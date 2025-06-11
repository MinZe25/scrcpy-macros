import sys
import subprocess
import time
import re
import pygetwindow as gw
import win32gui  # For precise window client area detection
import win32con  # For win32 constants and mouse event forwarding

from PyQt5.QtWidgets import QApplication, QWidget, QPushButton
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush
from PyQt5.QtCore import Qt, QPoint, QTimer, QRectF

# --- Configuration ---
SCRCPY_WINDOW_TITLE = "scrcpy"  # The title of your scrcpy window. Adjust if different (e.g., just "scrcpy")
OVERLAY_UPDATE_INTERVAL_MS = 20  # How often the overlay updates its position/size (in ms)
KEYBOARD_CHECK_INTERVAL_SEC = 1  # How often the keyboard active state is checked (in seconds)

# --- Global state for overlay drawing ---
# This dictionary will store primitives to draw on the overlay.
# Each entry will store center coordinates.
# For rectangles, 'dimensions' will be (width, height).
# For circles/crosshairs, 'dimensions' will be radius/line_length.
DRAWING_PRIMITIVES = {}
NEXT_PRIMITIVE_ID = 0


# --- Helper functions for ADB communication ---
def is_keyboard_active():
    """
    Checks if the on-screen (soft) keyboard is currently active on the Android device
    by executing a command on the device shell and parsing its output.
    """
    try:
        # Command to run on the Android device shell, filtering output with grep.
        command = f'adb shell "dumpsys input_method | grep mInputShown"'

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )

        output = result.stdout.strip()

        if "mInputShown=true" in output:
            return True
        else:
            return False

    except subprocess.CalledProcessError as e:
        print(f"Error running ADB command: {e}")
        print(f"Stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print(
            "Error: 'adb' command not found. Make sure Android SDK Platform-Tools (containing adb.exe) is installed and its directory is added to your system's PATH environmental variable.")
        return False


# --- Overlay Window Class ---
class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scrcpy Overlay")

        # Set window flags for transparent, always-on-top, and frameless.
        # IMPORTANT: Qt.WindowTransparentForInput HAS BEEN REMOVED to make the button clickable.
        # We'll implement manual click forwarding to scrcpy when not in edit mode.
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |  # Keep window on top of others
            Qt.FramelessWindowHint |  # No window frame (border, title bar)
            Qt.Tool |  # Hide from taskbar and alt-tab
            Qt.X11BypassWindowManagerHint  # Helps with focus issues on some platforms
        )

        # Set background to transparent (per-pixel transparency)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Ensure the widget can receive focus and key events
        self.setFocusPolicy(Qt.StrongFocus)

        # Store device resolution - HARDCODED as requested
        # These dimensions should match the intended virtual display resolution or your device's
        self.device_width = 1920
        self.device_height = 1080
        print(f"Device resolution hardcoded to: {self.device_width}x{self.device_height}")

        # Store scrcpy window details (using pygetwindow's wrapper for window handle)
        self.scrcpy_window_gw = None
        self.scrcpy_hwnd = None  # Store scrcpy's raw Win32 window handle for consistent checks
        self.find_scrcpy_window()  # Initial search

        # Timer to periodically update overlay position/size and keyboard status
        self.overlay_timer = QTimer(self)
        self.overlay_timer.timeout.connect(self.update_overlay_position)
        self.overlay_timer.start(OVERLAY_UPDATE_INTERVAL_MS)

        self.keyboard_check_timer = QTimer(self)
        self.keyboard_check_timer.timeout.connect(self.check_keyboard_status)
        self.keyboard_check_timer.start(KEYBOARD_CHECK_INTERVAL_SEC * 1000)

        self.keyboard_active_status = False
        # self.overlay_has_focus = False # Removed: Relying on isActiveWindow() directly

        # --- Edit Mode Variables ---
        self.edit_mode_active = False  # Tracks if edit mode is currently active
        self.new_primitive_type = 'circle'  # Circle is the only primitive type now
        self.new_primitive_color = (50, 200, 50)  # Default color (softer green)
        self.new_primitive_opacity = 0.7  # Default opacity
        self.primitive_being_created = None  # Stores data for primitive being created
        self.start_point = None  # Start point for drag operations
        self.selected_primitive_id = None  # ID of selected primitive
        self.primitive_being_moved = False  # Flag to track if a primitive is being moved
        self.delete_button_size = 20  # Size of the delete X button
        self.assigning_key_combo = False  # Flag to track if we're waiting for key combo

        # --- Edit Mode Button ---
        self.edit_button = QPushButton("Edit Mode", self)
        # Apply subtle styling to the button
        self.edit_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 70, 70, 150); /* Semi-transparent dark grey */
                color: white;
                border: 1px solid rgba(100, 100, 100, 150);
                border-radius: 5px;
                padding: 3px 6px;
            }
            QPushButton:hover {
                background-color: rgba(90, 90, 90, 200); /* Slightly more opaque on hover */
            }
            QPushButton:pressed {
                background-color: rgba(50, 50, 50, 200);
            }
        """)
        self.edit_button.setFixedSize(80, 25)  # Fixed size for consistency
        self.edit_button.clicked.connect(self.toggle_edit_mode)
        # --- Edit Mode Control Panel ---
        self.edit_panel = QWidget(self)
        self.edit_panel.setFixedSize(160, 240)
        self.edit_panel.setStyleSheet("background-color: rgba(40, 40, 40, 180); border-radius: 8px;")
        self.edit_panel.hide()  # Hidden by default, shown only in edit mode

        # We'll position the panel in update_overlay_position method
        # --- End Edit Mode Control Panel ---

        # Add primitives based on the hardcoded device resolution

        # Initial primitives are only circles now

        # Red circle at the bottom-right corner of the device resolution
        # Its center is placed such that its right/bottom edge is at the device_width/height
        circle_radius = 50
        # coords now represents the center of the circle
        self.add_primitive('circle', (255, 0, 0), 0.5,
                           (self.device_width - circle_radius,
                            self.device_height - circle_radius),
                           circle_radius)

        # Add another red circle for testing at specific coordinates
        circle_radius_small = 25
        self.add_primitive('circle', (255, 0, 0), 0.5,
                           (self.device_width - 280,
                            self.device_height - 900),
                           circle_radius_small)  # This will be the center of the circle

    # Removed focusInEvent and focusOutEvent as overlay_has_focus is no longer used directly

    def find_scrcpy_window(self):
        """
        Attempts to find the scrcpy window by its title.
        Updates the overlay's geometry to match the scrcpy window's *client area* if found.
        """
        try:
            # Get all windows whose title contains SCRCPY_WINDOW_TITLE
            scrcpy_windows = gw.getWindowsWithTitle(SCRCPY_WINDOW_TITLE)

            found_scrcpy_window = None
            if scrcpy_windows:
                for win in scrcpy_windows:
                    # Check if the title starts with the expected string and is not empty
                    if win.title and win.title.startswith(SCRCPY_WINDOW_TITLE):
                        found_scrcpy_window = win
                        break  # Found a suitable scrcpy window, stop searching

            if found_scrcpy_window:
                self.scrcpy_window_gw = found_scrcpy_window
                self.scrcpy_hwnd = self.scrcpy_window_gw._hWnd  # Store the HWND

                # Get the client rectangle (drawable area) coordinates relative to the window (0,0)
                l, t, r, b = win32gui.GetClientRect(self.scrcpy_hwnd)
                client_width = r - l
                client_height = b - t

                # Convert client coordinates to screen coordinates
                # This gives us the absolute position and size of the drawable area on the screen
                client_top_left_screen = win32gui.ClientToScreen(self.scrcpy_hwnd, (l, t))
                client_bottom_right_screen = win32gui.ClientToScreen(self.scrcpy_hwnd, (r, b))

                screen_x = client_top_left_screen[0]
                screen_y = client_top_left_screen[1]
                screen_width = client_bottom_right_screen[0] - screen_x
                screen_height = client_bottom_right_screen[1] - screen_y

                # Set the geometry of the overlay window to precisely match scrcpy's client area
                self.setGeometry(screen_x, screen_y, screen_width, screen_height)

                # Initially show if scrcpy is found AND either scrcpy is foreground or this overlay is active
                current_foreground = win32gui.GetForegroundWindow()
                if current_foreground == self.scrcpy_hwnd or self.isActiveWindow():
                    self.show()
                    self.raise_()
                else:
                    self.hide()  # Hide if scrcpy is found but not active
            else:
                self.scrcpy_window_gw = None
                self.scrcpy_hwnd = None  # Clear HWND if window not found
                self.hide()  # Hide overlay if scrcpy window is not found
        except Exception as e:
            print(f"Error finding scrcpy window: {e}")
            self.scrcpy_window_gw = None
            self.scrcpy_hwnd = None
            self.hide()

    def update_overlay_position(self):
        """
        Called by timer to continuously update overlay position/size
        and ensure it stays aligned with the scrcpy window's *client area*,
        and only shows when scrcpy or the overlay itself is the foreground window.
        """
        if self.scrcpy_window_gw and self.scrcpy_hwnd:  # Ensure we have a valid HWND for scrcpy
            current_foreground = win32gui.GetForegroundWindow()

            # Check if the scrcpy window is still valid, visible, and not minimized
            is_scrcpy_valid_and_visible = (
                    win32gui.IsWindow(self.scrcpy_hwnd) and
                    win32gui.IsWindowVisible(self.scrcpy_hwnd) and
                    not win32gui.IsIconic(self.scrcpy_hwnd)
            )

            # The overlay should be visible if:
            # 1. The scrcpy window is valid and visible AND
            # 2. Either scrcpy is the foreground OR the overlay itself is the active PyQt window.
            # Always show when in edit mode regardless of focus
            should_be_visible = is_scrcpy_valid_and_visible and (
                    current_foreground == self.scrcpy_hwnd or
                    self.isActiveWindow() or  # Use PyQt's internal active window status
                    self.edit_mode_active  # Always visible in edit mode
            )

            # --- Debugging Prints (Uncomment to see detailed foreground status) ---
            # print(f"--- Update Cycle ---")
            # print(f"Scrcpy HWND: {self.scrcpy_hwnd}, Overlay HWND: {self.winId()}, Foreground HWND: {current_foreground}")
            # print(f"Is Scrcpy Valid/Visible: {is_scrcpy_valid_and_visible}")
            # print(f"Overlay isActiveWindow(): {self.isActiveWindow()}")
            # print(f"Is Scrcpy Foreground: {current_foreground == self.scrcpy_hwnd}")
            # print(f"Should Overlay be Visible: {should_be_visible}")
            # print(f"Overlay current visibility: {self.isVisible()}")
            # -------------------------------------------------------------------

            if should_be_visible:
                if not self.isVisible():
                    # print("Overlay is not visible but should be. Showing now.")
                    self.show()
                    self.raise_()  # Bring to front

                # Get current client rect in screen coordinates
                l, t, r, b = win32gui.GetClientRect(self.scrcpy_hwnd)
                client_width = r - l
                client_height = b - t
                client_top_left_screen = win32gui.ClientToScreen(self.scrcpy_hwnd, (l, t))
                client_bottom_right_screen = win32gui.ClientToScreen(self.scrcpy_hwnd, (r, b))

                screen_x = client_top_left_screen[0]
                screen_y = client_top_left_screen[1]
                screen_width = client_bottom_right_screen[0] - screen_x
                screen_height = client_bottom_right_screen[1] - screen_y

                # Check if position or size has changed, then update and repaint
                if (self.x() != screen_x or
                        self.y() != screen_y or
                        self.width() != screen_width or
                        self.height() != screen_height):
                    self.setGeometry(screen_x, screen_y, screen_width, screen_height)
                    self.update()  # Request a repaint if geometry changed

                # --- Reposition the Edit Mode button ---
                # Place it relative to the overlay's current window size
                button_margin = 10
                self.edit_button.move(self.width() - self.edit_button.width() - button_margin, button_margin)
                self.edit_button.setVisible(True)  # Ensure button is visible when overlay is
                # --- End Reposition ---

                # --- Reposition and show/hide the Edit Panel ---
                panel_margin = 10
                self.edit_panel.move(self.width() - self.edit_panel.width() - panel_margin,
                                    self.edit_button.y() + self.edit_button.height() + 10)
                self.edit_panel.setVisible(self.edit_mode_active)  # Only visible in edit mode

            else:
                # If scrcpy is not valid OR neither scrcpy nor overlay is foreground, hide the overlay and its button
                if self.isVisible():
                    # print("Overlay is visible but should be hidden. Hiding now.")
                    self.hide()
                    self.edit_button.setVisible(False)  # Hide button too
                # If window is no longer valid, clear reference to force re-finding
                if not is_scrcpy_valid_and_visible:
                    # print("Scrcpy window is no longer valid/visible. Clearing reference.")
                    self.scrcpy_window_gw = None
                    self.scrcpy_hwnd = None
        else:
            self.find_scrcpy_window()  # Try to find scrcpy window if not found previously

    def check_keyboard_status(self):
        """
        Called by timer to check and update the keyboard active status.
        """
        current_status = is_keyboard_active()
        if current_status != self.keyboard_active_status:
            self.keyboard_active_status = current_status
            print(f"Keyboard Active Status: {self.keyboard_active_status}")
            self.update()  # Request a repaint to reflect status change

    def add_primitive(self, p_type, color, opacity, center_coords, dimensions):
        """
        Adds a primitive to be drawn on the overlay.
        Args:
            p_type (str): 'circle', 'rectangle', or 'crosshair'.
            color (tuple): RGB tuple (0-255, 0-255, 0-255).
            opacity (float): 0.0 (fully transparent) to 1.0 (fully opaque).
            center_coords (tuple): (x, y) representing the geometric center of the primitive.
                                   These coordinates are relative to the *device's native resolution*.
            dimensions (int or tuple): For 'circle': radius. For 'rectangle': (width, height).
                                       For 'crosshair': half-length of lines.
        """
        global NEXT_PRIMITIVE_ID
        primitive_id = f"primitive_{NEXT_PRIMITIVE_ID}"
        NEXT_PRIMITIVE_ID += 1

        DRAWING_PRIMITIVES[primitive_id] = {
            'type': p_type,
            'color': color,
            'opacity': opacity,
            'center_coords': center_coords,
            'dimensions': dimensions,
            'key_combo': ""  # Initialize with no key combo
        }
        self.update()  # Request a repaint

    def remove_primitive(self, primitive_id):
        """Removes a primitive from being drawn."""
        if primitive_id in DRAWING_PRIMITIVES:
            del DRAWING_PRIMITIVES[primitive_id]
            self.update()  # Request a repaint

    def find_primitive_at_coords(self, device_x, device_y):
        """Finds a primitive at the given device coordinates and returns its ID."""
        for p_id, p_data in DRAWING_PRIMITIVES.items():
            p_type = p_data['type']
            center_x, center_y = p_data['center_coords']
            dimensions = p_data['dimensions']

            if p_type == 'circle':
                radius = dimensions
                # Calculate distance from center
                distance = ((device_x - center_x) ** 2 + (device_y - center_y) ** 2) ** 0.5
                if distance <= radius:
                    return p_id
            elif p_type == 'crosshair':
                # Crosshairs have a small hitbox
                line_length = dimensions
                if (abs(device_x - center_x) <= 10 and abs(device_y - center_y) <= line_length) or \
                   (abs(device_y - center_y) <= 10 and abs(device_x - center_x) <= line_length):
                    return p_id
        return None

    def is_delete_button_hit(self, device_x, device_y):
        """Checks if the delete button of the selected primitive was hit."""
        if not self.selected_primitive_id or self.selected_primitive_id not in DRAWING_PRIMITIVES:
            return False

        p_data = DRAWING_PRIMITIVES[self.selected_primitive_id]
        center_x, center_y = p_data['center_coords']
        dimensions = p_data['dimensions']

        if p_data['type'] == 'circle':
            radius = dimensions
            # Position of delete button is at top-right of circle
            button_x = center_x + radius * 0.7  # Slightly inside the radius for better visibility
            button_y = center_y - radius * 0.7

            # Check if click is within delete button area
            distance = ((device_x - button_x) ** 2 + (device_y - button_y) ** 2) ** 0.5
            return distance <= self.delete_button_size / 2

        return False

    def is_key_combo_button_hit(self, device_x, device_y):
        """This method is kept for backwards compatibility but no longer used"""
        # Key combo assignment now happens automatically when a primitive is selected
        # without requiring a separate button click
        return False

    def paintEvent(self, event):
        """
        This method is called when the widget needs to be repainted.
        We draw all our primitives here, calculating scale and offset based on
        scrcpy's content area within its window.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # Smooth edges

        # Add a semi-transparent background in edit mode
        if self.edit_mode_active:
            # Fill the entire overlay with a semi-transparent background
            bg_color = QColor(50, 50, 50, 40)  # Very light gray with 40/255 opacity
            painter.fillRect(self.rect(), bg_color)

        current_overlay_width = self.width()  # Now this IS the client width of scrcpy
        current_overlay_height = self.height()  # Now this IS the client height of scrcpy

        # Calculate the actual scaling factor scrcpy is using.
        # This will be the scale factor applied to the hardcoded device resolution
        # to fit it into the client area of the scrcpy window.
        scale_factor_x = current_overlay_width / self.device_width
        scale_factor_y = current_overlay_height / self.device_height

        actual_scrcpy_content_scale = min(scale_factor_x, scale_factor_y)

        # Calculate the size of the actual Android content displayed by scrcpy
        # These are the dimensions of the area *within the scrcpy client window*
        # that actually shows the Android screen.
        scaled_content_width = self.device_width * actual_scrcpy_content_scale
        scaled_content_height = self.device_height * actual_scrcpy_content_scale

        # Calculate offsets to center the Android content within the scrcpy client window.
        # These offsets represent the black borders *scrcpy itself draws*.
        offset_x_in_scrcpy_content = (current_overlay_width - scaled_content_width) / 2
        offset_y_in_scrcpy_content = (current_overlay_height - scaled_content_height) / 2

        # Translate and scale the painter to draw relative to the *scrcpy content area*
        # Primitives defined in (device_width, device_height) coordinates will now
        # appear correctly scaled and positioned over the actual scrcpy screen.
        painter.translate(int(offset_x_in_scrcpy_content), int(offset_y_in_scrcpy_content))
        painter.scale(actual_scrcpy_content_scale, actual_scrcpy_content_scale)

        # Draw all primitives
        for p_id, p_data in DRAWING_PRIMITIVES.items():
            p_type = p_data['type']
            color_rgb = p_data['color']
            opacity = p_data['opacity']
            center_x, center_y = p_data['center_coords']
            dimensions = p_data['dimensions']

            # Set color with opacity
            color = QColor(color_rgb[0], color_rgb[1], color_rgb[2])
            color.setAlphaF(opacity)  # Set alpha (opacity)
            painter.setBrush(color)  # For filling shapes
            painter.setPen(Qt.NoPen)  # No outline for now, or set a transparent pen

            if p_type == 'circle':
                radius = dimensions
                # drawEllipse takes center coordinates directly
                painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(radius), int(radius))

                # Draw key combo text if assigned (always visible, even outside edit mode)
                key_combo = p_data.get('key_combo')
                if key_combo:
                    # Save current painter state
                    painter.save()

                    # Calculate size based on circle radius - make text as large as possible
                    # Use radius as a scaling factor for the font size
                    # Cap at reasonable sizes for very large or small circles
                    font_size = min(max(int(radius * 0.6), 12), 48)  # Scale with radius but with min/max

                    # Set up font for key combo
                    font = painter.font()
                    font.setPointSize(font_size)
                    font.setBold(True)
                    painter.setFont(font)

                    # Draw the text directly in the center of the circle
                    # First create a background that fills most of the circle
                    bg_size = radius * 1.4  # Make background large, filling most of the circle
                    bg_rect = QRectF(
                        center_x - bg_size/2,
                        center_y - bg_size/2,
                        bg_size,
                        bg_size
                    )

                    # Semi-transparent black background
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(0, 0, 0, 180))
                    painter.drawEllipse(bg_rect)  # Circular background

                    # Add a white border for contrast
                    painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(bg_rect)

                    # Draw text with bright color
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 3))  # Solid white, thick

                    # Use a slightly smaller rect for the text to ensure it fits
                    text_rect = QRectF(
                        center_x - bg_size/2 + 10,  # Inset from the background edge
                        center_y - bg_size/2 + 10,
                        bg_size - 20,
                        bg_size - 20
                    )
                    painter.drawText(text_rect, Qt.AlignCenter, key_combo)

                    # Restore painter state
                    painter.restore()

                # Draw selection indicator and buttons for selected primitive in edit mode
                if self.edit_mode_active and p_id == self.selected_primitive_id:
                    # Draw a dashed selection outline
                    select_pen = QPen(Qt.white, 2, Qt.DashLine)
                    painter.setPen(select_pen)
                    painter.setBrush(Qt.NoBrush)
                    # Draw slightly larger than the actual circle to show selection
                    painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(radius) + 5, int(radius) + 5)

                    # Draw delete button (red X) at top-right of circle
                    delete_x = center_x + radius * 0.7  # Position slightly inside the radius
                    delete_y = center_y - radius * 0.7

                    # Draw red circle for delete button
                    delete_button_radius = self.delete_button_size / 2
                    delete_color = QColor(255, 50, 50, 230)  # Bright semi-transparent red
                    painter.setBrush(delete_color)
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(QPoint(int(delete_x), int(delete_y)), 
                                      int(delete_button_radius), int(delete_button_radius))

                    # Draw X inside button
                    painter.setPen(QPen(Qt.white, 2))
                    x_size = delete_button_radius * 0.7
                    painter.drawLine(int(delete_x - x_size), int(delete_y - x_size), 
                                    int(delete_x + x_size), int(delete_y + x_size))
                    painter.drawLine(int(delete_x + x_size), int(delete_y - x_size), 
                                    int(delete_x - x_size), int(delete_y + x_size))

                    # Visual indicator for key combo assignment mode
                    if self.assigning_key_combo and self.selected_primitive_id == p_id:
                        # Draw an orange glow around the selected circle to indicate key combo assignment mode
                        glow_pen = QPen(QColor(255, 165, 0, 180), 3, Qt.DashLine)
                        painter.setPen(glow_pen)
                        painter.setBrush(Qt.NoBrush)
                        # Draw slightly larger than the selection circle
                        painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(radius) + 8, int(radius) + 8)
            elif p_type == 'crosshair':
                line_length = dimensions
                pen = QPen(color, 2)  # Use a pen for lines (line thickness 2)
                painter.setPen(pen)
                painter.drawLine(int(center_x - line_length), int(center_y), int(center_x + line_length), int(center_y))
                painter.drawLine(int(center_x), int(center_y - line_length), int(center_x), int(center_y + line_length))

        # Draw text feedback (this text will also be scaled and translated
        # because the painter is still scaled).
        if self.keyboard_active_status:
            text_color = QColor(255, 255, 255)  # White text
            text_color.setAlphaF(0.8)  # 80% opaque
            painter.setPen(QPen(text_color))
            painter.setBrush(Qt.NoBrush)
            painter.drawText(10, 30, "Keyboard is ACTIVE")
        else:
            text_color = QColor(255, 255, 255)  # White text
            text_color.setAlphaF(0.4)  # 40% opaque
            painter.setPen(QPen(text_color))
            painter.setBrush(Qt.NoBrush)
            painter.drawText(10, 30, "Keyboard is INACTIVE")

        # Draw edit mode UI elements and previews
        if self.edit_mode_active:
            # Draw a semi-transparent background for edit mode indicator
            bg_rect = QRectF(5, 35, 400, 85)
            bg_color = QColor(40, 40, 40)
            bg_color.setAlphaF(0.7)  # 70% opaque
            painter.setBrush(bg_color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 5, 5)

            # Draw edit mode status text with stronger contrast for better visibility
            edit_text_color = QColor(255, 100, 100)  # Red text
            edit_text_color.setAlphaF(1.0)  # Fully opaque for better visibility
            # Add text shadow for better readability against any background
            shadow_color = QColor(0, 0, 0, 180)
            shadow_offset = 1

            # Draw shadow text first
            painter.setPen(QPen(shadow_color))
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.drawText(15 + shadow_offset, 60 + shadow_offset, f"EDIT MODE - {self.new_primitive_type.upper()}")
            painter.drawText(15 + shadow_offset, 90 + shadow_offset, "Press: C=Circle, ESC=Exit")
            painter.drawText(15 + shadow_offset, 120 + shadow_offset, "Click and drag to create circles")
            painter.drawText(15 + shadow_offset, 150 + shadow_offset, "Click on circle to select, then:")
            painter.drawText(15 + shadow_offset, 180 + shadow_offset, "- Drag to move, click X to delete")
            painter.drawText(15 + shadow_offset, 210 + shadow_offset, "- Type keys to assign a shortcut (click elsewhere to cancel)")

            # Then draw the colored text on top
            painter.setPen(QPen(edit_text_color))
            painter.drawText(15, 60, f"EDIT MODE - CIRCLE")
            painter.drawText(15, 90, "Press: C=Circle, ESC=Exit")
            painter.drawText(15, 120, "Click and drag to create circles")
            painter.drawText(15, 150, "Click on circle to select, then:")
            painter.drawText(15, 180, "- Drag to move, click X to delete")
            painter.drawText(15, 210, "- Type keys to assign a shortcut (click elsewhere to cancel)")

            # Draw an example of the current primitive type
            preview_color = QColor(*self.new_primitive_color)
            preview_color.setAlphaF(self.new_primitive_opacity)
            painter.setBrush(preview_color)
            painter.setPen(Qt.NoPen)

            # Only circle preview as it's the only primitive type available
            painter.drawEllipse(350, 60, 30, 30)  # Small circle preview

            # Draw guide grid (lighter in edit mode to help with positioning)
            grid_color = QColor(200, 200, 200)
            grid_color.setAlphaF(0.2)  # Subtle grid
            grid_pen = QPen(grid_color, 1, Qt.DashLine)
            painter.setPen(grid_pen)

            # Draw horizontal grid lines every 100 device pixels
            for y in range(0, self.device_height + 1, 100):
                painter.drawLine(0, y, self.device_width, y)

            # Draw vertical grid lines every 100 device pixels
            for x in range(0, self.device_width + 1, 100):
                painter.drawLine(x, 0, x, self.device_height)

            # Draw preview of primitive being created
            if self.primitive_being_created:
                p_data = self.primitive_being_created
                color_rgb = p_data['color']
                opacity = p_data['opacity']
                center_x, center_y = p_data['center_coords']
                dimensions = p_data['dimensions']

                # Set color with opacity
                color = QColor(color_rgb[0], color_rgb[1], color_rgb[2])
                color.setAlphaF(opacity)  # Set alpha (opacity)

                # Draw with dashed outline to indicate it's a preview
                painter.setBrush(color)  # For filling shapes
                outline_pen = QPen(Qt.white, 2, Qt.DashLine)
                outline_pen.setColor(QColor(255, 255, 255, 150))  # Semi-transparent white
                painter.setPen(outline_pen)

                if p_data['type'] == 'circle':
                    radius = dimensions
                    painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(radius), int(radius))
                elif p_data['type'] == 'rectangle':
                    width, height = dimensions
                    top_left_x = center_x - width / 2
                    top_left_y = center_y - height / 2
                    painter.drawRect(int(top_left_x), int(top_left_y), int(width), int(height))

    # --- Edit Mode Methods ---
    def mousePressEvent(self, event):
        """
        Handles mouse press events for the overlay.
        In edit mode: Starts creating a new primitive.
        Otherwise: Passes the event through to the scrcpy window.
        """
        # First check if clicking on the edit button - always let Qt handle button clicks
        for child in self.findChildren(QPushButton):
            if child.isVisible() and child.geometry().contains(event.pos()):
                print(f"Clicked on button: {child.text()}")
                super().mousePressEvent(event)
                return

        # Check for clicking on primitives when not in edit mode to trigger key combos
        if not self.edit_mode_active and event.button() == Qt.LeftButton:
            # Calculate device coordinates (same as elsewhere in the code)
            pos = event.pos()
            current_overlay_width = self.width()
            current_overlay_height = self.height()
            scale_factor_x = current_overlay_width / self.device_width
            scale_factor_y = current_overlay_height / self.device_height
            actual_scale = min(scale_factor_x, scale_factor_y)
            scaled_content_width = self.device_width * actual_scale
            scaled_content_height = self.device_height * actual_scale
            offset_x = (current_overlay_width - scaled_content_width) / 2
            offset_y = (current_overlay_height - scaled_content_height) / 2

            # Convert overlay position to device coordinates
            device_x = (pos.x() - offset_x) / actual_scale
            device_y = (pos.y() - offset_y) / actual_scale

            # Check if we clicked on a primitive
            clicked_primitive_id = self.find_primitive_at_coords(device_x, device_y)
            if clicked_primitive_id and clicked_primitive_id in DRAWING_PRIMITIVES:
                # Get the key combo for this primitive
                key_combo = DRAWING_PRIMITIVES[clicked_primitive_id].get('key_combo')
                if key_combo:
                    print(f"Primitive clicked with key combo: {key_combo}")

                    # Simulate the key combination by sending key events to the active window
                    # For this example, we'll use win32 SendMessage to send keystrokes to scrcpy
                    if self.scrcpy_hwnd:
                        # Activate the scrcpy window first
                        win32gui.SetForegroundWindow(self.scrcpy_hwnd)

                        # Parse the key combo
                        has_ctrl = 'Ctrl+' in key_combo
                        has_alt = 'Alt+' in key_combo
                        has_shift = 'Shift+' in key_combo

                        # Extract the key part (after the last +)
                        key_part = key_combo.split('+')[-1]

                        # Press modifiers first if any
                        if has_ctrl:
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_CONTROL, 0)
                        if has_alt:
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_MENU, 0)
                        if has_shift:
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_SHIFT, 0)

                        # Try to send the main key
                        # This is a simplified approach - a full implementation would map all keys
                        if len(key_part) == 1 and key_part.isalpha():
                            vk_code = ord(key_part.upper())
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, vk_code, 0)
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, vk_code, 0)
                        elif key_part == 'Esc':
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
                        elif key_part == 'Tab':
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_TAB, 0)
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_TAB, 0)
                        elif key_part == 'Enter':
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
                        elif key_part == 'Delete':
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYDOWN, win32con.VK_DELETE, 0)
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_DELETE, 0)

                        # Release modifiers in reverse order
                        if has_shift:
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_SHIFT, 0)
                        if has_alt:
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_MENU, 0)
                        if has_ctrl:
                            win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_KEYUP, win32con.VK_CONTROL, 0)

                        # Return focus to overlay after sending keys
                        self.activateWindow()
                        self.raise_()

                    event.accept()
                    return

        if self.edit_mode_active and event.button() == Qt.LeftButton:
            # Ensure we have focus before proceeding with primitive creation
            if not self.hasFocus():
                self.activateWindow()
                self.setFocus()
                print("Activating window and setting focus in edit mode")

            # In edit mode - handle the click 
            print("Edit mode click detected")
            # Get click position and convert to device coordinates
            pos = event.pos()

            # Calculate actual content area within the overlay
            current_overlay_width = self.width()
            current_overlay_height = self.height()

            scale_factor_x = current_overlay_width / self.device_width
            scale_factor_y = current_overlay_height / self.device_height
            actual_scale = min(scale_factor_x, scale_factor_y)

            scaled_content_width = self.device_width * actual_scale
            scaled_content_height = self.device_height * actual_scale

            offset_x = (current_overlay_width - scaled_content_width) / 2
            offset_y = (current_overlay_height - scaled_content_height) / 2

            # Convert overlay position to device coordinates
            device_x = (pos.x() - offset_x) / actual_scale
            device_y = (pos.y() - offset_y) / actual_scale

            # Validate coordinates are within device bounds
            if 0 <= device_x <= self.device_width and 0 <= device_y <= self.device_height:
                # Store starting point for potential drag operations
                self.start_point = (device_x, device_y)

                # First check if we clicked on the delete button of the selected primitive
                if self.selected_primitive_id and self.is_delete_button_hit(device_x, device_y):
                    # Delete the selected primitive
                    print(f"Deleting primitive {self.selected_primitive_id}")
                    self.remove_primitive(self.selected_primitive_id)
                    self.selected_primitive_id = None
                    self.update()
                    return

                # Key combo button has been removed
                # Assignment mode is now automatically enabled when a primitive is selected

                # Then check if we clicked on an existing primitive
                clicked_primitive_id = self.find_primitive_at_coords(device_x, device_y)
                if clicked_primitive_id:
                    print(f"Selected existing primitive: {clicked_primitive_id}")
                    self.selected_primitive_id = clicked_primitive_id
                    self.primitive_being_moved = True
                    # Enable key combo assignment when a primitive is selected
                    self.assigning_key_combo = True
                    print(f"Waiting for key combo for primitive {self.selected_primitive_id}")
                    # Update to show selection
                    self.update()
                    return
                else:
                    # If we didn't click on an existing primitive, deselect any selected primitive
                    if self.selected_primitive_id:
                        self.selected_primitive_id = None
                        self.update()

                # If no primitive was clicked, start creating a new one
                # Initialize primitive being created (always circle now)
                self.primitive_being_created = {
                    'type': 'circle',
                    'color': self.new_primitive_color,
                    'opacity': self.new_primitive_opacity,
                    'center_coords': (device_x, device_y),
                    'dimensions': 10  # Start with a small radius/size
                }

                print(f"Started creating {self.new_primitive_type} at ({device_x:.1f}, {device_y:.1f})")
                # Update to show the new primitive as it's being created
                self.update()
            else:
                print(f"Click outside device bounds: ({device_x:.1f}, {device_y:.1f})")
        elif not self.edit_mode_active:
            # Not in edit mode - pass the click through to scrcpy window
            if self.scrcpy_hwnd:
                # Forward click to scrcpy window
                x, y = event.pos().x(), event.pos().y()
                print(f"Forwarding click to scrcpy at ({x}, {y})")
                # Create a simulated mouse click at the same position in scrcpy window
                # Convert to screen coordinates first
                screen_pos = self.mapToGlobal(event.pos())
                win32gui.SetForegroundWindow(self.scrcpy_hwnd)
                win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_LBUTTONDOWN, 0,
                                    (screen_pos.y() << 16) | screen_pos.x())
                win32gui.SendMessage(self.scrcpy_hwnd, win32con.WM_LBUTTONUP, 0,
                                    (screen_pos.y() << 16) | screen_pos.x())
                # Bring overlay back to foreground after forwarding click
                self.activateWindow()
                self.raise_()
                # In edit mode - handle the click to create a primitive
                print("Edit mode click detected")
                # Get click position and convert to device coordinates
                pos = event.pos()

                # Calculate actual content area within the overlay
                current_overlay_width = self.width()
                current_overlay_height = self.height()

                scale_factor_x = current_overlay_width / self.device_width
                scale_factor_y = current_overlay_height / self.device_height
                actual_scale = min(scale_factor_x, scale_factor_y)

                scaled_content_width = self.device_width * actual_scale
                scaled_content_height = self.device_height * actual_scale

                offset_x = (current_overlay_width - scaled_content_width) / 2
                offset_y = (current_overlay_height - scaled_content_height) / 2

                # Convert overlay position to device coordinates
                device_x = (pos.x() - offset_x) / actual_scale
                device_y = (pos.y() - offset_y) / actual_scale

                # Validate coordinates are within device bounds
                if 0 <= device_x <= self.device_width and 0 <= device_y <= self.device_height:
                    # Store starting point for potential drag operations
                    self.start_point = (device_x, device_y)

                    # Initialize primitive being created
                    self.primitive_being_created = {
                        'type': self.new_primitive_type,
                        'color': self.new_primitive_color,
                        'opacity': self.new_primitive_opacity,
                        'center_coords': (device_x, device_y),
                        'dimensions': 10  # Start with a small radius/size
                    }

                    print(f"Started creating {self.new_primitive_type} at ({device_x:.1f}, {device_y:.1f})")
                    # Update to show the new primitive as it's being created
                    self.update()
                else:
                    print(f"Click outside device bounds: ({device_x:.1f}, {device_y:.1f})")

    def mouseMoveEvent(self, event):
        """
        Handles mouse move events for primitive resizing or moving in edit mode.
        """
        if not self.edit_mode_active or not self.start_point:
            return

        # Get current position in device coordinates
        pos = event.pos()

        # Calculate actual content area within the overlay (same as in mousePressEvent)
        current_overlay_width = self.width()
        current_overlay_height = self.height()

        scale_factor_x = current_overlay_width / self.device_width
        scale_factor_y = current_overlay_height / self.device_height
        actual_scale = min(scale_factor_x, scale_factor_y)

        scaled_content_width = self.device_width * actual_scale
        scaled_content_height = self.device_height * actual_scale

        offset_x = (current_overlay_width - scaled_content_width) / 2
        offset_y = (current_overlay_height - scaled_content_height) / 2

        # Convert overlay position to device coordinates
        device_x = (pos.x() - offset_x) / actual_scale
        device_y = (pos.y() - offset_y) / actual_scale

        # Get distance moved from start point
        start_x, start_y = self.start_point
        dx = device_x - start_x
        dy = device_y - start_y

        # Handle moving an existing primitive
        if self.primitive_being_moved and self.selected_primitive_id:
            if self.selected_primitive_id in DRAWING_PRIMITIVES:
                # Update the primitive's position
                primitive = DRAWING_PRIMITIVES[self.selected_primitive_id]
                old_center_x, old_center_y = primitive['center_coords']

                # Move the primitive by the drag amount
                new_center_x = old_center_x + dx
                new_center_y = old_center_y + dy

                # Ensure the primitive stays within bounds
                if primitive['type'] == 'circle':
                    radius = primitive['dimensions']
                    new_center_x = max(radius, min(self.device_width - radius, new_center_x))
                    new_center_y = max(radius, min(self.device_height - radius, new_center_y))

                # Update the primitive's position
                primitive['center_coords'] = (new_center_x, new_center_y)

                # Update the start point for the next move event
                self.start_point = (device_x, device_y)

                self.update()  # Redraw
                return

        # Handle creating a new primitive
        if self.primitive_being_created:
            # For circle: calculate radius based on distance from start point
            radius = int(((dx ** 2) + (dy ** 2)) ** 0.5)  # Euclidean distance

            # Update the primitive being created
            self.primitive_being_created['dimensions'] = radius
            self.update()  # Redraw

            # Update to show the resized primitive
            self.update()

    def mouseReleaseEvent(self, event):
        """
        Handles mouse release events to finalize primitive creation or movement in edit mode.
        """
        if not self.edit_mode_active or event.button() != 1:  # Left mouse button
            return

        # Handle moving an existing primitive
        if self.primitive_being_moved and self.selected_primitive_id:
            print(f"Finished moving primitive {self.selected_primitive_id}")
            self.primitive_being_moved = False
            # Keep the primitive selected
            self.update()
            return

        # Handle finishing primitive creation
        if self.primitive_being_created:
            # Add the completed primitive to the list of primitives
            new_primitive_id = f"primitive_{NEXT_PRIMITIVE_ID}"
            self.add_primitive(
                self.primitive_being_created['type'],
                self.primitive_being_created['color'],
                self.primitive_being_created['opacity'],
                self.primitive_being_created['center_coords'],
                self.primitive_being_created['dimensions']
            )

            print(f"Added new {self.primitive_being_created['type']} primitive at "
                  f"{self.primitive_being_created['center_coords']} with "
                  f"dimensions {self.primitive_being_created['dimensions']}")

            # Clear the in-progress primitive
            self.primitive_being_created = None

            # Select the newly created primitive
            self.selected_primitive_id = new_primitive_id

        # Clear the start point for all cases
        self.start_point = None

        # Turn off key combo assignment mode if we released the mouse on empty space
        # (This allows clicking away from a primitive to cancel key combo assignment)
        if self.assigning_key_combo and not self.primitive_being_created and not self.primitive_being_moved:
            pos = event.pos()
            # Calculate device coordinates as in mousePressEvent
            current_overlay_width = self.width()
            current_overlay_height = self.height()
            scale_factor_x = current_overlay_width / self.device_width
            scale_factor_y = current_overlay_height / self.device_height
            actual_scale = min(scale_factor_x, scale_factor_y)
            scaled_content_width = self.device_width * actual_scale
            scaled_content_height = self.device_height * actual_scale
            offset_x = (current_overlay_width - scaled_content_width) / 2
            offset_y = (current_overlay_height - scaled_content_height) / 2
            device_x = (pos.x() - offset_x) / actual_scale
            device_y = (pos.y() - offset_y) / actual_scale

            # Check if we clicked on a primitive
            clicked_primitive_id = self.find_primitive_at_coords(device_x, device_y)
            if not clicked_primitive_id:
                # Clicked on empty space, cancel key combo assignment
                self.assigning_key_combo = False
                print("Cancelled key combo assignment (clicked on empty space)")
                self.update()

        # Make sure we keep focus
        self.activateWindow()
        self.setFocus()

        # Update to show the final state
        self.update()

    def focusInEvent(self, event):
        """
        Called when the window receives focus.
        """
        print("Overlay window gained focus")
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        """
        Called when the window loses focus.
        """
        print("Overlay window lost focus")
        super().focusOutEvent(event)
        if self.edit_mode_active:
            # If in edit mode, quickly regain focus to prevent losing it
            self.activateWindow()
            self.setFocus()
            print("Regaining focus since we're in edit mode")

    def keyPressEvent(self, event):
        """
        Handles key press events in edit mode.
        """
        key = event.key()
        print(f"Key pressed: {key} (0x{key:x})")

        # Key handling for edit mode
        if self.edit_mode_active:
            if key == 16777216:  # Qt.Key_Escape = 16777216
                # Exit edit mode when Escape is pressed
                print("ESC pressed - exiting edit mode")
                self.toggle_edit_mode()
                event.accept()
                return

            elif key == 67:  # C key = 67
                # Circle is the only primitive type
                self.new_primitive_type = 'circle'
                print("Primitive type set to circle")
                self.update()  # Update to refresh any UI indicators
                event.accept()
                return

            elif key == 16777223 and self.primitive_being_created:  # Qt.Key_Delete = 16777223
                # Cancel current primitive creation
                self.primitive_being_created = None
                self.start_point = None
                print("Canceled primitive creation")
                self.update()
                event.accept()
                return

            # Handle key combo assignment for selected primitive
            elif self.assigning_key_combo and self.selected_primitive_id and self.selected_primitive_id in DRAWING_PRIMITIVES:
                # Create a readable key combo string
                modifiers = event.modifiers()
                key_text = event.text()

                # Build the key combination string
                key_combo = ""
                if modifiers & Qt.ControlModifier:
                    key_combo += "Ctrl+"
                if modifiers & Qt.AltModifier:
                    key_combo += "Alt+"
                if modifiers & Qt.ShiftModifier:
                    key_combo += "Shift+"

                # For special keys, use more readable names
                key_name = ""
                if key in (16777216, 16777217, 16777219, 16777220, 16777223):  # Esc, Tab, Backspace, Enter, Delete
                    if key == 16777216:
                        key_name = "Esc"
                    elif key == 16777217:
                        key_name = "Tab"
                    elif key == 16777219:
                        key_name = "Backspace"
                    elif key == 16777220:
                        key_name = "Enter"
                    elif key == 16777223:
                        key_name = "Delete"
                # For regular printable characters, use the text
                elif key_text and key_text.isprintable():
                    key_name = key_text.upper()
                # For other keys, use the key code
                else:
                    key_name = f"K{key}"

                key_combo += key_name

                # Assign the key combo to the primitive
                if key_combo:
                    DRAWING_PRIMITIVES[self.selected_primitive_id]['key_combo'] = key_combo
                    print(f"Assigned key combo '{key_combo}' to primitive {self.selected_primitive_id}")
                    self.assigning_key_combo = False  # Turn off assignment mode after successful assignment
                    self.update()  # Redraw to show the key combo
                    event.accept()
                    return

        # Call the parent class implementation for other keys
        super().keyPressEvent(event)

    def toggle_edit_mode(self):
        """
        Toggles edit mode on/off and updates the button appearance.
        """
        self.edit_mode_active = not self.edit_mode_active
        print(f"Edit mode {'activated' if self.edit_mode_active else 'deactivated'}")

        # If entering edit mode, set window flags to ensure it stays focused
        if self.edit_mode_active:
            # Set window flags to ensure it stays on top and can receive focus
            self.setWindowFlags(
                Qt.WindowStaysOnTopHint |
                Qt.FramelessWindowHint |
                Qt.Tool
            )
            # Enable background opacity which makes clicks more reliable
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            # Show and activate to apply new flags
            self.show()
            self.activateWindow()
            self.raise_()

        # Make sure we have focus to receive key events
        self.setFocus()
        print(f"Window has focus: {self.hasFocus()}")

        if self.edit_mode_active:
            print("Edit Mode activated - click to add primitives")
            self.edit_button.setText("Exit Edit")
            self.edit_panel.show()  # Show edit panel when edit mode is active
            self.edit_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(200, 70, 70, 200); /* Semi-transparent red */
                    color: white;
                    border: 1px solid rgba(240, 100, 100, 200);
                    border-radius: 5px;
                    padding: 3px 6px;
                }
                QPushButton:hover {
                    background-color: rgba(220, 90, 90, 230);
                }
                QPushButton:pressed {
                    background-color: rgba(180, 60, 60, 230);
                }
            """)
        else:
            print("Edit Mode deactivated")
            self.edit_button.setText("Edit Mode")
            self.edit_panel.hide()  # Hide edit panel when exiting edit mode
            self.edit_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(70, 70, 70, 150); /* Semi-transparent dark grey */
                    color: white;
                    border: 1px solid rgba(100, 100, 100, 150);
                    border-radius: 5px;
                    padding: 3px 6px;
                }
                QPushButton:hover {
                    background-color: rgba(90, 90, 90, 200); /* Slightly more opaque on hover */
                }
                QPushButton:pressed {
                    background-color: rgba(50, 50, 50, 200);
                }
            """)

            # Clear any in-progress primitive creation or selection
            self.primitive_being_created = None
            self.start_point = None
            self.selected_primitive_id = None
            self.primitive_being_moved = False
            self.assigning_key_combo = False

        self.update()  # Repaint to reflect edit mode change
    # --- End Edit Mode Methods ---


# --- Main Application Logic ---
def main():
    app = QApplication(sys.argv)
    overlay = OverlayWindow()

    # --- Macro / Tap Functionality (example) ---
    def perform_tap(x, y):
        """
        Performs a tap at the given (x, y) coordinates on the Android device.
        These coordinates should be relative to the *device's native resolution*.
        """
        print(f"Attempting to tap at: ({x}, {y})")
        try:
            subprocess.run(['adb', 'shell', 'input', 'tap', str(x), str(y)], check=True, capture_output=True)
            print(f"Successfully tapped at ({x}, {y})")
        except subprocess.CalledProcessError as e:
            print(f"Error performing tap at ({x}, {y}): {e}")
            print(f"Stderr: {e.stderr.decode()}")
        except FileNotFoundError:
            print("Error: 'adb' command not found. Cannot perform tap.")

    def send_keyevent(keycode):
        """Sends an Android key event."""
        print(f"Attempting to send keyevent: {keycode}")
        try:
            subprocess.run(['adb', 'shell', 'input', 'keyevent', str(keycode)], check=True, capture_output=True)
            print(f"Successfully sent keyevent: {keycode}")
        except subprocess.CalledProcessError as e:
            print(f"Error sending keyevent {keycode}: {e}")
            print(f"Stderr: {e.stderr.decode()}")
        except FileNotFoundError:
            print("Error: 'adb' command not found. Cannot send keyevent.")

    sys.exit(app.exec_())


if __name__ == "__main__":
    # Ensure necessary libraries are installed:
    # pip install PyQt5 pygetwindow pywin32

    # First, run scrcpy manually.
    # Then run this Python script.
    print("Starting Scrcpy Overlay Macro Tool...")
    print(f"Looking for scrcpy window with title that starts with: '{SCRCPY_WINDOW_TITLE}'")
    print("Ensure 'adb.exe' is in your system's PATH environmental variable.")
    print("\nEdit Mode Controls:")
    print("  - Click 'Edit Mode' button to enter/exit edit mode")
    print("  - In edit mode, click and drag to create circles")
    print("  - Press 'C' for circle mode")
    print("  - Press 'ESC' to exit edit mode")
    print("  - Press 'Delete' to cancel current circle creation")
    print("  - Click on a circle to select it")
    print("  - Drag a selected circle to move it")
    print("  - Click the X button on a selected circle to delete it")
    print("  - When a circle is selected, type to assign a shortcut key to it")
    print("  - Click elsewhere to cancel shortcut assignment")
    print("  - Shortcut keys (with optional Ctrl, Alt, or Shift) are shown on circles")
    print("  - Shortcuts remain visible even outside edit mode")
    print("\nTroubleshooting:")
    print("  - If keyboard shortcuts don't work, click on the overlay background to ensure it has focus")
    print("  - Make sure to click and drag within the actual device display area (not in black borders)")
    print("\nStarting main application loop...")
    main()
