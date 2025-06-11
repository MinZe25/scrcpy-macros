from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFrame, QSplitter, QTabWidget
)
from PyQt5.QtGui import QPainter, QColor, QWindow
from PyQt5.QtCore import Qt, QRect, QPoint, QRectF, QEvent, QTimer

# Import win32gui and win32con for Windows API calls
import win32gui
import win32con

# (Keep your OverlayWidget class definition as before)
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


class ScrcpyIntegratedController(QMainWindow):
    def __init__(self, scrcpy_hwnd): # Pass the scrcpy_hwnd to the constructor
        super().__init__()
        self.scrcpy_hwnd = scrcpy_hwnd # Store the HWND
        self.setWindowTitle("Scrcpy Integrated Controller")
        self.setGeometry(100, 100, 1000, 700)

        self.splitter = QSplitter(self)
        self.setCentralWidget(self.splitter)

        control_panel = QTabWidget()
        control_panel.addTab(QLabel("Drawing Controls Placeholder"), "Drawing")
        control_panel.addTab(QLabel("Device Control Placeholder"), "Device Control")
        control_panel.addTab(QLabel("Console Placeholder"), "Console")
        self.splitter.addWidget(control_panel)

        self.scrcpy_frame = QFrame()
        self.scrcpy_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.scrcpy_frame.setStyleSheet("background-color: black; border: 2px solid #666666;")

        self.scrcpy_layout = QVBoxLayout(self.scrcpy_frame)
        self.scrcpy_layout.setContentsMargins(0, 0, 0, 0)

        # Create Qt window from the scrcpy HWND
        scrcpy_qwindow = QWindow.fromWinId(self.scrcpy_hwnd)

        # Create container widget for the scrcpy window
        self.scrcpy_container = QWidget.createWindowContainer(scrcpy_qwindow, self.scrcpy_frame)
        self.scrcpy_container.setMinimumSize(320, 240)
        self.scrcpy_container.setFocusPolicy(Qt.StrongFocus)
        self.scrcpy_container.setStyleSheet("background-color: red;") # Debug color
        # Install event filter directly on the container to precisely track its resizes
        self.scrcpy_container.installEventFilter(self)
        self.scrcpy_frame.installEventFilter(self) # Still filtering frame resizes


        self.scrcpy_layout.addWidget(self.scrcpy_container, 1)
        self.splitter.addWidget(self.scrcpy_frame)
        self.splitter.setSizes([300, 700])

        self.drawing_overlay = OverlayWidget(self)
        self.drawing_overlay.hide()

        # Initial update for overlay and scrcpy window
        QTimer.singleShot(100, self.update_scrcpy_and_overlay_geometry) # Small delay to ensure layouts are settled

    def eventFilter(self, source, event):
        # We need to react when the scrcpy_container itself resizes
        # because the layout manages its size.
        if source == self.scrcpy_container and event.type() == QEvent.Resize:
            # The scrcpy_container has resized, now resize the native window
            self.resize_scrcpy_native_window()
            # Also update the overlay, as its target area might have changed
            self.update_overlay_geometry()
            return True # Event handled

        # Also handle frame resize, as it might indirectly cause container resize
        if source == self.scrcpy_frame and event.type() == QEvent.Resize:
            # The frame resized, which would trigger scrcpy_container's resize
            # So, we don't need to explicitly call resize_scrcpy_native_window here
            # since the container's eventFilter will catch it.
            # But we might want to update the overlay geometry directly.
            self.update_overlay_geometry()


        return super().eventFilter(source, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Call this to ensure overlay is always correctly positioned when main window resizes
        # and also to trigger potential scrcpy_container resize if splitter moves
        self.update_scrcpy_and_overlay_geometry()

    def update_scrcpy_and_overlay_geometry(self):
        # This method ensures both the native scrcpy window and the overlay are updated.
        # It's called from resizeEvent and initial setup.
        self.resize_scrcpy_native_window()
        self.update_overlay_geometry()


    def resize_scrcpy_native_window(self):
        if not self.scrcpy_hwnd:
            print("Scrcpy HWND not available for resizing.")
            return

        # Get the current size of the QWidget container for the native window
        container_rect = self.scrcpy_container.rect()
        width = container_rect.width()
        height = container_rect.height()

        # The native window should be positioned at (0,0) relative to its QWidget container
        # and have the same dimensions.
        try:
            # win32gui.MoveWindow(hWnd, x, y, width, height, repaint)
            # x, y are relative to the parent window (which for CreateWindowContainer
            # is typically an internal Qt window, so (0,0) is correct for its client area)
            win32gui.MoveWindow(self.scrcpy_hwnd, 0, 0, width, height, True)
            # print(f"Resized scrcpy_hwnd to: {width}x{height}")
        except Exception as e:
            print(f"Error resizing scrcpy_hwnd: {e}")

    def update_overlay_geometry(self):
        # Calculate the geometry of scrcpy_frame relative to the QMainWindow's viewport
        # This remains the same as in the previous solution.
        frame_global_pos = self.scrcpy_frame.mapToGlobal(QPoint(0, 0))
        frame_local_pos_in_main_window = self.mapFromGlobal(frame_global_pos)
        frame_rect_in_main_window = QRect(frame_local_pos_in_main_window, self.scrcpy_frame.size())

        self.drawing_overlay.setGeometry(frame_rect_in_main_window)
        self.drawing_overlay.raise_()
        self.drawing_overlay.show()


    def enable_drawing_mode(self):
        self.drawing_overlay.show()
        self.drawing_overlay.raise_()
        self.drawing_overlay.update()

    def disable_drawing_mode(self):
        self.drawing_overlay.hide()


# --- How to run this example with a dummy HWND ---
# In a real scenario, you'd get the scrcpy_hwnd from your scrcpy process.
# For demonstration, we'll create a dummy window and use its HWND.

SCRCPY_WINDOW_TITLE = "touch1"  # The title of the scrcpy window


def find_scrcpy_window() -> int:
    """Find the scrcpy window by its title"""
    scrcpy_hwnd = None

    def callback(hwnd, _):
        nonlocal scrcpy_hwnd
        window_title = win32gui.GetWindowText(hwnd)
        if window_title.startswith(SCRCPY_WINDOW_TITLE):
            scrcpy_hwnd = hwnd
            print("Found")
            # return False  # Stop enumeration
        return True  # Continue enumeration

    win32gui.EnumWindows(callback, None)
    return scrcpy_hwnd

if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)

    # 1. Start Scrcpy (e.g., as a subprocess) and get its HWND.
    #    For this example, we'll create a dummy window to simulate scrcpy_hwnd.
    scrcpy_dummy_hwnd = find_scrcpy_window()

    # 2. Pass the real scrcpy HWND to your controller
    window = ScrcpyIntegratedController(scrcpy_dummy_hwnd)
    window.show()

    sys.exit(app.exec_())