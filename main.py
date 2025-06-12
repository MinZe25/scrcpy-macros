import sys
import subprocess
import win32gui
import win32con
import time
import math
import json
import os
import win32api
import re
import threading
import queue

from PyQt5.QtCore import QSizeF, QPointF, pyqtSignal, Qt, QPoint, QRectF, QTimer, QEvent, QObject
from PyQt5.QtGui import QKeySequence, QPainter, QColor, QFont, QFontMetrics, QMouseEvent, QKeyEvent, QWindow
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSpacerItem, QSizePolicy, QPushButton, QFrame, QVBoxLayout,
    QMainWindow, QSizeGrip, QStackedWidget, QApplication, QMessageBox
)

# Import the settings dialog from the other file
# Make sure 'settings_dialog.py' is in the same directory
try:
    from settings_dialog import SettingsDialog
except ImportError:
    print("CRITICAL ERROR: Could not find 'scrcpy_settings_dialog.py'. Please ensure it is in the same directory.")


# Helper class for non-blocking subprocess output reading (Unchanged)
class NonBlockingStreamReader:
    def __init__(self, stream):
        self._stream = stream
        self._queue = queue.Queue()

        def _populateQueue(stream, q):
            for line in iter(stream.readline, b''):
                if line:
                    q.put(line)
            stream.close()

        self._thread = threading.Thread(target=_populateQueue, args=(self._stream, self._queue))
        self._thread.daemon = True
        self._thread.start()

    def readline(self):
        try:
            return self._queue.get(block=False)
        except queue.Empty:
            return None


# --- Constants ---
SCRCPY_WINDOW_TITLE_BASE = "Lindo_Scrcpy_Instance"
SCRCPY_ASPECT_RATIO = 16.0 / 9.0
SCRCPY_NATIVE_WIDTH = 1920
SCRCPY_NATIVE_HEIGHT = 1080
KEYMAP_FILE = "keymaps.json"
SETTINGS_FILE = "scrcpy_instances.json"  # File to store instance settings

# --- Global Stylesheet (Unchanged) ---
GLOBAL_STYLESHEET = """
QMainWindow {
    background-color: #282a36;
    border-radius: 10px;
}
#TitleBar {
    background-color: #21222C;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
#TitleBar QLabel {
    color: #f8f8f2;
    padding-left: 10px;
    font-size: 14px;
    font-weight: bold;
}
#TitleBar QPushButton {
    background-color: transparent;
    border: none;
    padding: 5px;
    border-radius: 5px;
    color: #f8f8f2;
    font-size: 16px;
    min-width: 30px;
    min-height: 30px;
}
#TitleBar QPushButton:hover {
    background-color: #44475a;
}
#TitleBar QPushButton#CloseButton:hover {
    background-color: #ff5555;
}
#SidebarFrame {
    background-color: #21222C;
    border-bottom-left-radius: 10px;
    padding: 5px;
}
#SidebarButton {
    background-color: #44475a;
    color: #f8f8f2;
    border: none;
    border-radius: 8px;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    font-size: 18px;
    margin: 5px;
}
#SidebarButton:hover {
    background-color: #6272a4;
}
#SidebarButton:pressed {
    background-color: #bd93f9;
}
#MainContentWidget {
    background-color: #282a36;
    border-bottom-right-radius: 10px;
}
#MainContentAreaWidget QLabel {
    background-color: #383a59;
    border: 2px dashed #f8f8f2;
    border-radius: 8px;
    color: #f8f8f2;
    font-size: 16px;
    padding: 20px;
}
QDialog {
    background-color: #282a36;
    border: 1px solid #6272a4;
    border-radius: 10px;
    color: #f8f8f2;
}
QDialog QLabel {
    color: #f8f8f2;
}
"""


# --- Keymap Class (Unchanged) ---
class Keymap:
    def __init__(self, normalized_size: tuple, keycombo: list, normalized_position: tuple, type: str = "circle"):
        self.normalized_size = QSizeF(normalized_size[0], normalized_size[1])
        self.keycombo = keycombo
        self.normalized_position = QPointF(normalized_position[0], normalized_position[1])
        self.type = type

    def to_dict(self):
        return {
            "normalized_size": [self.normalized_size.width(), self.normalized_size.height()],
            "keycombo": self.keycombo,
            "normalized_position": [self.normalized_position.x(), self.normalized_position.y()],
            "type": self.type
        }

    @staticmethod
    def from_dict(data: dict):
        return Keymap(
            normalized_size=tuple(data["normalized_size"]),
            keycombo=data["keycombo"],
            normalized_position=tuple(data["normalized_position"]),
            type=data["type"]
        )


# --- OverlayWidget Class (Unchanged) ---
class OverlayWidget(QWidget):
    keymaps_changed = pyqtSignal(list)

    def __init__(self, keymaps: list = None, parent=None, is_transparent_to_mouse: bool = False):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, is_transparent_to_mouse)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setFocusPolicy(Qt.StrongFocus if not is_transparent_to_mouse else Qt.NoFocus)
        self.keymaps = keymaps if keymaps is not None else []
        self.edit_mode_active = False
        self._dragging_keymap = None
        self._creating_keymap = False
        self._drag_start_pos_local = QPoint()
        self._keymap_original_pixel_pos = QPoint()
        self._selected_keymap_for_combo_edit = None
        self._pending_modifier_key = None
        self.setMouseTracking(True)

    def _get_key_text(self, qt_key_code: int) -> str:
        if qt_key_code == Qt.Key_Shift: return "S"
        if qt_key_code == Qt.Key_Control: return "C"
        if qt_key_code == Qt.Key_Alt: return "A"
        return QKeySequence(qt_key_code).toString()

    def set_keymaps(self, keymaps_list: list):
        self.keymaps = keymaps_list
        self.update()

    def set_edit_mode(self, active: bool):
        self.edit_mode_active = active
        if not self.testAttribute(Qt.WA_TransparentForMouseEvents):
            self.setFocusPolicy(Qt.StrongFocus if active else Qt.NoFocus)
        if not active:
            self._dragging_keymap = None
            self._creating_keymap = False
            self._selected_keymap_for_combo_edit = None
            self._pending_modifier_key = None
            self.unsetCursor()
            self.keymaps_changed.emit(self.keymaps)
        self.update()

    # ... (paintEvent and mouse/key events are unchanged) ...
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        if self.edit_mode_active:
            painter.setBrush(QColor(0, 0, 0, 60))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())
            grid_size = 50
            painter.setPen(QColor(100, 100, 100, 80))
            for x in range(0, self.width(), grid_size): painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), grid_size): painter.drawLine(0, y, self.width(), y)
        for keymap in self.keymaps:
            pixel_x = keymap.normalized_position.x() * self.width()
            pixel_y = keymap.normalized_position.y() * self.height()
            pixel_width = keymap.normalized_size.width() * self.width()
            pixel_height = keymap.normalized_size.height() * self.height()
            keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                painter.setPen(QColor(255, 255, 0))
                painter.setBrush(QColor(255, 255, 0, 50))
                painter.drawRoundedRect(keymap_rect.adjusted(-5, -5, 5, 5), 5, 5)
            elif self.edit_mode_active and keymap == self._dragging_keymap:
                painter.setPen(QColor(0, 255, 255))
                painter.setBrush(QColor(0, 255, 255, 50))
                painter.drawRoundedRect(keymap_rect.adjusted(-3, -3, 3, 3), 3, 3)
            if keymap.type == "circle":
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 120))
                painter.drawEllipse(keymap_rect)
                key_texts = [self._get_key_text(kc) for kc in keymap.keycombo]
                display_text = "+".join(key_texts) if key_texts else "KEY"
                font = painter.font()
                font.setFamily("Inter")
                max_font_size, min_font_size = 72, 6
                for font_size in range(max_font_size, min_font_size - 1, -1):
                    font.setPointSize(font_size)
                    painter.setFont(font)
                    metrics = QFontMetrics(font)
                    text_bounding_rect = metrics.boundingRect(display_text)
                    if text_bounding_rect.width() <= keymap_rect.width() * 0.9 and \
                            text_bounding_rect.height() <= keymap_rect.height() * 0.9:
                        break
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(keymap_rect, Qt.AlignCenter, display_text)
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                x_button_size_pixels = 25
                x_button_rect = QRectF(keymap_rect.right() - x_button_size_pixels / 2,
                                       keymap_rect.top() - x_button_size_pixels / 2, x_button_size_pixels,
                                       x_button_size_pixels)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 200))
                painter.drawEllipse(x_button_rect)
                font = painter.font()
                font.setPointSize(int(x_button_size_pixels * 0.7))
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(x_button_rect, Qt.AlignCenter, "X")
        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        if not self.edit_mode_active: return super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._drag_start_pos_local = event.pos()
            if self._selected_keymap_for_combo_edit:
                selected_keymap = self._selected_keymap_for_combo_edit
                pixel_x, pixel_y = selected_keymap.normalized_position.x() * self.width(), selected_keymap.normalized_position.y() * self.height()
                pixel_width, pixel_height = selected_keymap.normalized_size.width() * self.width(), selected_keymap.normalized_size.height() * self.height()
                selected_keymap_pixel_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)
                x_button_size_pixels = 25
                x_button_rect = QRectF(selected_keymap_pixel_rect.right() - x_button_size_pixels / 2,
                                       selected_keymap_pixel_rect.top() - x_button_size_pixels / 2,
                                       x_button_size_pixels, x_button_size_pixels)
                if x_button_rect.contains(event.pos()):
                    self.keymaps.remove(selected_keymap)
                    self._selected_keymap_for_combo_edit = None
                    self.keymaps_changed.emit(self.keymaps)
                    self.update()
                    return event.accept()
            self._selected_keymap_for_combo_edit = None
            clicked_on_existing_keymap = False
            for keymap in self.keymaps:
                pixel_x, pixel_y = keymap.normalized_position.x() * self.width(), keymap.normalized_position.y() * self.height()
                pixel_width, pixel_height = keymap.normalized_size.width() * self.width(), keymap.normalized_size.height() * self.height()
                keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)
                if keymap_rect.contains(event.pos()):
                    self._dragging_keymap = keymap
                    self._keymap_original_pixel_pos = QPoint(int(pixel_x), int(pixel_y))
                    clicked_on_existing_keymap = True
                    break
            if not clicked_on_existing_keymap:
                self._creating_keymap = True
                new_keymap = Keymap(normalized_size=(0.01, 0.01), keycombo=[],
                                    normalized_position=(event.pos().x() / self.width(),
                                                         event.pos().y() / self.height()))
                self.keymaps.append(new_keymap)
                self._dragging_keymap = new_keymap
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.edit_mode_active: return super().mouseMoveEvent(event)
        if self._dragging_keymap:
            if self._creating_keymap:
                dx, dy = event.pos().x() - self._drag_start_pos_local.x(), event.pos().y() - self._drag_start_pos_local.y()
                side_length = min(abs(dx), abs(dy))
                current_pixel_x = self._drag_start_pos_local.x()
                if dx < 0: current_pixel_x = self._drag_start_pos_local.x() - side_length
                current_pixel_y = self._drag_start_pos_local.y()
                if dy < 0: current_pixel_y = self._drag_start_pos_local.y() - side_length
                self._dragging_keymap.normalized_position = QPointF(current_pixel_x / self.width(),
                                                                    current_pixel_y / self.height())
                self._dragging_keymap.normalized_size = QSizeF(side_length / self.width(), side_length / self.height())
                min_norm_size_w, min_norm_size_h = 10 / self.width(), 10 / self.height()
                if self._dragging_keymap.normalized_size.width() < min_norm_size_w: self._dragging_keymap.normalized_size.setWidth(
                    min_norm_size_w)
                if self._dragging_keymap.normalized_size.height() < min_norm_size_h: self._dragging_keymap.normalized_size.setHeight(
                    min_norm_size_h)
            else:
                delta = event.pos() - self._drag_start_pos_local
                new_pixel_x, new_pixel_y = self._keymap_original_pixel_pos.x() + delta.x(), self._keymap_original_pixel_pos.y() + delta.y()
                self._dragging_keymap.normalized_position = QPointF(new_pixel_x / self.width(),
                                                                    new_pixel_y / self.height())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.edit_mode_active: return super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            release_pos = event.pos()
            try:
                distance_moved = QPointF(release_pos - self._drag_start_pos_local).norm()
            except AttributeError:
                dx, dy = release_pos.x() - self._drag_start_pos_local.x(), release_pos.y() - self._drag_start_pos_local.y()
                distance_moved = math.sqrt(dx * dx + dy * dy)
            if self._dragging_keymap:
                if self._creating_keymap:
                    if distance_moved < 5:
                        self.keymaps.remove(self._dragging_keymap)
                        default_pixel_diameter = 100
                        new_norm_width, new_norm_height = default_pixel_diameter / self.width(), default_pixel_diameter / self.height()
                        new_norm_x, new_norm_y = (release_pos.x() - default_pixel_diameter // 2) / self.width(), (
                                release_pos.y() - default_pixel_diameter // 2) / self.height()
                        new_keymap = Keymap(normalized_size=(new_norm_width, new_norm_height), keycombo=[],
                                            normalized_position=(new_norm_x, new_norm_y))
                        self.keymaps.append(new_keymap)
                        self._selected_keymap_for_combo_edit = new_keymap
                    else:
                        self._selected_keymap_for_combo_edit = self._dragging_keymap
                else:
                    if distance_moved < 5: self._selected_keymap_for_combo_edit = self._dragging_keymap
                self._dragging_keymap = None
                self._creating_keymap = False
                self.update()
                self.keymaps_changed.emit(self.keymaps)

    def keyPressEvent(self, event: QKeyEvent):
        if not self.edit_mode_active: return super().keyPressEvent(event)
        if event.key() == Qt.Key_Delete and self._selected_keymap_for_combo_edit:
            self.keymaps.remove(self._selected_keymap_for_combo_edit)
            self._selected_keymap_for_combo_edit = None
            self.update()
            self.keymaps_changed.emit(self.keymaps)
            return event.accept()
        if self._selected_keymap_for_combo_edit:
            key = event.key()
            is_modifier_key = (key in [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta])
            if is_modifier_key:
                self._pending_modifier_key = key
            else:
                new_combo = []
                if self._pending_modifier_key:
                    new_combo.append(self._pending_modifier_key)
                    self._pending_modifier_key = None
                new_combo.append(key)
                self._selected_keymap_for_combo_edit.keycombo = new_combo
                self._selected_keymap_for_combo_edit = None
                self.update()
                self.keymaps_changed.emit(self.keymaps)
            event.accept()


# --- Sidebar Widget Class ---
class SidebarWidget(QFrame):
    instance_selected = pyqtSignal(int)
    edit_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, settings_list, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(60)
        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(5, 10, 5, 5)
        self.sidebar_layout.setSpacing(10)

        self.build_buttons(settings_list)

    def build_buttons(self, settings_list):
        # Clear existing buttons
        for i in reversed(range(self.sidebar_layout.count())):
            widget = self.sidebar_layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        # Build new buttons based on settings
        for i, settings in enumerate(settings_list):
            instance_name = settings.get("instance_name", f"Inst {i + 1}")
            btn = QPushButton("📱")
            btn.setObjectName("SidebarButton")
            btn.setToolTip(instance_name)
            btn.clicked.connect(lambda _, index=i: self.instance_selected.emit(index))
            self.sidebar_layout.addWidget(btn)

        self.sidebar_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.edit_button = QPushButton("✏️")
        self.edit_button.setObjectName("SidebarButton")
        self.edit_button.setToolTip("Edit Keymaps")
        self.edit_button.clicked.connect(self.edit_requested.emit)
        self.sidebar_layout.addWidget(self.edit_button)

        self.settings_button = QPushButton("⚙️")
        self.settings_button.setObjectName("SidebarButton")
        self.settings_button.setToolTip("Settings")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.sidebar_layout.addWidget(self.settings_button)


# --- Main Content Area Widget Class (UPDATED) ---
class MainContentAreaWidget(QWidget):
    scrcpy_container_ready = pyqtSignal()

    def __init__(self, instance_id: int, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("MainContentWidget")
        self.instance_id = instance_id
        self.settings = settings
        self.scrcpy_process = None
        self.scrcpy_hwnd = None
        self.scrcpy_qwindow = None
        self.scrcpy_container_widget = None
        self.scrcpy_stdout_reader = None
        self.scrcpy_stderr_reader = None
        self.scrcpy_output_timer = QTimer(self)
        self.scrcpy_display_id = None
        self.scrcpy_expected_title = f"{SCRCPY_WINDOW_TITLE_BASE}_{self.instance_id}"
        self.main_content_layout = QVBoxLayout(self)
        self.main_content_layout.setContentsMargins(0, 0, 0, 0)

        self.placeholder_label = QLabel(f"Loading Instance: {self.settings.get('instance_name', self.instance_id + 1)}")
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.main_content_layout.addWidget(self.placeholder_label)

        self.scrcpy_output_timer.timeout.connect(self._read_scrcpy_output)
        self.start_scrcpy()
        self.installEventFilter(self)

    def start_scrcpy(self):
        """Builds and launches the scrcpy command from the settings dictionary."""
        if self.scrcpy_process and self.scrcpy_process.poll() is None:
            print(f"Scrcpy for instance {self.instance_id} is already running.")
            return

        # --- Build Command from Settings ---
        cmd = ['scrcpy']
        if self.settings.get('use_tcpip'):
            cmd.extend([f"--tcpip={self.settings.get('tcpip_address', '')}"])
        # If not using TCP/IP, you might need to add "-s <serial>" for USB devices.
        # This example assumes either TCP/IP or the first available USB device.

        cmd.extend([f"--video-codec={self.settings.get('video_codec', 'h264')}"])
        cmd.extend([f"--max-fps={str(self.settings.get('max_fps', 60))}"])

        display_str = f"--new-display={self.settings.get('resolution', '1920x1080')}"
        if self.settings.get('density'):
            display_str += f"/{self.settings.get('density', 320)}"
        cmd.append(display_str)

        cmd.extend([f"--window-title={self.scrcpy_expected_title}"])

        if self.settings.get('start_app'):
            cmd.extend([f'--start-app', self.settings.get('start_app')])
        if self.settings.get('turn_screen_off'):
            cmd.append('-S')
        if self.settings.get('no_decorations'):
            cmd.append('--no-vd-system-decorations')

        print(f"Launching instance {self.instance_id} with command: {' '.join(cmd)}")

        try:
            self.scrcpy_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                   creationflags=subprocess.CREATE_NO_WINDOW, universal_newlines=True)
            self.scrcpy_stdout_reader = NonBlockingStreamReader(self.scrcpy_process.stdout)
            self.scrcpy_stderr_reader = NonBlockingStreamReader(self.scrcpy_process.stderr)
            self.scrcpy_output_timer.start(100)
            QTimer.singleShot(2000, self.find_and_embed_scrcpy)
        except FileNotFoundError:
            self.placeholder_label.setText("Error: scrcpy not found in PATH.")
        except Exception as e:
            self.placeholder_label.setText(f"Error launching scrcpy: {e}")

    def stop_scrcpy(self):
        """Safely stops the running scrcpy process for this instance."""
        if self.scrcpy_process and self.scrcpy_process.poll() is None:
            print(f"Stopping scrcpy process for instance {self.instance_id} (PID: {self.scrcpy_process.pid})")
            self.scrcpy_process.terminate()
            try:
                self.scrcpy_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.scrcpy_process.kill()
        self.scrcpy_process = None

    # ... (other methods like find_and_embed_scrcpy, _read_scrcpy_output are largely unchanged) ...
    def find_and_embed_scrcpy(self):
        if not self.scrcpy_process or self.scrcpy_process.poll() is not None:
            print(f"Scrcpy process for instance {self.instance_id} has terminated.")
            self.placeholder_label.setText(f"Scrcpy for Instance {self.instance_id} failed or was closed.")
            return
        self.scrcpy_hwnd = win32gui.FindWindow(None, self.scrcpy_expected_title)
        if self.scrcpy_hwnd:
            self.scrcpy_qwindow = QWindow.fromWinId(self.scrcpy_hwnd)
            self.scrcpy_container_widget = QWidget.createWindowContainer(self.scrcpy_qwindow, self)
            self.main_content_layout.replaceWidget(self.placeholder_label, self.scrcpy_container_widget)
            self.placeholder_label.hide()
            self.placeholder_label.deleteLater()
            self.scrcpy_container_ready.emit()
        else:
            QTimer.singleShot(1000, self.find_and_embed_scrcpy)

    def _read_scrcpy_output(self):
        # This method helps debug scrcpy launch issues
        if not self.scrcpy_process: return self.scrcpy_output_timer.stop()
        stdout = self.scrcpy_stdout_reader.readline()
        if stdout: print(f"Scrcpy STDOUT (Inst {self.instance_id}): {stdout.strip()}")
        stderr = self.scrcpy_stderr_reader.readline()
        if stderr: print(f"Scrcpy STDERR (Inst {self.instance_id}): {stderr.strip()}")

    def eventFilter(self, source, event):
        # Ensures the embedded window resizes correctly
        if source == self and event.type() == QEvent.Resize and self.scrcpy_hwnd:
            win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, self.width(), self.height(), True)
            return True
        return super().eventFilter(source, event)


# --- Main Application Window (UPDATED) ---
class MyQtApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bonito Integrated Controller")
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet(GLOBAL_STYLESHEET)

        # --- Load Settings First ---
        self.settings = self._load_app_settings()
        self.main_content_pages = []

        # --- Main Layout ---
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout = QHBoxLayout()
        self.main_layout.addLayout(self.content_layout)

        # --- Build UI From Settings ---
        self.sidebar = None  # Placeholder
        self.stacked_widget = QStackedWidget(self)  # Must be created before building UI
        self.content_layout.addWidget(self.stacked_widget, 1)

        self._build_ui_from_settings()

        # --- Overlays & Other Setup ---
        self.edit_mode_active = False
        self.current_instance_keymaps = []  # This will be managed by the instance pages later
        self.play_overlay = OverlayWidget(keymaps=self.current_instance_keymaps, is_transparent_to_mouse=True,
                                          parent=self)
        self.edit_overlay = OverlayWidget(keymaps=self.current_instance_keymaps, is_transparent_to_mouse=False,
                                          parent=self)
        self.edit_overlay.hide()

        # In a real app, keymaps should be saved per-instance
        self.load_keymaps_from_local_json()

    def _load_app_settings(self):
        """Loads instance configurations from a JSON file."""
        if not os.path.exists(SETTINGS_FILE):
            print(f"'{SETTINGS_FILE}' not found. Creating with default settings.")
            # Create a default settings file for one instance
            default_settings = [{
                "instance_name": "Default Instance", "use_tcpip": True, "tcpip_address": "192.168.1.100",
                "video_codec": "h265", "max_fps": 60, "resolution": "1920x1080",
                "start_app": "com.ankama.dofustouch", "turn_screen_off": True, "no_decorations": False
            }]
            self._save_app_settings(default_settings)
            return default_settings

        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Basic validation
                if isinstance(settings, list) and all(isinstance(s, dict) for s in settings):
                    return settings
                else:
                    raise ValueError("Settings file is not a list of dictionaries.")
        except Exception as e:
            print(f"Error loading settings from '{SETTINGS_FILE}': {e}")
            QMessageBox.critical(self, "Settings Error",
                                 f"Could not load or parse '{SETTINGS_FILE}'. Please check the file or delete it to generate a new one.")
            return []  # Return empty list on error

    def _save_app_settings(self, settings_list):
        """Saves the given list of settings to the JSON file."""
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings_list, f, indent=4)
            print(f"Instance settings saved to '{SETTINGS_FILE}'.")
        except Exception as e:
            print(f"Error saving settings: {e}")

    def _build_ui_from_settings(self):
        """Constructs or reconstructs the sidebar and instance pages from self.settings."""
        # --- Create Sidebar ---
        if self.sidebar:
            self.content_layout.removeWidget(self.sidebar)
            self.sidebar.deleteLater()

        self.sidebar = SidebarWidget(self.settings, self)
        self.sidebar.instance_selected.connect(self.stacked_widget.setCurrentIndex)
        self.sidebar.edit_requested.connect(self.toggle_edit_mode)
        self.sidebar.settings_requested.connect(self.show_settings_dialog)
        self.content_layout.insertWidget(0, self.sidebar)

        # --- Create Instance Pages ---
        # Clear existing pages and processes
        for page in self.main_content_pages:
            page.stop_scrcpy()
            self.stacked_widget.removeWidget(page)
            page.deleteLater()
        self.main_content_pages.clear()

        # Create new pages from settings
        for i, instance_settings in enumerate(self.settings):
            page = MainContentAreaWidget(instance_id=i, settings=instance_settings, parent=self)
            self.stacked_widget.addWidget(page)
            self.main_content_pages.append(page)

        print(f"UI built for {len(self.settings)} instance(s).")
        if self.main_content_pages:
            self.stacked_widget.setCurrentIndex(0)

    def _rebuild_ui_from_settings(self):
        """Saves current settings and completely rebuilds the UI."""
        self._save_app_settings(self.settings)
        # Give a moment for things to process before rebuilding
        QTimer.singleShot(100, self._build_ui_from_settings)

    def show_settings_dialog(self):
        """Opens the settings dialog and rebuilds the UI if settings are saved."""
        print("Opening settings dialog...")
        try:
            # Pass the current settings to the dialog
            dialog = SettingsDialog(current_settings=self.settings, parent=self)
            if dialog.exec_():  # This blocks until the dialog is closed
                new_settings = dialog.get_settings()
                if new_settings is not None:
                    print("Settings dialog accepted. Rebuilding UI...")
                    self.settings = new_settings
                    self._rebuild_ui_from_settings()
            else:
                print("Settings dialog cancelled.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open settings dialog: {e}")
            print(f"Error showing settings dialog: {e}")

    def closeEvent(self, event):
        """Ensures all scrcpy processes are terminated on exit."""
        print("Closing application, stopping all scrcpy instances...")
        for page in self.main_content_pages:
            page.stop_scrcpy()
        event.accept()

    # ... (Other methods like keyPressEvent, toggle_edit_mode, etc. are unchanged) ...
    def load_keymaps_from_local_json(self):
        if not os.path.exists(KEYMAP_FILE): return
        try:
            with open(KEYMAP_FILE, 'r') as f:
                self.current_instance_keymaps[:] = [Keymap.from_dict(km) for km in json.load(f)]
            self.play_overlay.set_keymaps(self.current_instance_keymaps)
            self.edit_overlay.set_keymaps(self.current_instance_keymaps)
        except Exception as e:
            print(f"Error loading keymaps: {e}")

    def toggle_edit_mode(self):
        self.edit_mode_active = not self.edit_mode_active
        self.edit_overlay.set_edit_mode(self.edit_mode_active)
        if self.edit_mode_active:
            self.play_overlay.hide()
            self.edit_overlay.show()
            self.edit_overlay.setFocus()
        else:
            self.edit_overlay.hide()
            self.play_overlay.show()
            self.setFocus()  # Bring focus back to main window for keymaps

    def keyPressEvent(self, event: QKeyEvent):
        if self.edit_mode_active:
            self.edit_overlay.keyPressEvent(event)
        else:
            # Logic to handle keymaps when not in edit mode
            pass


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MyQtApp()
    window.show()
    sys.exit(app.exec_())
