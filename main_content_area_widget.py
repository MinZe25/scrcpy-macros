import win32con
import re
import subprocess

import win32gui
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QEvent
from PyQt5.QtGui import QWindow
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy

from non_blocking_stream_reader import NonBlockingStreamReader


class MainContentAreaWidget(QWidget):
    scrcpy_container_ready = pyqtSignal()

    def __init__(self, instance_id: int, settings: dict, title_base: str, device_serial: str = None, parent=None, ):
        super().__init__(parent)
        self.start_instance = 0
        self.start = False
        self.start = self.start or self.start_instance == instance_id
        self.settings = settings
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
        self.scrcpy_expected_title = f"{title_base}_{self.instance_id}"

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
        if self.start:
            QTimer.singleShot(1000 * instance_id, self.start_scrcpy)
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
            cmd = ['scrcpy']

            # Check if TCPIP is enabled and an address is provided, then extend the command.
            if self.settings.get('use_tcpip') and self.settings.get('tcpip_address'):
                cmd.extend([f"--tcpip={self.settings.get('tcpip_address')}"])

            # Check if a video codec is specified, then extend the command.
            if self.settings.get('video_codec'):
                cmd.extend([f"--video-codec={self.settings.get('video_codec')}"])

            # Check if a maximum FPS is specified, then extend the command (converted to string).
            if self.settings.get('max_fps'):
                cmd.extend([f"--max-fps={str(self.settings.get('max_fps'))}"])

            # Prepare the display string, including resolution and optional density.
            display_str = self.settings.get('resolution', '1920x1080')
            if self.settings.get('density'):
                display_str += f"/{self.settings.get('density')}"
            cmd.extend([f"--new-display={display_str}"])

            # Add the window title to the command.
            cmd.extend([f"--window-title={self.scrcpy_expected_title}"])

            # If 'start_app' setting is present, add it to the command in the desired format: '--start-app=value'.
            if self.settings.get('start_app'):
                cmd.extend([f"--start-app={self.settings.get('start_app')}"])

            # Check if screen turn-off is enabled, then append the '-S' flag (this flag doesn't take a value).
            if self.settings.get('turn_screen_off'):
                cmd.append('-S')
            if self.settings.get('no_audio'):
                cmd.append('--no-audio')

            # Check if no decorations are desired, then append the corresponding flag (this flag doesn't take a value).
            if self.settings.get('no_decorations'):
                cmd.append('--no-vd-system-decorations')

            print(f"Executing: {str.join(' ', cmd)}")
            self.scrcpy_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
