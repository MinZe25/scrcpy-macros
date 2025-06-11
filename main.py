import sys
import subprocess
import win32gui
import win32con
import time  # For potential small delays if needed

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QSizePolicy, QSpacerItem, QDialog,
    QStackedWidget, QSizeGrip, QSplitter, QTabWidget  # Added QSplitter and QTabWidget back for the original example
)
from PyQt5.QtGui import QPainter, QColor, QFont, QCursor, QWindow
from PyQt5.QtCore import Qt, QRect, QPoint, QRectF, QSize, QTimer, pyqtSignal, QEvent

from settings_dialog import SettingsDialog

# Constants for window resizing
RESIZE_BORDER_WIDTH = 8
# Masks for resize corners/edges
CORNER_DRAG = True
LEFT = 1
RIGHT = 2
TOP = 4
BOTTOM = 8
TOP_LEFT = 5
TOP_RIGHT = 6
BOTTOM_LEFT = 9
BOTTOM_RIGHT = 10

# SCRCPY_WINDOW_TITLE_BASE is now a prefix/base, actual title will be dynamic per instance
SCRCPY_WINDOW_TITLE_BASE = "Lindo_Scrcpy_Instance"

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


# --- OverlayWidget Class (As provided by user) ---
class OverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        taskbar_height = 50
        taskbar_rect = QRectF(0, 0, self.width(), taskbar_height)
        taskbar_color = QColor(30, 30, 30, 150)
        painter.fillRect(taskbar_rect, taskbar_color)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(10, 30, "Overlay Controls Here")

        circle_radius = 50
        circle_center_x = self.width() // 2
        circle_center_y = self.height() // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 0, 0, 120))
        painter.drawEllipse(circle_center_x - circle_radius, circle_center_y - circle_radius,
                            circle_radius * 2, circle_radius * 2)
        painter.end()


# --- Custom Title Bar Class ---
class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setObjectName("TitleBar")  # For stylesheet targeting

        self.setFixedHeight(35)  # Standard height for title bars

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # App Icon/Title
        self.app_icon = QLabel("Bonito")  # Using an emoji as a placeholder icon
        self.app_icon.setFont(QFont("Inter", 16))
        self.layout.addWidget(self.app_icon)

        self.layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Extra button (optional, as per request)
        self.extra_button = QPushButton("🏠")  # Home icon
        self.extra_button.setObjectName("ExtraButton")
        self.extra_button.clicked.connect(lambda: print("Extra button clicked"))  # Debug print
        self.layout.addWidget(self.extra_button)

        # Window control buttons
        self.min_button = QPushButton("─")  # Minimize icon
        self.min_button.setObjectName("MinimizeButton")
        self.min_button.clicked.connect(self.parent_window.showMinimized)
        self.min_button.clicked.connect(lambda: print("Minimize button clicked"))  # Debug print
        self.layout.addWidget(self.min_button)

        self.max_button = QPushButton("⬜")  # Maximize/Restore icon (will change based on state)
        self.max_button.setObjectName("MaximizeButton")
        self.max_button.clicked.connect(self.parent_window.toggle_maximize_restore)  # Connect to parent's method
        self.max_button.clicked.connect(lambda: print("Maximize/Restore button clicked"))  # Debug print
        self.layout.addWidget(self.max_button)

        self.close_button = QPushButton("✕")  # Close icon
        self.close_button.setObjectName("CloseButton")
        self.close_button.clicked.connect(self.parent_window.close)
        self.close_button.clicked.connect(lambda: print("Close button clicked"))  # Debug print
        self.layout.addWidget(self.close_button)



# --- Sidebar Widget Class ---
class SidebarWidget(QFrame):
    settings_requested = pyqtSignal()
    instance_selected = pyqtSignal(int)  # Emits the index of the instance/page

    def __init__(self, num_instances: int = 5, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(60)

        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(5, 10, 5, 5)
        self.sidebar_layout.setSpacing(10)

        for i in range(num_instances):
            btn = QPushButton(f"💬")  # Chat icon placeholder
            btn.setObjectName("SidebarButton")
            btn.clicked.connect(lambda _, index=i: self._on_instance_button_clicked(index))
            self.sidebar_layout.addWidget(btn)

        self.sidebar_layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        self.settings_button = QPushButton("⚙️")  # Gear icon
        self.settings_button.setObjectName("SettingsButton")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.sidebar_layout.addWidget(self.settings_button)

    def _on_instance_button_clicked(self, index: int):
        print(f"Sidebar: Instance button {index + 1} clicked, emitting index {index}.")
        self.instance_selected.emit(index)


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


# --- Main Content Area Widget Class (Revised with explicit win32gui.MoveWindow and eventFilter) ---
class MainContentAreaWidget(QWidget):
    def __init__(self, instance_id: int, device_serial: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("MainContentWidget")
        self.instance_id = instance_id
        self.device_serial = device_serial
        self.scrcpy_process = None
        self.scrcpy_hwnd = None
        self.scrcpy_qwindow = None
        self.scrcpy_container_widget = None

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

        self.start_scrcpy()
        self.installEventFilter(self)  # Install event filter on THIS WIDGET

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
                '--new-display=1920x1080',
                '--start-app=com.ankama.dofustouch',
                f'--window-title={self.scrcpy_expected_title}',
            ]

            self.scrcpy_process = subprocess.Popen(
                scrcpy_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print(f"Scrcpy process for instance {self.instance_id + 1} started with PID: {self.scrcpy_process.pid}")

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

        else:
            print(
                f"Scrcpy window '{self.scrcpy_expected_title}' for instance {self.instance_id + 1} not found, retrying in 1 second...")
            QTimer.singleShot(1000, self.find_and_embed_scrcpy)

    def eventFilter(self, source, event):
        # We need to react when THIS WIDGET (MainContentAreaWidget) resizes
        # because its layout manages the scrcpy_container_widget's size.
        if source == self and event.type() == QEvent.Resize:
            self.resize_scrcpy_native_window()
            print("resizing native")
            return True
        return super().eventFilter(source, event)

    def resize_scrcpy_native_window(self):
        if not self.scrcpy_hwnd or not self.scrcpy_container_widget:
            return

        container_rect = self.scrcpy_container_widget.rect()
        width = container_rect.width()
        height = container_rect.height()

        try:
            # Explicitly move and resize the native HWND
            win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, width, height, True)
            print(
                f"Scrcpy window {self.scrcpy_hwnd} (Instance {self.instance_id + 1}) forced resize to: {width}x{height}")
            # Optional: Verify actual dimensions after move
            # left, top, right, bottom = win32gui.GetWindowRect(self.scrcpy_hwnd)
            # actual_width = right - left
            # actual_height = bottom - top
            # print(f"Actual size reported by Windows: {actual_width}x{actual_height}.")

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
            print(f"Terminating Scrcpy process for instance {self.instance_id + 1} (PID: {self.scrcpy_process.pid})...")

            if self.scrcpy_hwnd:
                win32gui.ShowWindow(self.scrcpy_hwnd, win32con.SW_HIDE)
                win32gui.SetParent(self.scrcpy_hwnd, 0)

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
            print(f"Scrcpy process for instance {self.instance_id + 1} terminated.")
        elif self.scrcpy_process:
            print(f"Scrcpy process for instance {self.instance_id + 1} already stopped.")
            self.scrcpy_process = None
            self.scrcpy_hwnd = None
            self.scrcpy_qwindow = None
            self.scrcpy_container_widget = None


# --- Main Application Window ---
class MyQtApp(QMainWindow):
    _gripSize = 8

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lindo Integrated Controller")
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowFlags(Qt.FramelessWindowHint)

        self.sideGrips = [
            SideGrip(self, Qt.LeftEdge),
            SideGrip(self, Qt.TopEdge),
            SideGrip(self, Qt.RightEdge),
            SideGrip(self, Qt.BottomEdge),
        ]
        self.cornerGrips = [QSizeGrip(self) for i in range(4)]

        self.setStyleSheet(GLOBAL_STYLESHEET)

        self._resizing = False
        self._moving = False
        self._drag_position = None
        self._resize_mode = None
        self.setMouseTracking(True)

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        self.main_layout.addWidget(self.title_bar)

        self.content_layout = QHBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.main_layout.addLayout(self.content_layout, 1)

        self.num_instances = 1
        device_serials = [None] * self.num_instances

        self.sidebar = SidebarWidget(num_instances=self.num_instances, parent=self)
        self.sidebar.settings_requested.connect(self.open_settings_dialog)
        self.content_layout.addWidget(self.sidebar)

        self.stacked_widget = QStackedWidget(self)
        self.content_layout.addWidget(self.stacked_widget, 1)

        self.main_content_pages = []
        for i in range(self.num_instances):
            serial = device_serials[i] if i < len(device_serials) else None
            page = MainContentAreaWidget(instance_id=i, device_serial=serial, parent=self)
            self.stacked_widget.addWidget(page)
            self.main_content_pages.append(page)

        self.sidebar.instance_selected.connect(self.stacked_widget.setCurrentIndex)
        self.stacked_widget.currentChanged.connect(self._on_stacked_widget_page_changed)

        if self.num_instances > 0:
            self.stacked_widget.setCurrentIndex(0)
            print("MyQtApp: Initial MainContentAreaWidget set to index 0.")

        self.update_max_restore_button()

    @property
    def gripSize(self):
        return self._gripSize

    def setGripSize(self, size):
        if size == self._gripSize:
            return
        self._gripSize = max(2, size)
        self.updateGrips()

    def updateGrips(self):
        self.setContentsMargins(*[self.gripSize] * 4)

        outRect = self.rect()
        inRect = outRect.adjusted(self.gripSize, self.gripSize,
                                  -self.gripSize, -self.gripSize)

        self.cornerGrips[0].setGeometry(
            QRect(outRect.topLeft(), inRect.topLeft()))
        self.cornerGrips[1].setGeometry(
            QRect(outRect.topRight(), inRect.topRight()).normalized())
        self.cornerGrips[2].setGeometry(
            QRect(inRect.bottomRight(), outRect.bottomRight()))
        self.cornerGrips[3].setGeometry(
            QRect(outRect.bottomLeft(), inRect.bottomLeft()).normalized())

        self.sideGrips[0].setGeometry(
            0, inRect.top(), self.gripSize, inRect.height())
        self.sideGrips[1].setGeometry(
            inRect.left(), 0, inRect.width(), self.gripSize)
        self.sideGrips[2].setGeometry(
            inRect.left() + inRect.width(),
            inRect.top(), self.gripSize, inRect.height())
        self.sideGrips[3].setGeometry(
            self.gripSize, inRect.top() + inRect.height(),
            inRect.width(), self.gripSize)

    def resizeEvent(self, event):
        QMainWindow.resizeEvent(self, event)
        self.updateGrips()
        self.update_max_restore_button()

    def _get_resize_mode(self, pos: QPoint):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        mode = 0

        if CORNER_DRAG:
            if x < RESIZE_BORDER_WIDTH and y < RESIZE_BORDER_WIDTH:
                mode = TOP_LEFT
            elif x > w - RESIZE_BORDER_WIDTH and y < RESIZE_BORDER_WIDTH:
                mode = TOP_RIGHT
            elif x < RESIZE_BORDER_WIDTH and y > h - RESIZE_BORDER_WIDTH:
                mode = BOTTOM_LEFT
            elif x > w - RESIZE_BORDER_WIDTH and y > h - RESIZE_BORDER_WIDTH:
                mode = BOTTOM_RIGHT

        if mode == 0:
            if x < RESIZE_BORDER_WIDTH:
                mode = LEFT
            elif x > w - RESIZE_BORDER_WIDTH:
                mode = RIGHT
            if y < RESIZE_BORDER_WIDTH:
                mode |= TOP
            elif y > h - RESIZE_BORDER_WIDTH:
                mode |= BOTTOM

        return mode

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._resize_mode = self._get_resize_mode(event.pos())
            if self._resize_mode != 0:
                self._resizing = True
                self._drag_position = event.globalPos()
                event.accept()
            elif self.title_bar.geometry().contains(event.pos()):
                self._moving = True
                self._drag_position = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
            else:
                super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isMaximized():
            self.unsetCursor()
            super().mouseMoveEvent(event)
            return

        if self._resizing:
            diff = event.globalPos() - self._drag_position
            new_rect = self.geometry()

            if self._resize_mode & LEFT:
                new_rect.setLeft(new_rect.left() + diff.x())
            if self._resize_mode & RIGHT:
                new_rect.setRight(new_rect.right() + diff.x())
            if self._resize_mode & TOP:
                new_rect.setTop(new_rect.top() + diff.y())
            if self._resize_mode & BOTTOM:
                new_rect.setBottom(new_rect.bottom() + diff.y())

            self.setGeometry(new_rect.normalized())
            self._drag_position = event.globalPos()
            event.accept()

        elif self._moving:
            self.move(event.globalPos() - self._drag_position)
            event.accept()

        else:
            mode = self._get_resize_mode(event.pos())
            if mode == LEFT or mode == RIGHT:
                self.setCursor(Qt.SizeHorCursor)
            elif mode == TOP or mode == BOTTOM:
                self.setCursor(Qt.SizeVerCursor)
            elif mode == TOP_LEFT or mode == BOTTOM_RIGHT:
                self.setCursor(Qt.SizeFDiagCursor)
            elif mode == TOP_RIGHT or mode == BOTTOM_LEFT:
                self.setCursor(Qt.SizeBDiagCursor)
            else:
                self.unsetCursor()
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        self._moving = False
        self._drag_position = None
        self._resize_mode = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.title_bar.geometry().contains(event.pos()):
            self.toggle_maximize_restore()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.update_max_restore_button()

    def leaveEvent(self, event):
        if not self._resizing and not self._moving:
            self.unsetCursor()
        super().leaveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self.isMaximized() or self.isMinimized():
                self.unsetCursor()
            else:
                pass
        super().changeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background_color = QColor(40, 42, 54)
        painter.setBrush(background_color)
        painter.setPen(Qt.NoPen)
        border_radius = 10
        painter.drawRoundedRect(self.rect(), border_radius, border_radius)

    def update_max_restore_button(self):
        if self.isMaximized():
            self.title_bar.max_button.setText("❐")
        else:
            self.title_bar.max_button.setText("⬜")

    def showEvent(self, event):
        super().showEvent(event)
        self.update_max_restore_button()
        self.updateGrips()

    def _on_stacked_widget_page_changed(self, index: int):
        print(f"Stacked widget page changed to index: {index}")
        current_page = self.stacked_widget.widget(index)
        for i, page in enumerate(self.main_content_pages):
            if page.scrcpy_hwnd:
                if i == index:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_SHOW)
                    # Crucially, force resize when the page becomes active
                    page.resize_scrcpy_native_window()
                else:
                    win32gui.ShowWindow(page.scrcpy_hwnd, win32con.SW_HIDE)

    def closeEvent(self, event):
        print("Closing application, stopping all Scrcpy processes...")
        for page in self.main_content_pages:
            page.stop_scrcpy()
        super().closeEvent(event)

    def open_settings_dialog(self):
        print("Opening settings dialog...")
        settings_dialog = SettingsDialog(self)
        settings_dialog.exec_()


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