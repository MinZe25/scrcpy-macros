import sys
import subprocess
import win32gui
import win32con
import time
import math  # Import math for sqrt if .norm() is not available
import json  # For serializing/deserializing keymap data
import os  # For checking file existence
import win32api  # Added for simulating mouse taps
import re  # For regex parsing
import threading
import queue
from PyQt5.QtCore import QSizeF, QPointF, pyqtSignal, Qt, QPoint, QRectF, QTimer, QEvent, QRect, QObject
from PyQt5.QtGui import QKeySequence, QPainter, QColor, QFontMetrics, QMouseEvent, QKeyEvent, QFont, QWindow
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpacerItem, QSizePolicy, QPushButton, QFrame, QVBoxLayout, \
    QMainWindow, QSizeGrip, QStackedWidget, QApplication

from keymap import Keymap
from main_content_area_widget import MainContentAreaWidget
from non_blocking_stream_reader import NonBlockingStreamReader
from overlay_widget import OverlayWidget
from settings_dialog import SettingsDialog
from sidebar_widget import SidebarWidget

# Helper class for non-blocking subprocess output reading


# Constants for window resizing
RESIZE_BORDER_WIDTH = 8
CORNER_DRAG = True
LEFT = 1
RIGHT = 2
TOP = 4
BOTTOM = 8
TOP_LEFT = 5
TOP_RIGHT = 6
BOTTOM_LEFT = 9
BOTTOM_RIGHT = 10
SCRCPY_WINDOW_TITLE_BASE = "Lindo_Scrcpy_Instance"

# Aspect ratio of the Scrcpy display
# From '--new-display=1920x1080'
SCRCPY_ASPECT_RATIO = 16.0 / 9.0
SCRCPY_NATIVE_WIDTH = 1920  # Native resolution for ADB tap commands
SCRCPY_NATIVE_HEIGHT = 1080  # Native resolution for ADB tap commands
KEYMAP_FILE = "keymaps.json"  # Local JSON file for keymap storage


# --- Main Application Window ---
class MyQtApp(QMainWindow):
    _gripSize = 8
    keyboard_status_updated = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bonito Integrated Controller")
        self.settings = {}
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet(self.load_stylesheet_from_file('style.css'))
        self.setMouseTracking(True)
        self.edit_mode_active = False

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)

        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.content_layout = QHBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.main_layout.addLayout(self.content_layout, 1)

        self.load_settings_from_local_json()
        self.num_instances = len(self.settings.get("instances", []))
        device_serials = [None] * self.num_instances

        self.sidebar = SidebarWidget(num_instances=self.num_instances, parent=self)
        self.sidebar.edit_requested.connect(self.toggle_edit_mode)
        self.sidebar.settings_requested.connect(self.show_settings_dialog)
        self.content_layout.addWidget(self.sidebar)

        self.stacked_widget = QStackedWidget(self)
        self.content_layout.addWidget(self.stacked_widget, 1)

        self.main_content_pages = []
        for i in range(self.num_instances):
            serial = device_serials[i] if i < len(device_serials) else None
            page = MainContentAreaWidget(instance_id=i, title_base=SCRCPY_WINDOW_TITLE_BASE, settings=self.settings.get("instances")[i],
                                         device_serial=serial, parent=self)
            page.scrcpy_container_ready.connect(self.on_scrcpy_container_ready)
            self.stacked_widget.addWidget(page)
            self.main_content_pages.append(page)

        self.sidebar.instance_selected.connect(self.stacked_widget.setCurrentIndex)
        self.stacked_widget.currentChanged.connect(self._on_stacked_widget_page_changed)

        if self.num_instances > 0:
            self.stacked_widget.setCurrentIndex(0)

        self.update_max_restore_button()

        self.current_instance_keymaps = []
        self.play_overlay = OverlayWidget(keymaps=self.current_instance_keymaps, is_transparent_to_mouse=True,
                                          general_settings=self.settings.get("general_settings", {}),
                                          parent=self)
        self.edit_overlay = OverlayWidget(keymaps=self.current_instance_keymaps,
                                          is_transparent_to_mouse=False,
                                          general_settings=self.settings.get("general_settings", {}),
                                          parent=self)
        self.edit_overlay.keymaps_changed.connect(self.save_keymaps_to_local_json)

        self.play_overlay.show()
        self.edit_overlay.hide()

        self.load_keymaps_from_local_json()

        self.is_soft_keyboard_active = False
        self.keyboard_check_timer = QTimer(self)
        self.keyboard_check_timer.setInterval(250)  # Check 4 times a second
        self.keyboard_check_timer.timeout.connect(self._start_keyboard_status_check)
        self.keyboard_check_timer.start()

        self.keyboard_status_updated.connect(self._update_keyboard_status)

    def load_stylesheet_from_file(self, filepath: str) -> str:
        """
        Loads a stylesheet from a given file path and returns its content as a string.
        Args:
            filepath (str): The path to the CSS file.
        Returns:
            str: The content of the CSS file, or an empty string if the file is not found.
        """
        if not os.path.exists(filepath):
            print(f"Warning: Stylesheet file not found at {filepath}")
            return ""

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                stylesheet_content = f.read()
            return stylesheet_content
        except Exception as e:
            print(f"Error loading stylesheet from {filepath}: {e}")
            return ""

    def get_key_text_for_app(self, qt_key_code: int) -> str:
        if qt_key_code == Qt.Key_Shift: return "Shift"
        if qt_key_code == Qt.Key_Control: return "Control"
        if qt_key_code == Qt.Key_Alt: return "Alt"
        return QKeySequence(qt_key_code).toString()

    def send_adb_keyevent(self, keycode: str):
        current_page = self.stacked_widget.currentWidget()
        if current_page and current_page.scrcpy_display_id is not None:
            device_ip = "192.168.1.38"
            adb_cmd = ['adb', '-s', device_ip, 'shell', 'input', 'keyevent', keycode]
            try:
                subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                print(f"Sent ADB keyevent '{keycode}' to {device_ip}")
            except Exception as e:
                print(f"Error sending ADB keyevent: {e}")
        else:
            print(f"Cannot send ADB keyevent '{keycode}': No active Scrcpy page or display ID not detected.")

    def send_scrcpy_tap(self, x: int, y: int):
        current_page = self.stacked_widget.currentWidget()
        if current_page and current_page.scrcpy_display_id is not None:
            display_id, device_ip = current_page.scrcpy_display_id, "192.168.1.38"
            adb_cmd = ['adb', '-s', device_ip, 'shell', 'input', '-d', str(display_id), 'tap', str(x), str(y)]
            try:
                subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                print(f"Sent ADB tap to {device_ip} (display {display_id}) at coordinates ({x}, {y})")
            except Exception as e:
                print(f"Error sending ADB tap: {e}")
        else:
            print("Cannot send ADB tap: No active Scrcpy page or display ID not detected.")

    def save_keymaps_to_local_json(self, keymaps_list: list):
        serializable_keymaps = [km.to_dict() for km in keymaps_list]
        try:
            with open(KEYMAP_FILE, 'w') as f:
                json.dump(serializable_keymaps, f, indent=4)
            print(f"Keymaps saved to {KEYMAP_FILE} successfully.")
        except Exception as e:
            print(f"Error saving keymaps to local JSON: {e}")

    def load_settings_from_local_json(self):
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                self.settings = json.load(f)
            print(f"Keymaps loaded from {'settings.json'}.")
        except Exception as e:
            print(f"Error loading keymaps from {'settings.json'}: {e}. Starting with empty keymaps.")

    def load_keymaps_from_local_json(self):
        loaded_keymaps = []

        if os.path.exists(KEYMAP_FILE):
            try:
                with open(KEYMAP_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    loaded_keymaps = [Keymap.from_dict(km_data) for km_data in data]
                print(f"Keymaps loaded from {KEYMAP_FILE}.")
            except Exception as e:
                print(f"Error loading keymaps from {KEYMAP_FILE}: {e}. Starting with empty keymaps.")
        else:
            print(f"{KEYMAP_FILE} not found, starting with empty keymaps.")
            initial_keymap_circle = Keymap(normalized_size=(100 / SCRCPY_NATIVE_WIDTH, 100 / SCRCPY_NATIVE_HEIGHT),
                                           keycombo=[Qt.Key_Shift, Qt.Key_A],
                                           normalized_position=(50 / SCRCPY_NATIVE_WIDTH, 50 / SCRCPY_NATIVE_HEIGHT),
                                           type="circle")
            secondary_keymap_circle = Keymap(normalized_size=(100 / SCRCPY_NATIVE_WIDTH, 100 / SCRCPY_NATIVE_HEIGHT),
                                             keycombo=[Qt.Key_A], normalized_position=(400 / SCRCPY_NATIVE_WIDTH,
                                                                                       300 / SCRCPY_NATIVE_HEIGHT),
                                             type="circle")
            loaded_keymaps = [initial_keymap_circle, secondary_keymap_circle]
            self.save_keymaps_to_local_json(loaded_keymaps)

        self.current_instance_keymaps[:] = loaded_keymaps
        self.play_overlay.set_keymaps(self.current_instance_keymaps)
        self.edit_overlay.set_keymaps(self.current_instance_keymaps)

    def toggle_edit_mode(self):
        self.edit_mode_active = not self.edit_mode_active
        print(f"Edit mode toggled to: {self.edit_mode_active}")

        if self.edit_mode_active:
            self.play_overlay.hide()
            self.edit_overlay.show()
            self.edit_overlay.set_edit_mode(True)
            self.edit_overlay.setFocus()
            self.setFocus()
        else:
            self.edit_overlay.hide()
            self.play_overlay.show()
            self.edit_overlay.set_edit_mode(False)
            self.setFocus()

            current_page = self.stacked_widget.currentWidget()
            if current_page and current_page.scrcpy_hwnd:
                try:
                    win32gui.SetFocus(current_page.scrcpy_hwnd)
                    print(f"Set native focus to Scrcpy window HWND: {current_page.scrcpy_hwnd} on exiting edit mode.")
                except Exception as e:
                    print(f"Warning: Could not set native focus to Scrcpy window on exiting edit mode: {e}")

        self.update_global_overlay_geometry()

    def show_settings_dialog(self):
        print("Opening settings dialog...")
        try:
            dialog = SettingsDialog(current_settings=self.settings, parent=self)
            if dialog.exec_():
                print("Settings dialog saved")
                self.settings = dialog.get_settings()
                self.edit_overlay.reload_settings(self.settings)
                self.play_overlay.reload_settings(self.settings)
            else:
                print("Settings dialog cancelled")
        except Exception as e:
            print(f"Error showing settings dialog: {e}")

    @property
    def gripSize(self):
        return self._gripSize

    def setGripSize(self, size):
        if size == self._gripSize: return
        self._gripSize = max(2, size)
        self.updateGrips()

    def updateGrips(self):
        pass

    def resizeEvent(self, event):
        QMainWindow.resizeEvent(self, event)
        self.update_max_restore_button()
        QTimer.singleShot(0, self.update_global_overlay_geometry)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)

    def toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

        self.update_max_restore_button()
        self.update_global_overlay_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.update_global_overlay_geometry()

    def _is_soft_keyboard_active_blocking(self) -> bool:
        try:
            command = 'adb shell "dumpsys input_method | grep mInputShown"'
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True, timeout=5)
            return "mInputShown=true" in result.stdout.strip()
        except Exception:
            return False

    def _start_keyboard_status_check(self):
        if hasattr(self, '_keyboard_check_thread') and self._keyboard_check_thread.is_alive():
            return
        self._keyboard_check_thread = threading.Thread(target=self._run_keyboard_check_in_thread)
        self._keyboard_check_thread.daemon = True
        self._keyboard_check_thread.start()

    def _run_keyboard_check_in_thread(self):
        active = self._is_soft_keyboard_active_blocking()
        self.keyboard_status_updated.emit(active)

    def _update_keyboard_status(self, is_active: bool):
        if self.is_soft_keyboard_active == is_active:
            return  # No change, do nothing.
        self.is_soft_keyboard_active = is_active
        print(f"Soft keyboard active status changed to: {self.is_soft_keyboard_active}")
        if is_active:
            # Soft keyboard is ON. Give focus to Scrcpy.
            current_page = self.stacked_widget.currentWidget()
            if current_page and current_page.scrcpy_hwnd:
                try:
                    win32gui.SetFocus(current_page.scrcpy_hwnd)
                    print(f"Focus set to Scrcpy (HWND: {current_page.scrcpy_hwnd}) for direct input.")
                except Exception as e:
                    print(f"Warning: Could not set focus to Scrcpy window: {e}")
        else:
            # Soft keyboard is OFF. Give focus back to our app for keymaps.
            self.activateWindow()
            self.setFocus()
            print("Focus set to main application for keymap input.")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setBrush(QColor(40, 42, 54))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)

    def update_max_restore_button(self):
        pass

    def showEvent(self, event):
        super().showEvent(event)
        self.update_max_restore_button()
        self.update_global_overlay_geometry()

        current_page = self.stacked_widget.currentWidget()
        if current_page and current_page.scrcpy_hwnd:
            try:
                win32gui.SetFocus(current_page.scrcpy_hwnd)
                print(f"Set native focus to Scrcpy window HWND: {current_page.scrcpy_hwnd} on showEvent.")
            except Exception as e:
                print(f"Warning: Could not set native focus to Scrcpy window on showEvent: {e}")

    def _on_stacked_widget_page_changed(self, index: int):
        print(f"Stacked widget page changed to index: {index}")
        for i, page in enumerate(self.main_content_pages):
            if page.scrcpy_hwnd:
                if i == index:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_SHOW)
                    # No need for this resize here, it will happen after layout update
                    # page.resize_scrcpy_native_window()
                    try:
                        # win32gui.SetFocus(page.scrcpy_hwnd)
                        # And again, no need for this resize here
                        # page.resize_scrcpy_native_window()
                        print(f"Set native focus to Scrcpy window HWND: {page.scrcpy_hwnd} on page change.")
                    except Exception as e:
                        print(f"Warning: Could not set native focus to Scrcpy window on page change: {e}")
                else:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_HIDE)

        # Force a layout recalculation for the main window's central widget
        # This is the most crucial part to fix the sidebar
        self.main_widget.updateGeometry()
        self.main_layout.invalidate()
        self.content_layout.invalidate()  # Invalidate the specific layout containing sidebar and stacked widget

        # Give a small delay for Scrcpy window to potentially update its size/position
        # then update the overlay geometry. A short delay can be beneficial here.
        QTimer.singleShot(100, self.update_global_overlay_geometry)

    def on_scrcpy_container_ready(self):
        print("Received scrcpy_container_ready signal. Updating overlay geometry.")
        QTimer.singleShot(0, self.update_global_overlay_geometry)

    def update_global_overlay_geometry(self):
        try:
            current_page = self.stacked_widget.currentWidget()
            if current_page and hasattr(current_page,
                                        'scrcpy_container_widget') and current_page.scrcpy_container_widget:
                active_overlay_to_move = self.edit_overlay if self.edit_mode_active else self.play_overlay

                global_pos = current_page.scrcpy_container_widget.mapToGlobal(QPoint(0, 0))
                available_width, available_height = current_page.scrcpy_container_widget.width(), current_page.scrcpy_container_widget.height()

                target_height_by_width = int(available_width / SCRCPY_ASPECT_RATIO)
                if target_height_by_width <= available_height:
                    active_display_width, active_display_height = available_width, target_height_by_width
                else:
                    active_display_width, active_display_height = int(
                        available_height * SCRCPY_ASPECT_RATIO), available_height

                offset_x, offset_y = (available_width - active_display_width) // 2, (
                        available_height - active_display_height) // 2

                overlay_x, overlay_y = global_pos.x() + offset_x, global_pos.y() + offset_y
                active_overlay_to_move.setGeometry(overlay_x, overlay_y, active_display_width, active_display_height)
                active_overlay_to_move.raise_()

                if active_overlay_to_move.isHidden():
                    active_overlay_to_move.show()
            else:
                self.play_overlay.hide()
                self.edit_overlay.hide()
        except Exception as e:
            print(f"Error updating global overlay geometry: {e}")

    def keyReleaseEvent(self, event: QKeyEvent):
        if self.is_soft_keyboard_active:
            super().keyPressEvent(event)
            return

        if not self.edit_mode_active:
            if event.key() == Qt.Key_Alt:
                self.stacked_widget.setCurrentIndex(
                    (self.stacked_widget.currentIndex() + 1) % self.stacked_widget.count())
                event.accept()
                return

        # Important: Call the superclass method to ensure standard processing
        super().keyReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if self.is_soft_keyboard_active:
            super().keyPressEvent(event)
            return

        if not self.edit_mode_active:
            if event.key() == Qt.Key_Escape:
                self.send_adb_keyevent("KEYCODE_BACK")
                event.accept()
                return

            keymap_activated = False
            for keymap in self.current_instance_keymaps:
                if len(keymap.keycombo) > 0 and event.key() == keymap.keycombo[0]:
                    pixel_x_native = keymap.normalized_position.x() * SCRCPY_NATIVE_WIDTH
                    pixel_y_native = keymap.normalized_position.y() * SCRCPY_NATIVE_HEIGHT
                    pixel_width_native = keymap.normalized_size.width() * SCRCPY_NATIVE_WIDTH
                    pixel_height_native = keymap.normalized_size.height() * SCRCPY_NATIVE_HEIGHT
                    center_x_native = int(pixel_x_native + pixel_width_native / 2)
                    center_y_native = int(pixel_y_native + pixel_height_native / 2)
                    self.send_scrcpy_tap(center_x_native, center_y_native)
                    event.accept()
                    keymap_activated = True
                    break

            if not keymap_activated:
                super().keyPressEvent(event)
        else:
            self.edit_overlay.keyPressEvent(event)
            event.accept()

    def closeEvent(self, event):
        print("Closing application, stopping all Scrcpy processes...")
        self.keyboard_check_timer.stop()
        self.play_overlay.hide()
        self.edit_overlay.hide()
        self.play_overlay.deleteLater()
        self.edit_overlay.deleteLater()

        for page in self.main_content_pages:
            page.stop_scrcpy()

        super().closeEvent(event)


if __name__ == '__main__':
    def exception_hook(exctype, value, traceback_obj):
        sys.__excepthook__(exctype, value, traceback_obj)
        print(f"\n--- Unhandled Exception Detected ---")
        import traceback
        traceback.print_exception(exctype, value, traceback_obj)
        print("----------------------------------")


    sys.excepthook = exception_hook

    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 10))
    window = MyQtApp()
    window.show()
    sys.exit(app.exec_())
