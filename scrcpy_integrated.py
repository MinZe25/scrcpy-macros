import queue
import subprocess
import sys
import threading

import win32con
import win32gui
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QPoint, QTimer, QPointF, QRectF, QRect, QEvent
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtGui import QWindow
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout,
                             QHBoxLayout, QLabel, QSplitter, QGroupBox, QToolBar, QAction, QSlider,
                             QComboBox, QColorDialog, QSpinBox, QTabWidget, QFrame,
                             QPlainTextEdit)

from OverlayWidget import OverlayWidget

# Constants
SCRCPY_WINDOW_TITLE = "touch1"  # The title of the scrcpy window

# Default primitives template - this will be copied to instance variable
DEFAULT_PRIMITIVES = {
    "primitive_1": {
        "type": "circle",
        "color": (50, 200, 50),  # Default green color
        "opacity": 0.7,
        "center_coords": (100, 100),  # Center position
        "dimensions": 50,  # Default radius
        "key_combo": ""  # No key combo
    },
    "primitive_2": {
        "type": "circle",
        "color": (255, 0, 0),  # Red color
        "opacity": 0.5,
        "center_coords": (500, 500),  # Center position
        "dimensions": 40,  # Default radius
        "key_combo": ""  # No key combo
    },
    "primitive_3": {
        "type": "circle",
        "color": (0, 100, 255),  # Blue color
        "opacity": 0.6,
        "center_coords": (300, 700),  # Center position
        "dimensions": 60,  # Default radius
        "key_combo": ""  # No key combo
    }
}
NEXT_PRIMITIVE_ID = 4


class ScrcpyIntegratedApp(QMainWindow):
    """Main application window that embeds scrcpy and provides editing tools"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scrcpy Integrated Controller")
        self.resize(1200, 800)

        # Setup central widget and main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Create splitter for resizable panels
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)

        # Create scrcpy process
        self.scrcpy_process = None
        self.scrcpy_hwnd = None
        self.scrcpy_container = None
        self.scrcpy_frame = None  # Initialize scrcpy_frame to prevent attribute errors

        # Initialize drawing primitives from the default template
        self.DRAWING_PRIMITIVES = DEFAULT_PRIMITIVES.copy()
        self.NEXT_PRIMITIVE_ID = NEXT_PRIMITIVE_ID

        # Create the overlay widget but don't show it yet
        # We'll properly position it after creating the scrcpy_frame
        self.drawing_overlay = OverlayWidget(self)
        self.drawing_overlay.installEventFilter(self)  # Install event filter to monitor events
        self.drawing_overlay.show()  # Explicitly show the overlay
        # Start scrcpy process
        self.start_scrcpy()

        # Find and embed scrcpy window
        QTimer.singleShot(1000, self.find_and_embed_scrcpy)

        # Variables for edit mode
        self.edit_mode_active = False
        self.selected_primitive_id = None
        self.primitive_being_created = None
        self.primitive_being_moved = False
        self.start_point = None
        self.device_width = 1920  # Default device resolution
        self.device_height = 1080
        self.new_primitive_color = (50, 200, 50)  # Default color
        self.new_primitive_opacity = 0.7  # Default opacity
        self.delete_button_size = 20  # Size of delete button

        # Create control panel
        self.create_control_panel()

        # Setup interface
        self.setup_toolbar()

        # Create a timer to update the scrcpy container size
        self.resize_timer = QTimer(self)
        self.resize_timer.timeout.connect(self.update_container_size)
        self.resize_timer.start(500)  # Update every 500ms

        # Add a status bar
        self.statusBar().showMessage("Ready")

    def start_scrcpy(self):
        """Start the scrcpy process"""
        try:
            # Start scrcpy with minimal window decoration
            self.scrcpy_process = subprocess.Popen(
                args=[
                    'scrcpy',
                    '--video-codec=h265',
                    '--max-fps=60',
                    '--tcpip=192.168.1.38',
                    '-S',
                    '--new-display=1920x1080',  # Black background
                    '--start-app=com.ankama.dofustouch',
                    f'--window-title={SCRCPY_WINDOW_TITLE}',
                    '--window-borderless'  # Keep this for seamless integration
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=1, universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW  # Prevent console window from appearing
            )

            # Create a queue for output
            self.output_queue = queue.Queue()

            # Start threads to read output
            def read_output(stream, queue, prefix):
                try:
                    for line in stream:
                        queue.put(f"{prefix}: {line.strip()}")
                except (ValueError, IOError) as e:
                    queue.put(f"{prefix} ERROR: {str(e)}")
                except Exception as e:
                    queue.put(f"{prefix} UNEXPECTED ERROR: {str(e)}")

            self.stdout_thread = threading.Thread(
                target=read_output,
                args=(self.scrcpy_process.stdout, self.output_queue, "STDOUT"),
                daemon=True
            )
            self.stderr_thread = threading.Thread(
                target=read_output,
                args=(self.scrcpy_process.stderr, self.output_queue, "STDERR"),
                daemon=True
            )

            self.stdout_thread.start()
            self.stderr_thread.start()

            # Set up a timer to update the console
            self.console_timer = QTimer(self)
            self.console_timer.timeout.connect(self.update_console_output)
            self.console_timer.start(100)  # Update every 100ms

            self.statusBar().showMessage("Scrcpy process started")
        except FileNotFoundError:
            self.statusBar().showMessage("Error: scrcpy not found in PATH")
        except Exception as e:
            self.statusBar().showMessage(f"Error starting scrcpy: {e}")

    def find_and_embed_scrcpy(self):
        """Find the scrcpy window and embed it in the application"""
        # Find the scrcpy window
        self.scrcpy_hwnd = self.find_scrcpy_window()

        if not self.scrcpy_hwnd:
            self.statusBar().showMessage("Scrcpy window not found, retrying in 1 second...")
            QTimer.singleShot(1000, self.find_and_embed_scrcpy)
            return

        # Remove the window border and title bar
        style = win32gui.GetWindowLong(self.scrcpy_hwnd, win32con.GWL_STYLE)
        style &= ~win32con.WS_CAPTION
        style &= ~win32con.WS_THICKFRAME
        style &= ~win32con.WS_MINIMIZEBOX
        style &= ~win32con.WS_MAXIMIZEBOX
        style &= ~win32con.WS_SYSMENU
        win32gui.SetWindowLong(self.scrcpy_hwnd, win32con.GWL_STYLE, style)

        # Create Qt window from the scrcpy HWND
        scrcpy_window = QWindow.fromWinId(self.scrcpy_hwnd)

        # Create container widget for the scrcpy window
        self.scrcpy_container = QWidget.createWindowContainer(scrcpy_window, self)
        self.scrcpy_container.setMinimumSize(320, 240)
        self.scrcpy_container.setFocusPolicy(Qt.StrongFocus)
        # Set red background to make it visible for debugging
        self.scrcpy_container.setStyleSheet("background-color: red;")

        # Create a frame to hold the scrcpy container and drawing overlay
        self.scrcpy_frame = QFrame()
        self.scrcpy_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.scrcpy_frame.setStyleSheet("background-color: black; border: 2px solid #666666;")
        # Install event filter to detect resize events
        self.scrcpy_frame.installEventFilter(self)

        # Setup layout for the frame
        self.scrcpy_layout = QVBoxLayout(self.scrcpy_frame)
        self.scrcpy_layout.setContentsMargins(0, 0, 0, 0)

        # Add scrcpy container to the layout
        self.scrcpy_layout.addWidget(self.scrcpy_container, 1)  # Give it stretch factor of 1 to fill the space

        # Add the frame to the splitter
        self.splitter.addWidget(self.scrcpy_frame)

        # Ensure the container is properly reparented
        self.scrcpy_container.setParent(self.scrcpy_frame)
        self.scrcpy_container.show()

        # Create the overlay widget as a child of the QMainWindow if not already created
        # Update the overlay geometry and show it
        self.update_overlay_geometry()

        # Ensure our window has focus
        self.activateWindow()
        self.raise_()

        # Explicitly activate the overlay widget
        if hasattr(self, 'drawing_overlay'):
            self.drawing_overlay.setVisible(True)
            self.drawing_overlay.raise_()
            self.drawing_overlay.activateWindow()

        # Configure splitter
        self.splitter.setStretchFactor(0, 4)  # Give more space to scrcpy
        self.splitter.setStretchFactor(1, 1)  # Less space for control panel

        # Set initial sizes
        splitter_sizes = [int(self.width() * 0.8), int(self.width() * 0.2)]
        self.splitter.setSizes(splitter_sizes)

        self.statusBar().showMessage("Scrcpy window embedded successfully")

    def find_scrcpy_window(self):
        """Find the scrcpy window by its title"""
        scrcpy_hwnd = None

        def callback(hwnd, _):
            nonlocal scrcpy_hwnd
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if window_title.startswith(SCRCPY_WINDOW_TITLE):
                    scrcpy_hwnd = hwnd
                    return False  # Stop enumeration
            return True  # Continue enumeration

        win32gui.EnumWindows(callback, None)
        return scrcpy_hwnd

    def create_control_panel(self):
        """Create the control panel with editing tools"""
        # Create control panel widget
        self.control_panel = QTabWidget()

        # Drawing tab
        self.drawing_tab = QWidget()
        drawing_layout = QVBoxLayout(self.drawing_tab)

        # Edit mode toggle button
        self.edit_mode_button = QPushButton("Enable Edit Mode")
        self.edit_mode_button.setCheckable(True)
        self.edit_mode_button.toggled.connect(self.toggle_edit_mode)
        drawing_layout.addWidget(self.edit_mode_button)

        # Circle properties group
        circle_group = QGroupBox("Circle Properties")
        circle_layout = QVBoxLayout(circle_group)

        # Color selector
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.color_button = QPushButton()
        self.color_button.setFixedSize(24, 24)
        self.color_button.setStyleSheet(
            f"background-color: rgb({self.new_primitive_color[0]}, {self.new_primitive_color[1]}, {self.new_primitive_color[2]});"
        )
        self.color_button.clicked.connect(self.select_color)
        color_layout.addWidget(self.color_button)
        circle_layout.addLayout(color_layout)

        # Opacity slider
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(self.new_primitive_opacity * 100))
        self.opacity_slider.valueChanged.connect(self.set_opacity)
        opacity_layout.addWidget(self.opacity_slider)
        circle_layout.addLayout(opacity_layout)

        drawing_layout.addWidget(circle_group)
        # Delete selected primitive button
        self.delete_primitive_button = QPushButton("Delete Selected Primitive")
        self.delete_primitive_button.clicked.connect(self.delete_selected_primitive)
        self.delete_primitive_button.setEnabled(False)
        # Primitive list group
        primitive_group = QGroupBox("Primitive List")
        primitive_layout = QVBoxLayout(primitive_group)
        self.primitive_list = QComboBox()
        self.primitive_list.addItem("No primitives")
        self.primitive_list.setEnabled(False)
        self.update_primitive_list()
        # Connect selection change to selecting the primitive
        self.primitive_list.currentIndexChanged.connect(self.on_primitive_selection_changed)
        primitive_layout.addWidget(self.primitive_list)

        primitive_layout.addWidget(self.delete_primitive_button)

        drawing_layout.addWidget(primitive_group)

        # Help text
        help_text = QLabel(
            "<b>Controls:</b><br>"
            "- Toggle Edit Mode to start drawing<br>"
            "- Click and drag to create circles<br>"
            "- Click on a circle to select it<br>"
            "- Drag a selected circle to move it"
        )
        help_text.setWordWrap(True)
        drawing_layout.addWidget(help_text)

        # Add stretch to push everything to the top
        drawing_layout.addStretch(1)

        # Device Control Tab
        self.device_tab = QWidget()
        device_layout = QVBoxLayout(self.device_tab)

        # Device information
        device_info_group = QGroupBox("Device Information")
        device_info_layout = QVBoxLayout(device_info_group)

        # Resolution settings
        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Resolution:"))
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(320, 3840)
        self.width_spinbox.setValue(self.device_width)
        self.width_spinbox.valueChanged.connect(self.set_device_width)
        res_layout.addWidget(self.width_spinbox)

        res_layout.addWidget(QLabel("x"))

        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(240, 2160)
        self.height_spinbox.setValue(self.device_height)
        self.height_spinbox.valueChanged.connect(self.set_device_height)
        res_layout.addWidget(self.height_spinbox)

        device_info_layout.addLayout(res_layout)
        device_layout.addWidget(device_info_group)

        # Common ADB commands
        adb_group = QGroupBox("ADB Commands")
        adb_layout = QVBoxLayout(adb_group)

        # Home button
        home_button = QPushButton("Home")
        home_button.clicked.connect(lambda: self.send_keyevent(3))  # HOME keycode
        adb_layout.addWidget(home_button)

        # Back button
        back_button = QPushButton("Back")
        back_button.clicked.connect(lambda: self.send_keyevent(4))  # BACK keycode
        adb_layout.addWidget(back_button)

        # Recent apps button
        recent_button = QPushButton("Recent Apps")
        recent_button.clicked.connect(lambda: self.send_keyevent(187))  # APP_SWITCH keycode
        adb_layout.addWidget(recent_button)

        device_layout.addWidget(adb_group)

        # Add stretch to push everything to the top
        device_layout.addStretch(1)

        # Console tab
        self.console_tab = QWidget()
        console_layout = QVBoxLayout(self.console_tab)

        # Console output display
        console_group = QGroupBox("Scrcpy Console Output")
        console_group_layout = QVBoxLayout(console_group)

        self.console_output = QPlainTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumBlockCount(1000)  # Limit to 1000 lines
        self.console_output.setStyleSheet("background-color: black; color: white; font-family: 'Consolas', monospace;")
        console_group_layout.addWidget(self.console_output)

        # Clear console button
        clear_console_button = QPushButton("Clear Console")
        clear_console_button.clicked.connect(self.clear_console)
        console_group_layout.addWidget(clear_console_button)

        console_layout.addWidget(console_group)

        # Add tabs to the control panel
        self.control_panel.addTab(self.drawing_tab, "Drawing")
        self.control_panel.addTab(self.device_tab, "Device Control")
        self.control_panel.addTab(self.console_tab, "Console")

        # Add control panel to the splitter
        self.splitter.addWidget(self.control_panel)

    def setup_toolbar(self):
        """Setup the application toolbar"""
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        # Edit mode action
        edit_action = QAction("Toggle Edit Mode", self)
        edit_action.triggered.connect(lambda: self.edit_mode_button.setChecked(not self.edit_mode_button.isChecked()))
        toolbar.addAction(edit_action)

        toolbar.addSeparator()

        # Restart scrcpy action
        restart_action = QAction("Restart Scrcpy", self)
        restart_action.triggered.connect(self.restart_scrcpy)
        toolbar.addAction(restart_action)

    def toggle_edit_mode(self, checked):
        """Toggle the edit mode on/off"""
        self.edit_mode_active = checked

        if checked:
            self.edit_mode_button.setText("Disable Edit Mode")
            self.statusBar().showMessage("Edit mode enabled - click and drag to create circles")
        else:
            self.edit_mode_button.setText("Enable Edit Mode")
            self.statusBar().showMessage("Edit mode disabled")
            # Reset editing state
            self.selected_primitive_id = None
            self.primitive_being_created = None
            self.primitive_being_moved = False
            self.start_point = None

        # Update the overlay to reflect edit mode change
        if hasattr(self, 'drawing_overlay'):
            self.drawing_overlay.update()
        self.update()

    def select_color(self):
        """Open color dialog to select new primitive color"""
        current_color = QColor(*self.new_primitive_color)
        color = QColorDialog.getColor(current_color, self, "Select Color")

        if color.isValid():
            self.new_primitive_color = (color.red(), color.green(), color.blue())
            self.color_button.setStyleSheet(
                f"background-color: rgb({color.red()}, {color.green()}, {color.blue()});"
            )

    def set_opacity(self, value):
        """Set the opacity for new primitives"""
        self.new_primitive_opacity = value / 100.0

    def set_device_width(self, width):
        """Set the device width"""
        self.device_width = width

    def set_device_height(self, height):
        """Set the device height"""
        self.device_height = height

    def update_primitive_list(self):
        """Update the primitive dropdown list"""
        self.primitive_list.clear()

        if not self.DRAWING_PRIMITIVES:
            self.primitive_list.addItem("No primitives")
            self.primitive_list.setEnabled(False)
            self.delete_primitive_button.setEnabled(False)
            return

        self.primitive_list.setEnabled(True)
        self.delete_primitive_button.setEnabled(True)

        for p_id, p_data in self.DRAWING_PRIMITIVES.items():
            # Include type and color information in the display
            color_name = f"RGB({p_data['color'][0]},{p_data['color'][1]},{p_data['color'][2]})"
            display_text = f"{p_id} - {p_data['type']} ({color_name})"
            self.primitive_list.addItem(display_text)

            # Store the actual primitive_id as item data
            self.primitive_list.setItemData(self.primitive_list.count() - 1, p_id)

    def on_primitive_selection_changed(self, index):
        """Handle selection change in the primitive list"""
        if index < 0:
            self.selected_primitive_id = None
            return

        # Get the primitive_id from the item data
        primitive_id = self.primitive_list.itemData(index)

        if primitive_id and primitive_id in self.DRAWING_PRIMITIVES:
            self.selected_primitive_id = primitive_id
            # Update the overlay to show selection
            if hasattr(self, 'drawing_overlay'):
                self.drawing_overlay.update()
            self.update()  # Redraw to show selection

    def delete_selected_primitive(self):
        """Delete the currently selected primitive from the dropdown"""
        current_index = self.primitive_list.currentIndex()
        if current_index < 0:
            return

        # Get the primitive_id from the item data
        primitive_id = self.primitive_list.itemData(current_index)

        if primitive_id and primitive_id in self.DRAWING_PRIMITIVES:
            del self.DRAWING_PRIMITIVES[primitive_id]
            # Update UI
            self.selected_primitive_id = None
            self.update_primitive_list()
            # Update the overlay
            if hasattr(self, 'drawing_overlay'):
                self.drawing_overlay.update()
            self.update()

    def restart_scrcpy(self):
        """Restart the scrcpy process"""
        self.statusBar().showMessage("Restarting scrcpy...")

        # Clear the console
        if hasattr(self, 'console_output'):
            self.console_output.clear()
            self.console_output.appendPlainText("=== Restarting scrcpy ===\n")

        # Stop the console update timer
        if hasattr(self, 'console_timer'):
            self.console_timer.stop()

        # Remove the current container if it exists
        if self.scrcpy_container:
            self.scrcpy_layout.removeWidget(self.scrcpy_container)
            self.scrcpy_container.deleteLater()
            self.scrcpy_container = None

        # Kill the current scrcpy process
        if self.scrcpy_process:
            try:
                self.scrcpy_process.terminate()
                self.scrcpy_process.wait(timeout=5)
            except Exception as e:
                print(f"Error terminating scrcpy: {e}")

        # Start a new scrcpy process
        self.start_scrcpy()

        # Find and embed the new scrcpy window after a delay
        QTimer.singleShot(2000, self.find_and_embed_scrcpy)

    def update_container_size(self):
        """Update the size and position of the scrcpy container to match the frame"""
        if self.scrcpy_container and self.scrcpy_frame:
            # Get the frame's content rect (accounting for layout margins)
            frame_content_rect = self.scrcpy_layout.contentsRect()

            # Check if size or position needs updating
            if (self.scrcpy_container.size() != frame_content_rect.size() or
                    self.scrcpy_container.pos() != frame_content_rect.topLeft()):
                # Update both size and position
                print(f"Adjusting container to {frame_content_rect.width()}x{frame_content_rect.height()}")
                self.scrcpy_container.resize(frame_content_rect.size())
                self.scrcpy_container.move(frame_content_rect.topLeft())

                # Ensure the container is visible and on top
                self.scrcpy_container.show()
                self.scrcpy_container.raise_()

                # Force layout update
                self.scrcpy_layout.update()
                # Also update the overlay's geometry
                self.update_overlay_geometry()
                # Request repaint
                self.update()

    def update_overlay_geometry(self):
        """Position the overlay within the scrcpy_frame to make it an overlay layer"""
        if not hasattr(self, 'drawing_overlay') or not self.scrcpy_frame:
            return
        print("Update overlay geometry")

        # Get the scrcpy_container and ensure it's valid
        if not self.scrcpy_container or not self.scrcpy_container.isVisible():
            print("Scrcpy container not visible, can't update overlay")
            return

        # Set the overlay to fill the entire frame
        # Get the inner size of the frame (accounting for layout margins)
        frame_content_rect = self.scrcpy_layout.contentsRect()

        # Resize the overlay to match the frame's content area exactly
        self.drawing_overlay.setGeometry(0, 0, self.scrcpy_frame.width(), self.scrcpy_frame.height())

        # Make sure it's visible and on top of other widgets in the scrcpy_frame
        self.drawing_overlay.setVisible(True)
        self.drawing_overlay.show()
        self.drawing_overlay.raise_()

        # Force update to trigger immediate repaint
        self.drawing_overlay.update()

        # The paintEvent method has been removed from the main window class.
        # All drawing is now handled by the OverlayWidget's paintEvent method.

    def mousePressEvent(self, event):
        """Handle mouse press events for creating and selecting primitives"""
        # Call the parent implementation first
        super().mousePressEvent(event)

        # Only handle events in edit mode
        if not self.edit_mode_active or not self.scrcpy_container or not hasattr(self, 'drawing_overlay'):
            return

        # Check if the click is within the scrcpy container
        # Use the same container_rect calculation as in paintEvent for consistency
        container_rect = QRect(self.scrcpy_container.mapTo(self, QPoint(0, 0)), self.scrcpy_container.size())

        if not container_rect.contains(event.pos()):
            return

        # Calculate device coordinates from window coordinates
        pos = event.pos()
        container_width = container_rect.width()
        container_height = container_rect.height()

        scale_factor_x = container_width / self.device_width
        scale_factor_y = container_height / self.device_height
        actual_scale = min(scale_factor_x, scale_factor_y)

        scaled_content_width = self.device_width * actual_scale
        scaled_content_height = self.device_height * actual_scale

        offset_x = container_rect.x() + (container_width - scaled_content_width) / 2
        offset_y = container_rect.y() + (container_height - scaled_content_height) / 2

        # Convert to device coordinates - use exact floating point for precise hit detection
        device_x = (pos.x() - offset_x) / actual_scale
        device_y = (pos.y() - offset_y) / actual_scale

        # Store start point for dragging
        self.start_point = (device_x, device_y)

        # Check if clicking on delete button of selected primitive
        if self.selected_primitive_id and self.is_delete_button_hit(device_x, device_y):
            self.remove_primitive(self.selected_primitive_id)
            self.selected_primitive_id = None
            self.update_primitive_list()
            self.update()
            return

        # Check if clicking on an existing primitive
        clicked_primitive_id = self.find_primitive_at_coords(device_x, device_y)
        if clicked_primitive_id:
            self.selected_primitive_id = clicked_primitive_id
            self.primitive_being_moved = True
            self.update()
            return
        else:
            # Deselect if clicking elsewhere
            self.selected_primitive_id = None

        # Start creating a new primitive
        self.primitive_being_created = {
            'type': 'circle',
            'color': self.new_primitive_color,
            'opacity': self.new_primitive_opacity,
            'center_coords': (device_x, device_y),
            'dimensions': 10  # Start with small radius
        }

        self.update()

    def mouseMoveEvent(self, event):
        """Handle mouse move events for resizing or moving primitives"""
        super().mouseMoveEvent(event)

        if not self.edit_mode_active or not self.scrcpy_container or not self.start_point:
            return

        # Check if the mouse is within the scrcpy container
        # Use the same container_rect calculation as in paintEvent for consistency
        container_rect = QRect(self.scrcpy_container.mapTo(self, QPoint(0, 0)), self.scrcpy_container.size())

        # Calculate device coordinates
        pos = event.pos()
        container_width = container_rect.width()
        container_height = container_rect.height()

        scale_factor_x = container_width / self.device_width
        scale_factor_y = container_height / self.device_height
        actual_scale = min(scale_factor_x, scale_factor_y)

        scaled_content_width = self.device_width * actual_scale
        scaled_content_height = self.device_height * actual_scale

        offset_x = container_rect.x() + (container_width - scaled_content_width) / 2
        offset_y = container_rect.y() + (container_height - scaled_content_height) / 2

        # Convert to device coordinates
        device_x = (pos.x() - offset_x) / actual_scale
        device_y = (pos.y() - offset_y) / actual_scale

        # Get distance moved from start point
        start_x, start_y = self.start_point
        dx = device_x - start_x
        dy = device_y - start_y

        # Handle moving an existing primitive
        if self.primitive_being_moved and self.selected_primitive_id:
            if self.selected_primitive_id in self.DRAWING_PRIMITIVES:
                # Update the primitive's position
                primitive = self.DRAWING_PRIMITIVES[self.selected_primitive_id]
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

                # Update the start point for the next move
                self.start_point = (device_x, device_y)

                self.update()
                return

        # Handle creating a new primitive
        if self.primitive_being_created:
            # For circle: calculate radius based on distance
            radius = int(((dx ** 2) + (dy ** 2)) ** 0.5)

            # Update the primitive being created
            self.primitive_being_created['dimensions'] = radius
            # Update the overlay
            if hasattr(self, 'drawing_overlay'):
                self.drawing_overlay.update()
            self.update()

    def mouseReleaseEvent(self, event):
        """Handle mouse release events to finalize primitive creation or movement"""
        super().mouseReleaseEvent(event)

        if not self.edit_mode_active or not self.scrcpy_container or not self.start_point:
            return

        # Handle finishing moving a primitive
        if self.primitive_being_moved and self.selected_primitive_id:
            self.primitive_being_moved = False
            self.update()
            return

        # Handle finishing creating a primitive
        if self.primitive_being_created:
            # Add the completed primitive
            self.add_primitive(
                self.primitive_being_created['type'],
                self.primitive_being_created['color'],
                self.primitive_being_created['opacity'],
                self.primitive_being_created['center_coords'],
                self.primitive_being_created['dimensions']
            )

            # Clear the in-progress primitive
            self.primitive_being_created = None

            # Update the primitive list
            self.update_primitive_list()

        # Clear the start point
        self.start_point = None
        # Update the overlay
        if hasattr(self, 'drawing_overlay'):
            self.drawing_overlay.update()
        self.update()

    def add_primitive(self, p_type, color, opacity, center_coords, dimensions):
        """Add a primitive to the drawing primitives"""
        primitive_id = f"primitive_{self.NEXT_PRIMITIVE_ID}"
        self.NEXT_PRIMITIVE_ID += 1

        self.DRAWING_PRIMITIVES[primitive_id] = {
            'type': p_type,
            'color': color,
            'opacity': opacity,
            'center_coords': center_coords,
            'dimensions': dimensions,
            'key_combo': ""  # Initialize with no key combo
        }

        # Select the newly created primitive
        self.selected_primitive_id = primitive_id

    def remove_primitive(self, primitive_id):
        """Remove a primitive from the drawing primitives"""
        if primitive_id in self.DRAWING_PRIMITIVES:
            del self.DRAWING_PRIMITIVES[primitive_id]

    def find_primitive_at_coords(self, device_x, device_y):
        """Find a primitive at the given device coordinates"""
        for p_id, p_data in self.DRAWING_PRIMITIVES.items():
            p_type = p_data['type']
            center_x, center_y = p_data['center_coords']
            dimensions = p_data['dimensions']

            if p_type == 'circle':
                radius = dimensions
                # Calculate distance from center
                distance = ((device_x - center_x) ** 2 + (device_y - center_y) ** 2) ** 0.5
                if distance <= radius:
                    return p_id
            # Add handling for other primitive types if needed in the future

        return None

    def is_delete_button_hit(self, device_x, device_y):
        """Check if the delete button of the selected primitive was hit"""
        if not self.selected_primitive_id or self.selected_primitive_id not in self.DRAWING_PRIMITIVES:
            return False

        p_data = self.DRAWING_PRIMITIVES[self.selected_primitive_id]
        center_x, center_y = p_data['center_coords']
        dimensions = p_data['dimensions']

        if p_data['type'] == 'circle':
            radius = dimensions
            # Position of delete button is at top-right of circle
            button_x = center_x + radius * 0.7
            button_y = center_y - radius * 0.7

            # Check if click is within delete button area
            distance = ((device_x - button_x) ** 2 + (device_y - button_y) ** 2) ** 0.5
            return distance <= self.delete_button_size / 2

        return False

    def send_keyevent(self, keycode):
        """Send an Android key event using adb"""
        try:
            subprocess.run(['adb', 'shell', 'input', 'keyevent', str(keycode)], check=True)
            self.statusBar().showMessage(f"Sent keyevent {keycode}")
        except Exception as e:
            self.statusBar().showMessage(f"Error sending keyevent: {e}")

    def update_console_output(self):
        """Update the console output with new content from the queue"""
        try:
            # Check if output_queue and console_output exist
            if not hasattr(self, 'output_queue') or not hasattr(self, 'console_output'):
                return

            while not self.output_queue.empty():
                line = self.output_queue.get_nowait()
                self.console_output.appendPlainText(line)
                # Auto-scroll to bottom
                self.console_output.verticalScrollBar().setValue(
                    self.console_output.verticalScrollBar().maximum()
                )
        except Exception as e:
            self.statusBar().showMessage(f"Error updating console: {e}")

    def clear_console(self):
        """Clear the console output"""
        self.console_output.clear()

    def eventFilter(self, obj, event):
        """Handle events for filtered objects"""
        if obj == self.scrcpy_frame and event.type() == QtCore.QEvent.Resize:
            # Frame was resized, update container
            if self.scrcpy_container:
                # Get the inner size of the frame (accounting for layout margins)
                frame_content_rect = self.scrcpy_layout.contentsRect()
                # Immediately resize the container to match frame content area
                self.scrcpy_container.resize(frame_content_rect.size())
                # Move container to the correct position within the frame
                self.scrcpy_container.move(frame_content_rect.topLeft())
                print(f"Frame resized to {frame_content_rect.width()}x{frame_content_rect.height()}")
                # Update the overlay geometry to match the frame's new size
                self.update_overlay_geometry()
                # Request repaint to update all overlays
                self.update()

        # Monitor overlay widget events
        elif obj == self.drawing_overlay:
            if event.type() == QtCore.QEvent.Paint:
                print("Overlay paint event detected")
            elif event.type() == QtCore.QEvent.Show:
                print("Overlay show event detected")
            elif event.type() == QtCore.QEvent.Hide:
                print("Overlay hide event detected")
            elif event.type() == QtCore.QEvent.Resize:
                print(f"Overlay resize event detected: {self.drawing_overlay.size()}")

        # Always return False to continue standard event processing
        return False

    def resizeEvent(self, event):
        """Override resizeEvent for the QMainWindow to update overlay"""
        super().resizeEvent(event)
        # Update the overlay geometry when the main window is resized
        self.update_overlay_geometry()

    def update(self):
        """Override the update method to ensure overlay gets updated too"""
        super().update()
        if hasattr(self, 'drawing_overlay') and self.drawing_overlay.isVisible():
            self.drawing_overlay.update()

    def closeEvent(self, event):
        """Clean up resources when closing the application"""
        # Stop the console update timer
        if hasattr(self, 'console_timer'):
            self.console_timer.stop()

        # Kill the scrcpy process when closing the application
        if hasattr(self, 'scrcpy_process') and self.scrcpy_process:
            try:
                self.scrcpy_process.terminate()
                try:
                    self.scrcpy_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    self.scrcpy_process.kill()
            except Exception as e:
                print(f"Error terminating scrcpy: {e}")

        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = ScrcpyIntegratedApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
