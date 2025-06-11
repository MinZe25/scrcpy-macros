import sys
import subprocess
import threading
import queue
import win32gui
import win32con
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout,
                             QHBoxLayout, QLabel, QSplitter, QGroupBox, QToolBar, QAction, QSlider,
                             QComboBox, QCheckBox, QColorDialog, QSpinBox, QTabWidget, QFrame,
                             QTextEdit, QPlainTextEdit)
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QIcon, QFont
from PyQt5.QtCore import Qt, QPoint, QTimer, QRectF, QSize, QRect, QPointF
from PyQt5.QtGui import QWindow, QResizeEvent

# Constants
SCRCPY_WINDOW_TITLE = "touch1"  # The title of the scrcpy window
DRAWING_PRIMITIVES = {
    "primitive_1": {
        "type": "circle",
        "color": (50, 200, 50),  # Default green color
        "opacity": 0.7,
        "center_coords": (100, 100),  # Top left corner position
        "dimensions": 50,  # Default radius
        "key_combo": ""  # No key combo
    }
}
NEXT_PRIMITIVE_ID = 2


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
                bufsize=1, universal_newlines=True
            )

            # Create a queue for output
            self.output_queue = queue.Queue()

            # Start threads to read output
            def read_output(stream, queue, prefix):
                for line in stream:
                    queue.put(f"{prefix}: {line.strip()}")

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

        # Create a frame to hold the scrcpy container and drawing overlay
        self.scrcpy_frame = QFrame()
        self.scrcpy_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.scrcpy_frame.setStyleSheet("background-color: black;")

        self.scrcpy_layout = QVBoxLayout(self.scrcpy_frame)
        self.scrcpy_layout.setContentsMargins(0, 0, 0, 0)
        self.scrcpy_layout.addWidget(self.scrcpy_container)

        # Add to the splitter
        self.splitter.addWidget(self.scrcpy_frame)

        # Configure splitter
        self.splitter.setStretchFactor(0, 3)  # Give more space to scrcpy
        self.splitter.setStretchFactor(1, 1)  # Less space for control panel

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

        # Update the container to reflect edit mode change
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

        if not DRAWING_PRIMITIVES:
            self.primitive_list.addItem("No primitives")
            self.primitive_list.setEnabled(False)
            self.delete_primitive_button.setEnabled(False)
            return

        self.primitive_list.setEnabled(True)
        self.delete_primitive_button.setEnabled(True)

        for p_id in DRAWING_PRIMITIVES:
            self.primitive_list.addItem(p_id)

    def delete_selected_primitive(self):
        """Delete the currently selected primitive from the dropdown"""
        current_text = self.primitive_list.currentText()

        if current_text != "No primitives" and current_text in DRAWING_PRIMITIVES:
            del DRAWING_PRIMITIVES[current_text]
            self.update_primitive_list()
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
        """Update the size of the scrcpy container to match the frame"""
        if self.scrcpy_container and self.scrcpy_frame:
            # Ensure the container fills the frame
            self.scrcpy_container.resize(self.scrcpy_frame.size())

    def paintEvent(self, event):
        """Paint the primitives on top of the scrcpy container"""
        super().paintEvent(event)

        if not self.scrcpy_container or not hasattr(self, 'scrcpy_frame'):
            return

        # Create a painter for the window
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get the scrcpy container's global geometry
        container_rect = self.scrcpy_container.geometry()
        container_pos = self.scrcpy_container.mapTo(self, QPoint(0, 0))
        container_rect.moveTo(container_pos)

        # Draw edit mode overlay
        if self.edit_mode_active:
            # Semi-transparent overlay to indicate edit mode
            painter.fillRect(container_rect, QColor(50, 50, 50, 40))

            # Draw guide grid
            grid_color = QColor(200, 200, 200, 50)
            painter.setPen(QPen(grid_color, 1, Qt.DashLine))

            # Calculate scale factors
            scale_factor_x = container_rect.width() / self.device_width
            scale_factor_y = container_rect.height() / self.device_height
            actual_scale = min(scale_factor_x, scale_factor_y)

            # Calculate content area size and offset
            scaled_content_width = self.device_width * actual_scale
            scaled_content_height = self.device_height * actual_scale
            offset_x = container_rect.x() + (container_rect.width() - scaled_content_width) / 2
            offset_y = container_rect.y() + (container_rect.height() - scaled_content_height) / 2

            # Draw horizontal grid lines
            for y in range(0, self.device_height + 1, 100):
                scaled_y = offset_y + y * actual_scale
                painter.drawLine(
                    int(offset_x), int(scaled_y),
                    int(offset_x + scaled_content_width), int(scaled_y)
                )

            # Draw vertical grid lines
            for x in range(0, self.device_width + 1, 100):
                scaled_x = offset_x + x * actual_scale
                painter.drawLine(
                    int(scaled_x), int(offset_y),
                    int(scaled_x), int(offset_y + scaled_content_height)
                )

        # Draw all primitives
        if self.scrcpy_container:
            # Calculate scale factors
            container_width = container_rect.width()
            container_height = container_rect.height()

            scale_factor_x = container_width / self.device_width
            scale_factor_y = container_height / self.device_height
            actual_scale = min(scale_factor_x, scale_factor_y)

            # Calculate content area size and offset
            scaled_content_width = self.device_width * actual_scale
            scaled_content_height = self.device_height * actual_scale
            offset_x = container_rect.x() + (container_width - scaled_content_width) / 2
            offset_y = container_rect.y() + (container_height - scaled_content_height) / 2

            # Draw all primitives
            for p_id, p_data in DRAWING_PRIMITIVES.items():
                p_type = p_data['type']
                color_rgb = p_data['color']
                opacity = p_data['opacity']
                center_x, center_y = p_data['center_coords']
                dimensions = p_data['dimensions']

                # Calculate scaled coordinates
                scaled_center_x = offset_x + center_x * actual_scale
                scaled_center_y = offset_y + center_y * actual_scale

                # Set color with opacity
                color = QColor(color_rgb[0], color_rgb[1], color_rgb[2])
                color.setAlphaF(opacity)
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)

                if p_type == 'circle':
                    radius = dimensions
                    scaled_radius = radius * actual_scale
                    painter.drawEllipse(
                        QPointF(scaled_center_x, scaled_center_y),
                        scaled_radius, scaled_radius
                    )

                    # Draw selection indicator for selected primitive
                    if self.edit_mode_active and p_id == self.selected_primitive_id:
                        # Draw selection outline
                        select_pen = QPen(Qt.white, 2, Qt.DashLine)
                        painter.setPen(select_pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawEllipse(
                            QPointF(scaled_center_x, scaled_center_y),
                            scaled_radius + 5, scaled_radius + 5
                        )

                        # Draw delete button
                        delete_x = scaled_center_x + scaled_radius * 0.7
                        delete_y = scaled_center_y - scaled_radius * 0.7
                        delete_button_radius = self.delete_button_size / 2

                        # Draw red circle for delete button
                        delete_color = QColor(255, 50, 50, 230)
                        painter.setBrush(delete_color)
                        painter.setPen(Qt.NoPen)
                        painter.drawEllipse(
                            QPointF(delete_x, delete_y),
                            delete_button_radius, delete_button_radius
                        )

                        # Draw X inside button
                        painter.setPen(QPen(Qt.white, 2))
                        x_size = delete_button_radius * 0.7
                        painter.drawLine(
                            int(delete_x - x_size), int(delete_y - x_size),
                            int(delete_x + x_size), int(delete_y + x_size)
                        )
                        painter.drawLine(
                            int(delete_x + x_size), int(delete_y - x_size),
                            int(delete_x - x_size), int(delete_y + x_size)
                        )

            # Draw primitive being created
            if self.primitive_being_created:
                p_data = self.primitive_being_created
                color_rgb = p_data['color']
                opacity = p_data['opacity']
                center_x, center_y = p_data['center_coords']
                dimensions = p_data['dimensions']

                # Calculate scaled coordinates
                scaled_center_x = offset_x + center_x * actual_scale
                scaled_center_y = offset_y + center_y * actual_scale

                # Set color with opacity
                color = QColor(color_rgb[0], color_rgb[1], color_rgb[2])
                color.setAlphaF(opacity)
                painter.setBrush(color)

                # Draw with dashed outline
                outline_pen = QPen(QColor(255, 255, 255, 150), 2, Qt.DashLine)
                painter.setPen(outline_pen)

                if p_data['type'] == 'circle':
                    radius = dimensions
                    scaled_radius = radius * actual_scale
                    painter.drawEllipse(
                        QPointF(scaled_center_x, scaled_center_y),
                        scaled_radius, scaled_radius
                    )

    def mousePressEvent(self, event):
        """Handle mouse press events for creating and selecting primitives"""
        # Call the parent implementation first
        super().mousePressEvent(event)

        # Only handle events in edit mode
        if not self.edit_mode_active or not self.scrcpy_container:
            return

        # Check if the click is within the scrcpy container
        container_rect = self.scrcpy_container.geometry()
        container_pos = self.scrcpy_container.mapTo(self, QPoint(0, 0))
        container_rect.moveTo(container_pos)

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

        # Convert to device coordinates
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
        container_rect = self.scrcpy_container.geometry()
        container_pos = self.scrcpy_container.mapTo(self, QPoint(0, 0))
        container_rect.moveTo(container_pos)

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
        self.update()

    def add_primitive(self, p_type, color, opacity, center_coords, dimensions):
        """Add a primitive to the drawing primitives"""
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

        # Select the newly created primitive
        self.selected_primitive_id = primitive_id

    def remove_primitive(self, primitive_id):
        """Remove a primitive from the drawing primitives"""
        if primitive_id in DRAWING_PRIMITIVES:
            del DRAWING_PRIMITIVES[primitive_id]

    def find_primitive_at_coords(self, device_x, device_y):
        """Find a primitive at the given device coordinates"""
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

        return None

    def is_delete_button_hit(self, device_x, device_y):
        """Check if the delete button of the selected primitive was hit"""
        if not self.selected_primitive_id or self.selected_primitive_id not in DRAWING_PRIMITIVES:
            return False

        p_data = DRAWING_PRIMITIVES[self.selected_primitive_id]
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

    def closeEvent(self, event):
        """Clean up resources when closing the application"""
        # Stop the console update timer
        if hasattr(self, 'console_timer'):
            self.console_timer.stop()

        # Kill the scrcpy process when closing the application
        if self.scrcpy_process:
            try:
                self.scrcpy_process.terminate()
                self.scrcpy_process.wait(timeout=2)
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
