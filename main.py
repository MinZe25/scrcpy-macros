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

from PyQt5.QtCore import QSizeF, QPointF, pyqtSignal, Qt, QPoint, QRectF, QTimer, QEvent, QRect
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

    def __init__(self, keymaps: list = None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setFocusPolicy(Qt.NoFocus)  # Default: No focus, events pass through
        self.keymaps = keymaps if keymaps is not None else []
        self.edit_mode_active = False
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
        """Sets the keymaps from an external source (e.g., Firestore)."""
        self.keymaps = keymaps_list
        self.update()  # Redraw to show updated keymaps

    def set_edit_mode(self, active: bool):
        """Activates or deactivates the keymap editing mode."""
        self.edit_mode_active = active
        # Make the overlay transparent to mouse events when not in edit mode,
        # so clicks go through to the Scrcpy window.
        # When active, it should capture mouse events.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # Set focus policy to allow key events when in edit mode
        # When not active, we want the main window to handle key presses for keymap activation.
        # So, the overlay's focus policy should allow it to not capture key events.
        self.setFocusPolicy(Qt.StrongFocus if active else Qt.NoFocus)

        if not active:
            # Clear any active editing states when leaving edit mode
            self._dragging_keymap = None
            self._creating_keymap = False
            self._selected_keymap_for_combo_edit = None
            self._pending_modifier_key = None
            self.unsetCursor()  # Reset cursor
            # Emit signal when exiting edit mode to save changes
            self.keymaps_changed.emit(self.keymaps)

        self.update()  # Request repaint to show/hide grid

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        # Draw a semi-transparent taskbar-like area at the top of the overlay
        taskbar_height = 50
        taskbar_rect = QRectF(0, 0, self.width(), taskbar_height)
        taskbar_color = QColor(30, 30, 30, 150)  # Dark grey, 150 alpha
        painter.fillRect(taskbar_rect, taskbar_color)
        painter.setPen(QColor(255, 255, 255))  # White text
        painter.drawText(10, 30, "Overlay Controls Here")

        # Draw semi-transparent background if in edit mode
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

                # Iterate downwards to find the largest font size that fits
                for font_size in range(max_font_size, min_font_size - 1, -1):
                    font.setPointSize(font_size)
                    painter.setFont(font)
                    metrics = QFontMetrics(font)
                    text_bounding_rect = metrics.boundingRect(display_text)

                    # Check if text fits within the keymap_rect with some padding
                    if text_bounding_rect.width() <= keymap_rect.width() * 0.9 and \
                            text_bounding_rect.height() <= keymap_rect.height() * 0.9:
                        break  # Found a font size that fits

                painter.setPen(QColor(255, 255, 255))  # White text for key combo
                # Draw text centered in the keymap's rectangle using alignment flags
                painter.drawText(keymap_rect, Qt.AlignCenter, display_text)

            # Add other keymap types here as needed (e.g., "rectangle", "text")

            # Draw the 'X' button if in edit mode and this keymap is selected
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                x_button_size_pixels = 25  # Fixed size for the X button
                # Position the X button relative to the top-right corner of the keymap_rect
                x_button_rect = QRectF(
                    keymap_rect.right() - x_button_size_pixels / 2,
                    keymap_rect.top() - x_button_size_pixels / 2,
                    x_button_size_pixels,
                    x_button_size_pixels
                )

                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 200))  # Red, slightly opaque
                painter.drawEllipse(x_button_rect)

                font = painter.font()
                font.setPointSize(int(x_button_size_pixels * 0.7))  # Adjust font size
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))  # White 'X'
                painter.drawText(x_button_rect, Qt.AlignCenter, "X")

        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        # If not in edit mode, mouse events should pass through the overlay completely.
        # This is handled by Qt.WA_TransparentForMouseEvents.
        if not self.edit_mode_active:
            # If WA_TransparentForMouseEvents is correctly applied, this event
            # should not even reach here if it's meant to pass through.
            # If it does, then simply returning ensures it's not processed by this widget.
            return

        # --- From here onwards, edit_mode_active is True ---
        if event.button() == Qt.LeftButton:
            self._drag_start_pos_local = event.pos()

            # 1. Check if the click was on the 'X' button of the currently selected keymap
            if self._selected_keymap_for_combo_edit:  # Check if something is already selected
                selected_keymap = self._selected_keymap_for_combo_edit

                # Calculate the pixel position and size of the currently selected keymap
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
                    self.keymaps_changed.emit(self.keymaps)  # Signal that keymaps have changed
                    self.update()  # Redraw to show the keymap removed
                    print("Keymap removed via 'X' button.")
                    event.accept()  # Consume the event
                    return  # Exit early, as we've handled the click

            # 2. Reset selection for a new click
            self._selected_keymap_for_combo_edit = None

            clicked_on_existing_keymap = False
            # Check if an existing keymap was clicked (using current pixel positions)
            for keymap in self.keymaps:
                pixel_x = keymap.normalized_position.x() * self.width()
                pixel_y = keymap.normalized_position.y() * self.height()
                pixel_width = keymap.normalized_size.width() * self.width()
                pixel_height = keymap.normalized_size.height() * self.height()

                keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)

                if keymap_rect.contains(event.pos()):
                    self._dragging_keymap = keymap
                    # Store original pixel position for dragging calculation
                    self._keymap_original_pixel_pos = QPoint(int(pixel_x), int(pixel_y))
                    clicked_on_existing_keymap = True
                    break

            if not clicked_on_existing_keymap:
                # Clicked on empty space, start creating a new keymap.
                # Temporarily store as normalized small size at click point, will be adjusted.
                self._creating_keymap = True
                new_keymap = Keymap(normalized_size=(0.01, 0.01),  # Small normalized size
                                    keycombo=[],
                                    normalized_position=(event.pos().x() / self.width(),
                                                         event.pos().y() / self.height()))
                self.keymaps.append(new_keymap)
                self._dragging_keymap = new_keymap  # We are "dragging" this new one

            self.update()  # Redraw for highlighting or new keymap outline
        # super().mousePressEvent(event) # No need to call super if we've handled the left click in edit mode.

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mouseMoveEvent(event)
            return

        if self._dragging_keymap:
            if self._creating_keymap:
                # Calculate the current pixel rectangle for the new keymap
                dx = event.pos().x() - self._drag_start_pos_local.x()
                dy = event.pos().y() - self._drag_start_pos_local.y()
                side_length = min(abs(dx), abs(dy))

                current_pixel_x = self._drag_start_pos_local.x()
                if dx < 0:
                    current_pixel_x = self._drag_start_pos_local.x() - side_length

                current_pixel_y = self._drag_start_pos_local.y()
                if dy < 0:
                    current_pixel_y = self._drag_start_pos_local.y() - side_length

                # Update the normalized position and size of the temporary keymap
                self._dragging_keymap.normalized_position = QPointF(current_pixel_x / self.width(),
                                                                    current_pixel_y / self.height())
                self._dragging_keymap.normalized_size = QSizeF(side_length / self.width(),
                                                               side_length / self.height())

                # Ensure minimum normalized size (e.g., 10 pixels minimum)
                min_norm_size_w = 10 / self.width()
                min_norm_size_h = 10 / self.height()
                if self._dragging_keymap.normalized_size.width() < min_norm_size_w:
                    self._dragging_keymap.normalized_size.setWidth(min_norm_size_w)
                if self._dragging_keymap.normalized_size.height() < min_norm_size_h:
                    self._dragging_keymap.normalized_size.setHeight(min_norm_size_h)

            else:  # Moving existing keymap
                delta = event.pos() - self._drag_start_pos_local
                new_pixel_x = self._keymap_original_pixel_pos.x() + delta.x()
                new_pixel_y = self._keymap_original_pixel_pos.y() + delta.y()

                self._dragging_keymap.normalized_position = QPointF(new_pixel_x / self.width(),
                                                                    new_pixel_y / self.height())
            self.update()  # Redraw to show movement/resizing
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mouseReleaseEvent(event)
            return

        if event.button() == Qt.LeftButton:
            release_pos = event.pos()

            # Calculate distance moved to differentiate click from drag
            try:
                distance_moved = QPointF(release_pos - self._drag_start_pos_local).norm()
            except AttributeError:
                # Fallback for older PyQt5 versions if .norm() isn't present
                dx = release_pos.x() - self._drag_start_pos_local.x()
                dy = release_pos.y() - self._drag_start_pos_local.y()
                distance_moved = math.sqrt(dx * dx + dy * dy)

            if self._dragging_keymap:
                if self._creating_keymap:
                    # If it was a small click (not a significant drag) during creation, finalize as default size
                    if distance_moved < 5:  # Threshold for a "click" vs "drag"
                        # Remove the temporary keymap, as it was just a click
                        self.keymaps.remove(self._dragging_keymap)

                        # Define a default pixel diameter for the new circle
                        default_pixel_diameter = 100

                        # Calculate the normalized width and height for a perfect circle
                        # These values ensure that when scaled back by self.width() and self.height()
                        # in paintEvent, the pixel width and height are equal (default_pixel_diameter).
                        new_norm_width = default_pixel_diameter / self.width()
                        new_norm_height = default_pixel_diameter / self.height()

                        # Calculate the normalized top-left position to center the circle at release_pos
                        new_norm_x = (release_pos.x() - default_pixel_diameter // 2) / self.width()
                        new_norm_y = (release_pos.y() - default_pixel_diameter // 2) / self.height()

                        new_keymap = Keymap(normalized_size=(new_norm_width, new_norm_height),
                                            keycombo=[],
                                            normalized_position=(new_norm_x, new_norm_y))
                        self.keymaps.append(new_keymap)
                        self._selected_keymap_for_combo_edit = new_keymap
                    else:
                        # For drag-to-size, finalize the current size and position to a perfect circle
                        # The normalized position and size are already updated in mouseMoveEvent
                        # We just need to select it.
                        self._selected_keymap_for_combo_edit = self._dragging_keymap
                else:
                    # Existing keymap was dragged, check if it was truly a drag or a click
                    if distance_moved < 5:
                        self._selected_keymap_for_combo_edit = self._dragging_keymap

                self._dragging_keymap = None  # Stop dragging
                self._creating_keymap = False
                self.update()  # Redraw after finalizing changes
                self.keymaps_changed.emit(self.keymaps)  # Emit signal after modification
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        # This method is only for when the OverlayWidget has focus.
        # In this setup, MyQtApp captures all key presses and forwards them
        # to the OverlayWidget *only if* in edit mode.
        if not self.edit_mode_active:
            # If not in edit mode, the key event should be handled by MyQtApp directly.
            # This 'if' block should theoretically not be reached if MyQtApp is intercepting.
            # But as a fallback, and for clarity:
            super().keyPressEvent(event)
            return

        # Handle deletion of selected keymap
        if event.key() == Qt.Key_Delete and self._selected_keymap_for_combo_edit:
            self.keymaps.remove(self._selected_keymap_for_combo_edit)
            self._selected_keymap_for_combo_edit = None
            self.update()
            self.keymaps_changed.emit(self.keymaps)  # Emit signal after modification
            print("Keymap deleted.")
            event.accept()
            return

        if self._selected_keymap_for_combo_edit:
            key = event.key()
            modifiers = event.modifiers()

            new_combo = []

            # Determine if a modifier key is pressed (Shift, Ctrl, Alt)
            is_modifier_key = (key == Qt.Key_Shift or key == Qt.Key_Control or key == Qt.Key_Alt or
                               key == Qt.Key_Meta or key == Qt.Key_Super_L or key == Qt.Key_Super_R)  # Add Super/Meta keys

            # If a modifier key is pressed and it's the first key, store it.
            # If a modifier key is pressed and there's already a pending modifier, update it.
            if is_modifier_key:
                self._pending_modifier_key = key
                print(f"Pending modifier: {self._get_key_text(key)}")
            # If a non-modifier key is pressed
            else:
                if self._pending_modifier_key:
                    new_combo.append(self._pending_modifier_key)
                    self._pending_modifier_key = None  # Clear pending modifier after adding it

                # Add the current non-modifier key
                new_combo.append(key)

                self._selected_keymap_for_combo_edit.keycombo = new_combo
                self._selected_keymap_for_combo_edit = None  # Deselect after setting combo
                print(f"Keymap combo set to: {[self._get_key_text(k) for k in new_combo]}")
                self.update()  # Redraw to show updated key combo
                self.keymaps_changed.emit(self.keymaps)  # Emit signal after modification
            event.accept()  # Consume the event if it was for keymap combo setting
        else:
            super().keyPressEvent(event)  # Pass event if no keymap is selected for editing


# --- Sidebar Widget Class ---
class SidebarWidget(QFrame):
    settings_requested = pyqtSignal()
    edit_requested = pyqtSignal()  # New signal for the edit button
    instance_selected = pyqtSignal(int)

    def __init__(self, num_instances: int = 5, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(60)

        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(5, 10, 5, 5)
        self.sidebar_layout.setSpacing(10)

        for i in range(num_instances):
            btn = QPushButton(f"💬")
            btn.setObjectName("SidebarButton")
            btn.clicked.connect(lambda _, index=i: self._on_instance_button_clicked(index))
            self.sidebar_layout.addWidget(btn)

        # Spacer to push new buttons to the bottom
        self.sidebar_layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # New Edit Button
        self.edit_button = QPushButton("✏️")  # Pencil emoji for edit
        self.edit_button.setObjectName("SidebarButton")  # Use existing style
        self.edit_button.clicked.connect(self.edit_requested.emit)
        self.sidebar_layout.addWidget(self.edit_button)

        # New Settings Button
        self.settings_button = QPushButton("⚙️")  # Gear emoji for settings
        self.settings_button.setObjectName("SidebarButton")  # Use existing style
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.sidebar_layout.addWidget(self.settings_button)

    def _on_instance_button_clicked(self, index: int):
        print(f"Sidebar: Instance button {index + 1} clicked, emitting index {index}.")
        self.instance_selected.emit(index)


# --- Main Content Area Widget Class ---
class MainContentAreaWidget(QWidget):
    # New signal to notify parent when Scrcpy container is ready
    scrcpy_container_ready = pyqtSignal()

    def __init__(self, instance_id: int, device_serial: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("MainContentWidget")
        self.instance_id = instance_id
        self.device_serial = device_serial
        self.scrcpy_process = None
        self.scrcpy_hwnd = None
        self.scrcpy_qwindow = None
        self.scrcpy_container_widget = None  # This is the QWidget created by createWindowContainer
        self.scrcpy_stdout_reader = None  # For non-blocking stdout reading
        self.scrcpy_stderr_reader = None  # For non-blocking stderr reading
        self.scrcpy_output_timer = QTimer(self)  # Timer to poll Scrcpy output
        self.scrcpy_display_id = None  # To store the detected display ID

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

        # Connect the timer to the output reading slot
        self.scrcpy_output_timer.timeout.connect(self._read_scrcpy_output)

        self.start_scrcpy()
        self.installEventFilter(self)  # Install event filter on THIS WIDGET to catch its own resizes

    def _read_scrcpy_output(self):
        """
        Reads output from Scrcpy process stdout and stderr,
        and attempts to find the display ID.
        """
        if not self.scrcpy_process:
            self.scrcpy_output_timer.stop()
            return

        # Read stdout
        stdout_line = self.scrcpy_stdout_reader.readline()
        if stdout_line:
            line_str = stdout_line.strip()
            # print(f"Scrcpy STDOUT ({self.instance_id + 1}): {line_str}") # Commented for less verbose output

            # Regex to find display ID: "[server] INFO: New display: 1920x1080/333 (id=343)"
            match = re.search(r'\(id=(\d+)\)', line_str)
            if match:
                self.scrcpy_display_id = int(match.group(1))
                print(f"Detected Scrcpy Display ID: {self.scrcpy_display_id} for instance {self.instance_id + 1}")
                self.scrcpy_output_timer.stop()  # Stop polling once ID is found

        # Read stderr (for general error logging)
        stderr_line = self.scrcpy_stderr_reader.readline()
        if stderr_line:
            print(f"Scrcpy STDERR ({self.instance_id + 1}): {stderr_line.strip()}")

    def start_scrcpy(self):
        if self.scrcpy_process and self.scrcpy_process.poll() is None:
            print(f"Scrcpy for instance {self.instance_id + 1} is already running (PID: {self.scrcpy_process.pid}).")
            return

        print(f"Starting Scrcpy for Instance {self.instance_id + 1}...")
        try:
            scrcpy_cmd = [
                'scrcpy',
                '--video-codec=h265',
                '--max-fps=60',
                '--tcpip=192.168.1.38',
                '-S',
                '--new-display=1920x1080',  # This sets the internal rendering resolution
                '--start-app=com.ankama.dofustouch',  # Re-added this line as requested
                f'--window-title={self.scrcpy_expected_title}',
                '--turn-screen-off'  # Turn off device screen to save battery
            ]

            self.scrcpy_process = subprocess.Popen(
                scrcpy_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                universal_newlines=True  # Important for reading text output
            )
            print(f"Scrcpy process for instance {self.instance_id + 1} started with PID: {self.scrcpy_process.pid}")

            # Initialize non-blocking readers
            self.scrcpy_stdout_reader = NonBlockingStreamReader(self.scrcpy_process.stdout)
            self.scrcpy_stderr_reader = NonBlockingStreamReader(self.scrcpy_process.stderr)

            # Start timer to poll for output, specifically for the display ID
            self.scrcpy_output_timer.start(100)  # Check every 100 ms

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
            window_title = win32gui.GetWindowText(hwnd)
            if window_title == self.scrcpy_expected_title:
                self.scrcpy_hwnd = hwnd
                print(f"--- Found Scrcpy window HWND: {self.scrcpy_hwnd} for instance {self.instance_id + 1} ---")
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

            print(f"Scrcpy window {self.scrcpy_hwnd} embedded using QWidget.createWindowContainer.")

            win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_SHOW)

            # Explicitly call resize after embedding to ensure initial correct sizing
            self.resize_scrcpy_native_window()
            # Overlay is now handled globally by MyQtApp, so no call here.
            self.scrcpy_container_ready.emit()  # Emit signal once container is ready

        else:
            print(
                f"Scrcpy window '{self.scrcpy_expected_title}' for instance {self.instance_id + 1} not found, retrying in 1 second...")
            QTimer.singleShot(1000, self.find_and_embed_scrcpy)

    def eventFilter(self, source, event):
        # We need to react when THIS WIDGET (MainContentAreaWidget) resizes
        # because its layout manages the scrcpy_container_widget's size.
        if source == self and event.type() == QEvent.Resize:
            self.resize_scrcpy_native_window()
            # Overlay is now handled globally by MyQtApp, so no call here.
            print("resizing native (MainContentAreaWidget)")
            return True
        return super().eventFilter(source, event)

    def resize_scrcpy_native_window(self):
        if not self.scrcpy_hwnd or not self.scrcpy_container_widget:
            return

        container_rect = self.scrcpy_container_widget.rect()
        width = container_rect.width()
        height = container_rect.height()

        try:
            win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, width, height, True)
            print(
                f"Scrcpy window {self.scrcpy_hwnd} (Instance {self.instance_id + 1}) forced resize to: {width}x{height}")
        except Exception as e:
            print(f"Error resizing scrcpy_hwnd: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        if self.scrcpy_hwnd:
            win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_SHOW)
            self.resize_scrcpy_native_window()
        # MyQtApp will handle showing/hiding/positioning the global overlay

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.scrcpy_hwnd:
            win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_HIDE)
        # MyQtApp will handle showing/hiding/positioning the global overlay

    def stop_scrcpy(self):
        if self.scrcpy_process and self.scrcpy_process.poll() is None:
            print(f"Terminating Scrcpy process for instance {self.instance_id + 1} (PID: {self.scrcpy_process.pid})...")

            # Stop the output polling timer
            self.scrcpy_output_timer.stop()

            if self.scrcpy_hwnd:
                win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_HIDE)
                win32gui.SetParent(self.scrcpy_hwnd, 0)  # Unparent before terminating

            self.scrcpy_process.terminate()
            try:
                self.scrcpy_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.scrcpy_process.kill()
                print(f"Force-killed Scrcpy process for instance {self.instance_id + 1}.")
            self.scrcpy_process = None
            self.scrcpy_hwnd = None
            self.scrcpy_qwindow = None
            self.scrcpy_container_widget = None
            self.scrcpy_display_id = None  # Clear display ID on stop
            self.scrcpy_stdout_reader = None
            self.scrcpy_stderr_reader = None
            print(f"Scrcpy process for instance {self.instance_id + 1} terminated.")
        elif self.scrcpy_process:
            print(f"Scrcpy process for instance {self.instance_id + 1} already stopped.")
            self.scrcpy_process = None
            self.scrcpy_hwnd = None
            self.scrcpy_qwindow = None
            self.scrcpy_container_widget = None
            self.scrcpy_display_id = None  # Clear display ID on stop
            self.scrcpy_stdout_reader = None
            self.scrcpy_stderr_reader = None


# --- Main Application Window (MODIFIED to manage a global OverlayWidget) ---
class MyQtApp(QMainWindow):
    _gripSize = 8

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bonito Integrated Controller")
        self.setGeometry(100, 100, 1200, 800)

        self.setStyleSheet(self.load_stylesheet_from_file("./style.css"))

        self.setMouseTracking(True)  # Still useful for potential future custom interactions
        self.edit_mode_active = False  # New state for edit mode

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.content_layout = QHBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.main_layout.addLayout(self.content_layout, 1)

        self.num_instances = 1
        device_serials = [None] * self.num_instances

        self.sidebar = SidebarWidget(num_instances=self.num_instances, parent=self)
        # Connect new signals from sidebar
        self.sidebar.edit_requested.connect(self.toggle_edit_mode)
        self.sidebar.settings_requested.connect(self.show_settings_dialog)  # Connect to new method
        self.content_layout.addWidget(self.sidebar)

        self.stacked_widget = QStackedWidget(self)
        self.content_layout.addWidget(self.stacked_widget, 1)

        self.main_content_pages = []
        for i in range(self.num_instances):
            serial = device_serials[i] if i < len(device_serials) else None
            page = MainContentAreaWidget(instance_id=i, device_serial=serial, parent=self)
            # Connect the new signal here
            page.scrcpy_container_ready.connect(self.on_scrcpy_container_ready)
            self.stacked_widget.addWidget(page)
            self.main_content_pages.append(page)

        self.sidebar.instance_selected.connect(self.stacked_widget.setCurrentIndex)
        self.stacked_widget.currentChanged.connect(self._on_stacked_widget_page_changed)

        if self.num_instances > 0:
            self.stacked_widget.setCurrentIndex(0)
            print("MyQtApp: Initial MainContentAreaWidget set to index 0.")

        self.update_max_restore_button()

        # Initialize global overlay and connect signal
        self.global_overlay = OverlayWidget(parent=self)
        self.global_overlay.keymaps_changed.connect(self.save_keymaps_to_local_json)
        self.global_overlay.hide()

        # Load keymaps from local JSON after overlay is set up
        self.load_keymaps_from_local_json()

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

    def _get_key_text_for_app(self, qt_key_code: int) -> str:
        """Helper to convert Qt.Key code to its string representation for display/logging."""
        if qt_key_code == Qt.Key_Shift:
            return "Shift"
        elif qt_key_code == Qt.Key_Control:
            return "Control"
        elif qt_key_code == Qt.Key_Alt:
            return "Alt"
        return QKeySequence(qt_key_code).toString()

    def send_adb_keyevent(self, keycode: str):
        """
        Sends an ADB key event to the Android device via ADB shell input.
        """
        current_page = self.stacked_widget.currentWidget()
        if current_page and current_page.scrcpy_display_id is not None:
            device_ip = "192.168.1.38"  # Hardcoded IP

            adb_cmd = [
                'adb',
                '-s', device_ip,
                'shell',
                'input',
                'keyevent', keycode
            ]

            try:
                subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                print(f"Sent ADB keyevent '{keycode}' to {device_ip}")
            except FileNotFoundError:
                print("Error: adb not found. Make sure 'adb.exe' is in your system PATH.")
            except Exception as e:
                print(f"Error sending ADB keyevent: {e}")
        else:
            print(f"Cannot send ADB keyevent '{keycode}': No active Scrcpy page or display ID not detected.")

    def send_scrcpy_tap(self, x: int, y: int):
        """
        Sends a simulated tap event to the Android device via ADB shell input.
        The x and y coordinates are expected to be in the native Scrcpy resolution (1920x1080).
        """
        current_page = self.stacked_widget.currentWidget()
        if current_page and current_page.scrcpy_display_id is not None:
            display_id = current_page.scrcpy_display_id
            # The device IP is hardcoded in the scrcpy_cmd for simplicity,
            # but in a real app, it might be dynamically configured.
            device_ip = "192.168.1.38"

            adb_cmd = [
                'adb',
                '-s', device_ip,
                'shell',
                'input',
                '-d', str(display_id),
                'tap', str(x), str(y)
            ]

            try:
                # Use Popen to avoid blocking, and discard output
                subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                print(f"Sent ADB tap to {device_ip} (display {display_id}) at coordinates ({x}, {y})")
            except FileNotFoundError:
                print("Error: adb not found. Make sure 'adb.exe' is in your system PATH.")
            except Exception as e:
                print(f"Error sending ADB tap: {e}")
        else:
            print("Cannot send ADB tap: No active Scrcpy page or display ID not detected.")

    def save_keymaps_to_local_json(self, keymaps_list: list):
        """Saves the current list of keymaps to a local JSON file."""
        serializable_keymaps = [km.to_dict() for km in keymaps_list]
        try:
            with open(KEYMAP_FILE, 'w') as f:
                json.dump(serializable_keymaps, f, indent=4)
            print(f"Keymaps saved to {KEYMAP_FILE} successfully.")
        except Exception as e:
            print(f"Error saving keymaps to local JSON: {e}")

    def load_keymaps_from_local_json(self):
        """Loads keymaps from a local JSON file."""
        loaded_keymaps = []
        if os.path.exists(KEYMAP_FILE):
            try:
                with open(KEYMAP_FILE, 'r') as f:
                    data = json.load(f)
                    loaded_keymaps = [Keymap.from_dict(km_data) for km_data in data]
                print(f"Keymaps loaded from {KEYMAP_FILE}.")
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON from {KEYMAP_FILE}: {e}. Starting with empty keymaps.")
            except Exception as e:
                print(f"Error loading keymaps from {KEYMAP_FILE}: {e}. Starting with empty keymaps.")
        else:
            print(f"{KEYMAP_FILE} not found, starting with empty keymaps.")
            # If no file exists, initialize with default keymaps
            # These values are based on an assumed 1920x1080 internal resolution for Scrcpy
            # and represent 50px offset and 100px size from that reference.
            # Converted to normalized for a 1920x1080 Scrcpy area:
            initial_keymap_circle = Keymap(normalized_size=(100 / SCRCPY_NATIVE_WIDTH, 100 / SCRCPY_NATIVE_HEIGHT),
                                           keycombo=[Qt.Key_Shift, Qt.Key_A],
                                           normalized_position=(50 / SCRCPY_NATIVE_WIDTH, 50 / SCRCPY_NATIVE_HEIGHT),
                                           type="circle")
            secondary_keymap_circle = Keymap(normalized_size=(100 / SCRCPY_NATIVE_WIDTH, 100 / SCRCPY_NATIVE_HEIGHT),
                                             keycombo=[Qt.Key_A],
                                             normalized_position=(400 / SCRCPY_NATIVE_WIDTH,
                                                                  300 / SCRCPY_NATIVE_HEIGHT),
                                             type="circle")
            loaded_keymaps = [initial_keymap_circle, secondary_keymap_circle]
            self.save_keymaps_to_local_json(loaded_keymaps)  # Save defaults to new file

        self.global_overlay.set_keymaps(loaded_keymaps)

    def toggle_edit_mode(self):
        """Toggles the keymap editing mode."""
        self.edit_mode_active = not self.edit_mode_active
        self.global_overlay.set_edit_mode(self.edit_mode_active)
        self.update_global_overlay_geometry()  # Recalculate to show/hide overlay as needed

        # Update button text/style - These lines related to CustomTitleBar are now correctly commented out
        # if self.edit_mode_active:
        # self.title_bar.edit_button.setText("Exit Edit")
        # self.title_bar.edit_button.setStyleSheet(
        #     "background-color: #BD93F9; color: #282a36;")  # Highlight when active
        # else:
        # self.title_bar.edit_button.setText("Edit")
        # self.title_bar.edit_button.setStyleSheet("")  # Reset to default style

        print(f"Edit mode active: {self.edit_mode_active}")

    def show_settings_dialog(self):
        """Displays the settings dialog, importing it from settings_dialog.py."""
        print("Opening settings dialog...")
        try:
            # Dynamically import the SettingsDialog from the external file
            from settings_dialog import SettingsDialog
            dialog = SettingsDialog(self)
            dialog.exec_()  # Show the dialog modally
            print("Settings dialog closed.")
        except ImportError:
            print("Error: Could not import SettingsDialog. Ensure 'settings_dialog.py' exists in the same directory.")
        except Exception as e:
            print(f"Error showing settings dialog: {e}")

    @property
    def gripSize(self):
        return self._gripSize

    def setGripSize(self, size):
        if size == self._gripSize:
            return
        self._gripSize = max(2, size)
        self.updateGrips()

    def updateGrips(self):
        # This method and related grip logic are commented out in the original, so keeping it that way.
        pass
        # self.setContentsMargins(*[self.gripSize] * 4)

        # outRect = self.rect()
        # inRect = outRect.adjusted(self.gripSize, self.gripSize,
        #                           -self.gripSize, -self.gripSize)

        # self.cornerGrips[0].setGeometry(
        #     QRect(outRect.topLeft(), inRect.topLeft()))
        # self.cornerGrips[1].setGeometry(
        #     QRect(outRect.topRight(), inRect.topRight()).normalized())
        # self.cornerGrips[2].setGeometry(
        #     QRect(inRect.bottomRight(), outRect.bottomRight()))
        # self.cornerGrips[3].setGeometry(
        #     QRect(outRect.bottomLeft(), inRect.bottomLeft()).normalized())

        # self.sideGrips[0].setGeometry(
        #     0, inRect.top(), self.gripSize, inRect.height())
        # self.sideGrips[1].setGeometry(
        #     inRect.left(), 0, inRect.width(), self.gripSize)
        # self.sideGrips[2].setGeometry(
        #     inRect.left() + inRect.width(),
        #     inRect.top(), self.gripSize, inRect.height())
        # self.sideGrips[3].setGeometry(
        #     self.gripSize, inRect.top() + inRect.height(),
        #     inRect.width(), self.gripSize)

    def resizeEvent(self, event):
        QMainWindow.resizeEvent(self, event)
        # updateGrips and update_max_restore_button related calls are now correctly commented out as per original
        # self.updateGrips()
        self.update_max_restore_button()
        # Defer updating the overlay's geometry to ensure layouts have settled
        QTimer.singleShot(0, self.update_global_overlay_geometry)

    # Removed custom _get_resize_mode, mousePressEvent, mouseMoveEvent, mouseReleaseEvent, leaveEvent, changeEvent overrides

    def mouseDoubleClickEvent(self, event):
        # Title bar double click logic remains commented out
        # if event.button() == Qt.LeftButton and self.title_bar.geometry().contains(event.pos()):
        #     self.toggle_maximize_restore()
        #     event.accept()
        # else:
        super().mouseDoubleClickEvent(event)

    def toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.update_max_restore_button()
        # Update overlay geometry after maximize/restore
        self.update_global_overlay_geometry()

    # New: Override moveEvent to update overlay position
    def moveEvent(self, event):
        super().moveEvent(event)
        self.update_global_overlay_geometry()  # Ensure overlay moves with the main window

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        background_color = QColor(40, 42, 54)
        painter.setBrush(background_color)
        painter.setPen(Qt.NoPen)
        border_radius = 10
        painter.drawRoundedRect(self.rect(), border_radius, border_radius)

    def update_max_restore_button(self):
        # This method remains commented out as per original
        pass
        # if self.isMaximized():
        #     self.title_bar.max_button.setText("❐")
        # else:
        #     self.title_bar.max_button.setText("⬜")

    def showEvent(self, event):
        super().showEvent(event)
        # update_max_restore_button and updateGrips related calls are now correctly commented out as per original
        self.update_max_restore_button()
        # self.updateGrips()
        # Ensure global overlay is positioned and shown correctly on app startup
        # We still call this here to handle cases where the app is launched and Scrcpy
        # is already running or found very quickly.
        self.update_global_overlay_geometry()

    def _on_stacked_widget_page_changed(self, index: int):
        print(f"Stacked widget page changed to index: {index}")
        # When changing pages, ensure correct visibility and geometry for Scrcpy and its overlay
        for i, page in enumerate(self.main_content_pages):
            if page.scrcpy_hwnd:
                if i == index:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_SHOW)
                    page.resize_scrcpy_native_window()
                else:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_HIDE)
        # Always update the global overlay after a page change
        self.update_global_overlay_geometry()

    def on_scrcpy_container_ready(self):
        """
        Slot to be called when a Scrcpy container widget is fully ready.
        Ensures the overlay is positioned correctly after the Scrcpy window is embedded.
        """
        print("Received scrcpy_container_ready signal. Updating overlay geometry.")
        # Defer the update to ensure layout has settled
        QTimer.singleShot(0, self.update_global_overlay_geometry)

    def update_global_overlay_geometry(self):
        """
        Calculates the global geometry of the current Scrcpy display area
        and sets the global_overlay's geometry to match it, maintaining aspect ratio.
        The overlay is always shown if a Scrcpy page is active.
        """
        current_page = self.stacked_widget.currentWidget()

        if current_page and \
                hasattr(current_page, 'scrcpy_container_widget') and \
                current_page.scrcpy_container_widget:
            # Get the global position of the Scrcpy container widget
            global_pos = current_page.scrcpy_container_widget.mapToGlobal(QPoint(0, 0))
            # Get the size of the Scrcpy container widget (this is the available space)
            available_width = current_page.scrcpy_container_widget.width()
            available_height = current_page.scrcpy_container_widget.height()

            # Calculate the dimensions that maintain the aspect ratio and fit within the available space
            # Option 1: Maximize width, calculate height
            target_width_by_width = available_width
            target_height_by_width = int(available_width / SCRCPY_ASPECT_RATIO)

            # Option 2: Maximize height, calculate width
            target_height_by_height = available_height
            target_width_by_height = int(available_height * SCRCPY_ASPECT_RATIO)

            # Choose the option that fits without exceeding bounds
            if target_height_by_width <= available_height:
                # Option 1 fits vertically, so use it
                active_display_width = target_width_by_width
                active_display_height = target_height_by_width
            else:
                # Option 1 exceeds vertically, so use Option 2
                active_display_width = target_width_by_height
                active_display_height = target_height_by_height

            # Calculate centered position within the container widget's global rectangle
            offset_x = (available_width - active_display_width) // 2
            offset_y = (available_height - active_display_height) // 2

            overlay_x = global_pos.x() + offset_x
            overlay_y = global_pos.y() + offset_y

            self.global_overlay.setGeometry(
                overlay_x, overlay_y, active_display_width, active_display_height
            )
            self.global_overlay.raise_()  # Ensure it's on top of all other windows
            self.global_overlay.show()

            print(
                f"Overlay Geometry Set: x={overlay_x}, y={overlay_y}, w={active_display_width}, h={active_display_height}")
            print(f"Scrcpy Container (Available): w={available_width}, h={available_height}")
            print(f"Calculated Active Display: w={active_display_width}, h={active_display_height}")

        else:
            # If no Scrcpy page is active, hide the overlay
            self.global_overlay.hide()
            print("Global overlay hidden (no active Scrcpy page).")

    def keyPressEvent(self, event: QKeyEvent):
        """
        Handles key press events for the main application window.
        Routes key presses to keymap activation or editing based on the current mode.
        """
        if not self.edit_mode_active:
            # Check for ESC key press to send 'back' command
            if event.key() == Qt.Key_Escape:
                self.send_adb_keyevent("KEYCODE_BACK")
                event.accept()
                return

            # In play mode, check if the pressed key matches any keymap's assigned key.
            # We only support single-key triggers for now.
            for keymap in self.global_overlay.keymaps:
                # Assuming keymap.keycombo only has one element for simplicity based on previous implementation
                if len(keymap.keycombo) == 1 and event.key() == keymap.keycombo[0]:
                    # Calculate position and size in Scrcpy's native resolution (1920x1080)
                    pixel_x_native = keymap.normalized_position.x() * SCRCPY_NATIVE_WIDTH
                    pixel_y_native = keymap.normalized_position.y() * SCRCPY_NATIVE_HEIGHT
                    pixel_width_native = keymap.normalized_size.width() * SCRCPY_NATIVE_WIDTH
                    pixel_height_native = keymap.normalized_size.height() * SCRCPY_NATIVE_HEIGHT

                    # Calculate center coordinates in native resolution
                    center_x_native = int(pixel_x_native + pixel_width_native / 2)
                    center_y_native = int(pixel_y_native + pixel_height_native / 2)

                    # Send ADB tap with native coordinates
                    self.send_scrcpy_tap(center_x_native, center_y_native)
                    event.accept()  # Consume the event
                    print(
                        f"Key '{self._get_key_text_for_app(event.key())}' pressed, activating keymap at native ({center_x_native}, {center_y_native})")
                    return

            # If no keymap was activated, let the event propagate normally (e.g., to Scrcpy if possible).
            super().keyPressEvent(event)
        else:
            # In edit mode, forward the key press event to the global overlay
            # so it can handle setting key combos or deleting keymaps.
            self.global_overlay.keyPressEvent(event)
            event.accept()  # Assume the overlay handles it if in edit mode
            return

    def closeEvent(self, event):
        print("Closing application, stopping all Scrcpy processes...")
        # Hide the global overlay explicitly before closing
        self.global_overlay.hide()
        # It's good practice to close/delete the overlay if it's a top-level window
        # when the main application closes to ensure all resources are released.
        self.global_overlay.deleteLater()

        for page in self.main_content_pages:
            page.stop_scrcpy()
        super().closeEvent(event)


if __name__ == '__main__':
    def exception_hook(exctype, value, traceback_obj):
        sys.__excepthook__(exctype, value, traceback_obj)
        print(f"\n--- Unhandled Exception Detected ---")
        print(f"Type: {exctype.__name__}")
        print(f"Value: {value}")
        print("Traceback:")
        import traceback
        traceback.print_tb(traceback_obj)
        print("----------------------------------")


    sys.excepthook = exception_hook

    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 10))
    window = MyQtApp()
    window.show()
    sys.exit(app.exec_())
