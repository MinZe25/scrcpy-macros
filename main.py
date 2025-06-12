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


# Removed the settings_dialog import as requested by user.
# from settings_dialog import SettingsDialog


# Helper class for non-blocking subprocess output reading
class NonBlockingStreamReader:
    def __init__(self, stream):
        self._stream = stream
        self._queue = queue.Queue()

        def _populateQueue(stream, q):
            # Read until EOF
            for line in iter(stream.readline, b''):
                if line:  # Ensure line is not empty before putting in queue
                    q.put(line)
            stream.close()

        self._thread = threading.Thread(target=_populateQueue, args=(self._stream, self._queue))
        self._thread.daemon = True  # Thread dies with the main program
        self._thread.start()

    def readline(self):
        try:
            # Get line from queue, non-blocking
            return self._queue.get(block=False)
        except queue.Empty:
            return None


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

# --- Global Stylesheet ---
GLOBAL_STYLESHEET = """
QMainWindow {
    /* Styles for child widgets inside QMainWindow that are not handled by custom classes */
}

/* Custom Title Bar Styling */
#TitleBar {
    background-color: #21222C; /* Slightly darker than main window */
    border-top-left-radius: 10px; /* Still apply here for the visual look of the bar */
    border-top-right-radius: 10px;
}

#TitleBar QLabel {
    color: #f8f8f2; /* White text */
    padding-left: 10px;
    font-size: 14px;
    font-weight: bold;
}

#TitleBar QPushButton {
    background-color: #333642; /* Make button background visible even when not hovered */
    border: none;
    padding: 5px;
    border-radius: 5px;
    color: #f8f8f2;
    font-size: 16px;
    min-width: 30px; /* Ensure clickability */
    min-height: 30px;
}

#TitleBar QPushButton:hover {
    background-color: #44475a; /* Lighter on hover */
}

/* Close button specific styling for a distinct look */
#TitleBar QPushButton#CloseButton:hover {
    background-color: #ff5555; /* Red on hover */
}

/* Sidebar Styling */
#SidebarFrame { /* Using objectName for the frame */
    background-color: #21222C; /* Darker than main window */
    border-bottom-left-radius: 10px; /* Match main window's bottom left */
    padding: 5px;
}

#SidebarButton { /* For instance buttons */
    background-color: #44475a; /* Slightly lighter than sidebar background */
    color: #f8f8f2;
    border: none;
    border-radius: 8px; /* Rounded buttons */
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    font-size: 18px; /* Example icon size */
    margin: 5px; /* Spacing between buttons */
}

#SidebarButton:hover {
    background-color: #6272a4; /* Dracula purple on hover */
}

#SidebarButton:pressed {
    background-color: #bd93f9; /* Lighter purple on pressed */
}

#SettingsButton { /* For the settings button */
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

#SettingsButton:hover {
    background-color: #6272a4;
}

#SettingsButton:pressed {
    background-color: #bd93f9;
}

/* Main Content Area Styling */
#MainContentWidget { /* Using objectName for the main content widget */
    background-color: #282a36; /* Same as main window for seamless look */
    border-bottom-right-radius: 10px;
}

/* Specific styling for the QLabel within MainContentAreaWidget instances */
#MainContentWidget QLabel {
    background-color: #383a59; /* Slightly different dark shade */
    border: 2px dashed #f8f8f2;
    border-radius: 8px;
    color: #f8f8f2;
    font-size: 16px;
    padding: 20px;
}

/* Generic QDialog Styling (for settings dialog) */
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


# --- Keymap Class ---
class Keymap:
    """
    Represents a single keymap with its visual properties and associated key combination.
    Stores position and size as normalized floats (0.0 to 1.0).
    """

    def __init__(self, normalized_size: tuple, keycombo: list, normalized_position: tuple, type: str = "circle"):
        """
        Initialize a Keymap object.

        Args:
            normalized_size (tuple): A tuple (normalized_width, normalized_height) floats (0.0-1.0).
            keycombo (list): A list of Qt.Key values (integers) representing the key combination.
            normalized_position (tuple): A tuple (normalized_x, normalized_y) floats (0.0-1.0).
            type (str): The type of visual element for the keymap (e.g., "circle", "rectangle", "text").
        """
        self.normalized_size = QSizeF(normalized_size[0], normalized_size[1])
        self.keycombo = keycombo
        self.normalized_position = QPointF(normalized_position[0], normalized_position[1])
        self.type = type

    def to_dict(self):
        """Converts the Keymap object to a dictionary for JSON serialization."""
        return {
            "normalized_size": [self.normalized_size.width(), self.normalized_size.height()],
            "keycombo": self.keycombo,
            "normalized_position": [self.normalized_position.x(), self.normalized_position.y()],
            "type": self.type
        }

    @staticmethod
    def from_dict(data: dict):
        """Creates a Keymap object from a dictionary."""
        return Keymap(
            normalized_size=tuple(data["normalized_size"]),
            keycombo=data["keycombo"],
            normalized_position=tuple(data["normalized_position"]),
            type=data["type"]
        )


# --- OverlayWidget Class ---
class OverlayWidget(QWidget):
    keymaps_changed = pyqtSignal(list)  # Signal to notify parent of keymap changes

    def __init__(self, keymaps: list = None, parent=None, is_transparent_to_mouse: bool = False):
        """
        Initialize an OverlayWidget.

        Args:
            keymaps (list): A reference to the list of keymap objects.
            parent (QWidget): The parent widget.
            is_transparent_to_mouse (bool): If True, mouse events will pass through this widget.
        """
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Set transparency attribute ONLY ONCE based on init parameter
        self.setAttribute(Qt.WA_TransparentForMouseEvents, is_transparent_to_mouse)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        # Set focus policy to allow key events when in edit mode (if not transparent to mouse)
        # Otherwise, focus policy should allow events to pass through implicitly.
        self.setFocusPolicy(Qt.StrongFocus if not is_transparent_to_mouse else Qt.NoFocus)

        self.keymaps = keymaps if keymaps is not None else []

        self.edit_mode_active = False  # Controls visual elements like grid and selection
        self._dragging_keymap = None
        self._creating_keymap = False
        self._drag_start_pos_local = QPoint()  # Stores the QPoint of mousePressEvent (pixel)
        self._keymap_original_pixel_pos = QPoint()  # Original pixel position of keymap when drag starts
        self._selected_keymap_for_combo_edit = None
        self._pending_modifier_key = None  # To handle Shift+A, Ctrl+B etc.

        # Enable mouse tracking to show appropriate cursor in edit mode
        self.setMouseTracking(True)

    def _get_key_text(self, qt_key_code: int) -> str:
        """Converts a Qt.Key code to its string representation for display."""
        if qt_key_code == Qt.Key_Shift:
            return "S"
        elif qt_key_code == Qt.Key_Control:
            return "C"
        elif qt_key_code == Qt.Key_Alt:
            return "A"
        # For other keys, use QKeySequence to get the standard string
        return QKeySequence(qt_key_code).toString()

    def set_keymaps(self, keymaps_list: list):
        """Sets the keymaps from an external source. Assumes it's a shared list."""
        self.keymaps = keymaps_list  # We are given a reference to the shared list
        self.update()  # Redraw to show updated keymaps

    def set_edit_mode(self, active: bool):
        """
        Activates or deactivates the keymap editing mode for this specific overlay.
        This primarily affects drawing (grid, selection) and focus policy if this overlay is meant to interact.
        It DOES NOT change mouse transparency here.
        """
        self.edit_mode_active = active
        # Only set focus policy if this overlay is designed to capture events (i.e., not transparent to mouse)
        if not self.testAttribute(Qt.WA_TransparentForMouseEvents):
            self.setFocusPolicy(Qt.StrongFocus if active else Qt.NoFocus)

        if not active:
            # Clear any active editing states when leaving edit mode
            self._dragging_keymap = None
            self._creating_keymap = False
            self._selected_keymap_for_combo_edit = None
            self._pending_modifier_key = None
            self.unsetCursor()  # Reset cursor
            # Emit signal when exiting edit mode to save changes (only the edit overlay will do this)
            self.keymaps_changed.emit(self.keymaps)

        self.update()  # Request repaint to show/hide grid/selection

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        # Draw semi-transparent background if in edit mode (only the edit overlay)
        if self.edit_mode_active:
            painter.setBrush(QColor(0, 0, 0, 60))  # Black with 60 alpha (more transparent)
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())  # Cover the entire widget

            grid_size = 50  # Size of each grid cell
            painter.setPen(QColor(100, 100, 100, 80))  # Light grey, semi-transparent
            for x in range(0, self.width(), grid_size):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), grid_size):
                painter.drawLine(0, y, self.width(), y)

        for keymap in self.keymaps:
            # Convert normalized position and size to pixel coordinates
            pixel_x = keymap.normalized_position.x() * self.width()
            pixel_y = keymap.normalized_position.y() * self.height()
            pixel_width = keymap.normalized_size.width() * self.width()
            pixel_height = keymap.normalized_size.height() * self.height()

            keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)

            # Highlight selected keymap in edit mode
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                painter.setPen(QColor(255, 255, 0))  # Yellow highlight
                painter.setBrush(QColor(255, 255, 0, 50))  # Light yellow fill
                painter.drawRoundedRect(keymap_rect.adjusted(-5, -5, 5, 5), 5,
                                        5)  # Draw a slightly larger, rounded highlight
            elif self.edit_mode_active and keymap == self._dragging_keymap:
                painter.setPen(QColor(0, 255, 255))  # Cyan highlight for dragging
                painter.setBrush(QColor(0, 255, 255, 50))
                painter.drawRoundedRect(keymap_rect.adjusted(-3, -3, 3, 3), 3, 3)

            if keymap.type == "circle":
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 120))  # Red, 120 alpha
                painter.drawEllipse(keymap_rect)  # Draw ellipse using the keymap's rect

                # Prepare and draw text for the key combination
                key_texts = [self._get_key_text(kc) for kc in keymap.keycombo]
                display_text = "+".join(key_texts) if key_texts else "KEY"  # Default text if no key is set

                # Dynamically adjust font size to fit text within the keymap rectangle
                font = painter.font()
                font.setFamily("Inter")  # Use a clean, readable font
                max_font_size = 72  # Start with a large font size
                min_font_size = 6  # Minimum readable font size

                for font_size in range(max_font_size, min_font_size - 1, -1):
                    font.setPointSize(font_size)
                    painter.setFont(font)
                    metrics = QFontMetrics(font)
                    text_bounding_rect = metrics.boundingRect(display_text)

                    if text_bounding_rect.width() <= keymap_rect.width() * 0.9 and \
                            text_bounding_rect.height() <= keymap_rect.height() * 0.9:
                        break  # Found a font size that fits

                painter.setPen(QColor(255, 255, 255))  # White text for key combo
                painter.drawText(keymap_rect, Qt.AlignCenter, display_text)

            # Draw the 'X' button if in edit mode and this keymap is selected
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                x_button_size_pixels = 25
                x_button_rect = QRectF(
                    keymap_rect.right() - x_button_size_pixels / 2,
                    keymap_rect.top() - x_button_size_pixels / 2,
                    x_button_size_pixels,
                    x_button_size_pixels
                )

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
        if not self.edit_mode_active:
            super().mousePressEvent(event)
            return

        if event.button() == Qt.LeftButton:
            self._drag_start_pos_local = event.pos()

            if self._selected_keymap_for_combo_edit:
                selected_keymap = self._selected_keymap_for_combo_edit
                pixel_x = selected_keymap.normalized_position.x() * self.width()
                pixel_y = selected_keymap.normalized_position.y() * self.height()
                pixel_width = selected_keymap.normalized_size.width() * self.width()
                pixel_height = selected_keymap.normalized_size.height() * self.height()
                selected_keymap_pixel_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)

                x_button_size_pixels = 25
                x_button_rect = QRectF(
                    selected_keymap_pixel_rect.right() - x_button_size_pixels / 2,
                    selected_keymap_pixel_rect.top() - x_button_size_pixels / 2,
                    x_button_size_pixels,
                    x_button_size_pixels
                )

                if x_button_rect.contains(event.pos()):
                    self.keymaps.remove(selected_keymap)
                    self._selected_keymap_for_combo_edit = None
                    self.keymaps_changed.emit(self.keymaps)
                    self.update()
                    event.accept()
                    return

            self._selected_keymap_for_combo_edit = None

            clicked_on_existing_keymap = False
            for keymap in self.keymaps:
                pixel_x = keymap.normalized_position.x() * self.width()
                pixel_y = keymap.normalized_position.y() * self.height()
                pixel_width = keymap.normalized_size.width() * self.width()
                pixel_height = keymap.normalized_size.height() * self.height()
                keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)
                if keymap_rect.contains(event.pos()):
                    self._dragging_keymap = keymap
                    self._keymap_original_pixel_pos = QPoint(int(pixel_x), int(pixel_y))
                    clicked_on_existing_keymap = True
                    break

            if not clicked_on_existing_keymap:
                self._creating_keymap = True
                new_keymap = Keymap(normalized_size=(0.01, 0.01),
                                    keycombo=[],
                                    normalized_position=(event.pos().x() / self.width(),
                                                         event.pos().y() / self.height()))
                self.keymaps.append(new_keymap)
                self._dragging_keymap = new_keymap

            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mouseMoveEvent(event)
            return

        if self._dragging_keymap:
            if self._creating_keymap:
                dx = event.pos().x() - self._drag_start_pos_local.x()
                dy = event.pos().y() - self._drag_start_pos_local.y()
                side_length = min(abs(dx), abs(dy))
                current_pixel_x = self._drag_start_pos_local.x()
                if dx < 0:
                    current_pixel_x = self._drag_start_pos_local.x() - side_length
                current_pixel_y = self._drag_start_pos_local.y()
                if dy < 0:
                    current_pixel_y = self._drag_start_pos_local.y() - side_length

                self._dragging_keymap.normalized_position = QPointF(current_pixel_x / self.width(),
                                                                    current_pixel_y / self.height())
                self._dragging_keymap.normalized_size = QSizeF(side_length / self.width(),
                                                               side_length / self.height())

                min_norm_size_w = 10 / self.width()
                min_norm_size_h = 10 / self.height()
                if self._dragging_keymap.normalized_size.width() < min_norm_size_w:
                    self._dragging_keymap.normalized_size.setWidth(min_norm_size_w)
                if self._dragging_keymap.normalized_size.height() < min_norm_size_h:
                    self._dragging_keymap.normalized_size.setHeight(min_norm_size_h)
            else:
                delta = event.pos() - self._drag_start_pos_local
                new_pixel_x = self._keymap_original_pixel_pos.x() + delta.x()
                new_pixel_y = self._keymap_original_pixel_pos.y() + delta.y()
                self._dragging_keymap.normalized_position = QPointF(new_pixel_x / self.width(),
                                                                    new_pixel_y / self.height())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mouseReleaseEvent(event)
            return

        if event.button() == Qt.LeftButton:
            release_pos = event.pos()
            try:
                distance_moved = QPointF(release_pos - self._drag_start_pos_local).norm()
            except AttributeError:
                dx = release_pos.x() - self._drag_start_pos_local.x()
                dy = release_pos.y() - self._drag_start_pos_local.y()
                distance_moved = math.sqrt(dx * dx + dy * dy)

            if self._dragging_keymap:
                if self._creating_keymap:
                    if distance_moved < 5:
                        self.keymaps.remove(self._dragging_keymap)
                        default_pixel_diameter = 100
                        new_norm_width = default_pixel_diameter / self.width()
                        new_norm_height = default_pixel_diameter / self.height()
                        new_norm_x = (release_pos.x() - default_pixel_diameter // 2) / self.width()
                        new_norm_y = (release_pos.y() - default_pixel_diameter // 2) / self.height()
                        new_keymap = Keymap(normalized_size=(new_norm_width, new_norm_height),
                                            keycombo=[],
                                            normalized_position=(new_norm_x, new_norm_y))
                        self.keymaps.append(new_keymap)
                        self._selected_keymap_for_combo_edit = new_keymap
                    else:
                        self._selected_keymap_for_combo_edit = self._dragging_keymap
                else:
                    if distance_moved < 5:
                        self._selected_keymap_for_combo_edit = self._dragging_keymap
                self._dragging_keymap = None
                self._creating_keymap = False
                self.update()
                self.keymaps_changed.emit(self.keymaps)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if not self.edit_mode_active:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Delete and self._selected_keymap_for_combo_edit:
            self.keymaps.remove(self._selected_keymap_for_combo_edit)
            self._selected_keymap_for_combo_edit = None
            self.update()
            self.keymaps_changed.emit(self.keymaps)
            print("Keymap deleted.")
            event.accept()
            return

        if self._selected_keymap_for_combo_edit:
            key = event.key()
            is_modifier_key = (
                    key in [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R])
            if is_modifier_key:
                self._pending_modifier_key = key
                print(f"Pending modifier: {self._get_key_text(key)}")
            else:
                new_combo = []
                if self._pending_modifier_key:
                    new_combo.append(self._pending_modifier_key)
                    self._pending_modifier_key = None
                new_combo.append(key)
                self._selected_keymap_for_combo_edit.keycombo = new_combo
                self._selected_keymap_for_combo_edit = None
                print(f"Keymap combo set to: {[self._get_key_text(k) for k in new_combo]}")
                self.update()
                self.keymaps_changed.emit(self.keymaps)
            event.accept()
        else:
            super().keyPressEvent(event)


# --- Sidebar Widget Class ---
class SidebarWidget(QFrame):
    settings_requested = pyqtSignal()
    edit_requested = pyqtSignal()
    instance_selected = pyqtSignal(int)

    def __init__(self, num_instances: int = 5, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(60)
        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(5, 10, 5, 5)
        self.sidebar_layout.setSpacing(10)
        for i in range(num_instances):
            btn = QPushButton("💬")
            btn.setObjectName("SidebarButton")
            btn.clicked.connect(lambda _, index=i: self._on_instance_button_clicked(index))
            self.sidebar_layout.addWidget(btn)
        self.sidebar_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.edit_button = QPushButton("✏️")
        self.edit_button.setObjectName("SidebarButton")
        self.edit_button.clicked.connect(self.edit_requested.emit)
        self.sidebar_layout.addWidget(self.edit_button)
        self.settings_button = QPushButton("⚙️")
        self.settings_button.setObjectName("SidebarButton")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.sidebar_layout.addWidget(self.settings_button)

    def _on_instance_button_clicked(self, index: int):
        print(f"Sidebar: Instance button {index + 1} clicked, emitting index {index}.")
        self.instance_selected.emit(index)


# --- SideGrip Class ---
class SideGrip(QWidget):
    def __init__(self, parent, edge):
        QWidget.__init__(self, parent)
        if edge == Qt.LeftEdge:
            self.setCursor(Qt.SizeHorCursor)
            self.resizeFunc = self.resizeLeft
        elif edge == Qt.TopEdge:
            self.setCursor(Qt.SizeVerCursor)
            self.resizeFunc = self.resizeTop
        elif edge == Qt.RightEdge:
            self.setCursor(Qt.SizeHorCursor)
            self.resizeFunc = self.resizeRight
        else:
            self.setCursor(Qt.SizeVerCursor)
            self.resizeFunc = self.resizeBottom
        self.mousePos = None

    def resizeLeft(self, delta):
        window = self.window()
        width = max(window.minimumWidth(), window.width() - delta.x())
        geo = window.geometry()
        geo.setLeft(geo.right() - width)
        window.setGeometry(geo)

    def resizeTop(self, delta):
        window = self.window()
        height = max(window.minimumHeight(), window.height() - delta.y())
        geo = window.geometry()
        geo.setTop(geo.bottom() - height)
        window.setGeometry(geo)

    def resizeRight(self, delta):
        window = self.window()
        width = max(window.minimumWidth(), window.width() + delta.x())
        window.resize(width, window.height())

    def resizeBottom(self, delta):
        window = self.window()
        height = max(window.minimumHeight(), window.height() + delta.y())
        window.resize(window.width(), height)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mousePos = event.pos()

    def mouseMoveEvent(self, event):
        if self.mousePos is not None:
            delta = event.pos() - self.mousePos
            self.resizeFunc(delta)

    def mouseReleaseEvent(self, event):
        self.mousePos = None


# --- Main Content Area Widget Class ---
class MainContentAreaWidget(QWidget):
    scrcpy_container_ready = pyqtSignal()

    def __init__(self, instance_id: int, device_serial: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("MainContentWidget")
        self.instance_id = instance_id
        self.device_serial = device_serial
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
        self.main_content_layout.setSpacing(0)
        self.placeholder_label = QLabel(
            f"Loading Scrcpy for Instance {self.instance_id + 1}...\n"
            f"Device Serial: {self.device_serial if self.device_serial else 'Default/First available'}\n"
            f"Looking for window title: '{self.scrcpy_expected_title}'"
        )
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        self.main_content_layout.addWidget(self.placeholder_label)
        self.scrcpy_output_timer.timeout.connect(self._read_scrcpy_output)
        self.start_scrcpy()
        self.installEventFilter(self)

    def _read_scrcpy_output(self):
        if not self.scrcpy_process:
            self.scrcpy_output_timer.stop()
            return
        stdout_line = self.scrcpy_stdout_reader.readline()
        if stdout_line:
            line_str = stdout_line.strip()
            match = re.search(r'\(id=(\d+)\)', line_str)
            if match:
                self.scrcpy_display_id = int(match.group(1))
                print(f"Detected Scrcpy Display ID: {self.scrcpy_display_id} for instance {self.instance_id + 1}")
                self.scrcpy_output_timer.stop()
        stderr_line = self.scrcpy_stderr_reader.readline()
        if stderr_line:
            print(f"Scrcpy STDERR ({self.instance_id + 1}): {stderr_line.strip()}")

    def start_scrcpy(self):
        if self.scrcpy_process and self.scrcpy_process.poll() is None:
            print(f"Scrcpy for instance {self.instance_id + 1} is already running (PID: {self.scrcpy_process.pid}).")
            return
        print(f"Starting Scrcpy for Instance {self.instance_id + 1}...")
        try:
            scrcpy_cmd = ['scrcpy', '--video-codec=h265', '--max-fps=60', '--tcpip=192.168.1.38', '-S',
                          '--new-display=1920x1080', '--start-app=com.ankama.dofustouch',
                          f'--window-title={self.scrcpy_expected_title}', '--turn-screen-off']
            self.scrcpy_process = subprocess.Popen(scrcpy_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                   creationflags=subprocess.CREATE_NO_WINDOW, universal_newlines=True)
            print(f"Scrcpy process for instance {self.instance_id + 1} started with PID: {self.scrcpy_process.pid}")
            self.scrcpy_stdout_reader = NonBlockingStreamReader(self.scrcpy_process.stdout)
            self.scrcpy_stderr_reader = NonBlockingStreamReader(self.scrcpy_process.stderr)
            self.scrcpy_output_timer.start(100)
            QTimer.singleShot(2000, self.find_and_embed_scrcpy)
        except FileNotFoundError:
            print(f"Error: Scrcpy not found. Make sure 'scrcpy.exe' is in your system PATH or provide its full path.")
            self.placeholder_label.setText("Error: Scrcpy not found!")
        except Exception as e:
            print(f"Error starting Scrcpy for instance {self.instance_id + 1}: {e}")
            self.placeholder_label.setText(f"Error: {e}")

    def find_and_embed_scrcpy(self):
        if not self.scrcpy_process or self.scrcpy_process.poll() is not None:
            print(f"Scrcpy process for instance {self.instance_id + 1} is not running or has terminated.")
            self.placeholder_label.setText(f"Scrcpy process failed or closed for Instance {self.instance_id + 1}.")
            return
        self.scrcpy_hwnd = None

        def enum_windows_callback(hwnd, extra):
            if win32gui.GetWindowText(hwnd) == self.scrcpy_expected_title:
                self.scrcpy_hwnd = hwnd
                return False
            return True

        win32gui.EnumWindows(enum_windows_callback, None)
        if self.scrcpy_hwnd:
            self.scrcpy_qwindow = QWindow.fromWinId(self.scrcpy_hwnd)
            self.scrcpy_container_widget = QWidget.createWindowContainer(self.scrcpy_qwindow, self)
            self.scrcpy_container_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.scrcpy_container_widget.setMinimumSize(100, 100)
            self.main_content_layout.replaceWidget(self.placeholder_label, self.scrcpy_container_widget)
            self.placeholder_label.hide()
            win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_SHOW)
            self.resize_scrcpy_native_window()
            self.scrcpy_container_ready.emit()
            try:
                win32gui.SetFocus(self.scrcpy_hwnd)
                print(f"Set native focus to Scrcpy window HWND: {self.scrcpy_hwnd}")
            except Exception as e:
                print(f"Warning: Could not set native focus to Scrcpy window: {e}")
        else:
            QTimer.singleShot(1000, self.find_and_embed_scrcpy)

    def eventFilter(self, source, event):
        if source == self and event.type() == QEvent.Resize:
            self.resize_scrcpy_native_window()
            return True
        return super().eventFilter(source, event)

    def resize_scrcpy_native_window(self):
        if not self.scrcpy_hwnd or not self.scrcpy_container_widget:
            return
        container_rect = self.scrcpy_container_widget.rect()
        width, height = container_rect.width(), container_rect.height()
        try:
            win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, width, height, True)
        except Exception as e:
            print(f"Error resizing scrcpy_hwnd: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        if self.scrcpy_hwnd:
            win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_SHOW)
            self.resize_scrcpy_native_window()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.scrcpy_hwnd:
            win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_HIDE)

    def stop_scrcpy(self):
        if self.scrcpy_process and self.scrcpy_process.poll() is None:
            self.scrcpy_output_timer.stop()
            if self.scrcpy_hwnd:
                win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_HIDE)
                win32gui.SetParent(self.scrcpy_hwnd, 0)
            self.scrcpy_process.terminate()
            try:
                self.scrcpy_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.scrcpy_process.kill()
            self.scrcpy_process = None
            self.scrcpy_hwnd = None
            self.scrcpy_qwindow = None
            self.scrcpy_container_widget = None
            self.scrcpy_display_id = None
            self.scrcpy_stdout_reader = None
            self.scrcpy_stderr_reader = None
        elif self.scrcpy_process:
            self.scrcpy_process = None
            self.scrcpy_hwnd = None
            self.scrcpy_qwindow = None
            self.scrcpy_container_widget = None
            self.scrcpy_display_id = None
            self.scrcpy_stdout_reader = None
            self.scrcpy_stderr_reader = None


# --- Main Application Window ---
class MyQtApp(QMainWindow):
    _gripSize = 8
    keyboard_status_updated = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bonito Integrated Controller")
        self.settings = []
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet(GLOBAL_STYLESHEET)
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
        self.num_instances = 1
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
            page = MainContentAreaWidget(instance_id=i, device_serial=serial, parent=self)
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
                                          parent=self)
        self.edit_overlay = OverlayWidget(keymaps=self.current_instance_keymaps, is_transparent_to_mouse=False,
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

    def _get_key_text_for_app(self, qt_key_code: int) -> str:
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
            from settings_dialog import SettingsDialog
            dialog = SettingsDialog(current_settings=self.settings, parent=self)
            dialog.exec_()
            self.settings = dialog.get_settings()
            print("Settings dialog closed.")
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
                    page.resize_scrcpy_native_window()
                    try:
                        win32gui.SetFocus(page.scrcpy_hwnd)
                        print(f"Set native focus to Scrcpy window HWND: {page.scrcpy_hwnd} on page change.")
                    except Exception as e:
                        print(f"Warning: Could not set native focus to Scrcpy window on page change: {e}")
                else:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_HIDE)
        self.update_global_overlay_geometry()

    def on_scrcpy_container_ready(self):
        print("Received scrcpy_container_ready signal. Updating overlay geometry.")
        QTimer.singleShot(0, self.update_global_overlay_geometry)

    def update_global_overlay_geometry(self):
        current_page = self.stacked_widget.currentWidget()
        if current_page and hasattr(current_page, 'scrcpy_container_widget') and current_page.scrcpy_container_widget:
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
                if len(keymap.keycombo) == 1 and event.key() == keymap.keycombo[0]:
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
