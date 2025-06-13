# Scrcpy Multi-Instance Keymapper

## Project Description

This application provides a multi-instance interface for managing and interacting with Android devices using `scrcpy`. It allows users to run multiple `scrcpy` instances simultaneously, each embedded within a dedicated container. A key feature is the ability to create and customize "keymaps" – interactive overlay elements on each `scrcpy` display. These keymaps can be configured to trigger specific key combinations when clicked, offering a powerful way to define custom macros or shortcuts directly on the Android screen.

## Features

* **Multi-Instance Scrcpy:** Run and manage multiple `scrcpy` instances, each in its own dedicated view.
* **Embedded Scrcpy Displays:** Seamlessly embed `scrcpy` windows directly into the application's UI.
* **Customizable Keymaps:** Create, move, resize, and delete interactive overlay elements (keymaps) on each `scrcpy` display.
* **Key Combination Assignment:** Assign custom keyboard key combinations to each keymap.
* **"Hold" Functionality:** Toggle a "hold" state for keymaps, potentially for persistent key presses or different interaction behaviors.
* **Edit Mode:** A dedicated editing mode for visual configuration of keymaps, including a grid for precise placement.
* **Dynamic Scrcpy Configuration:** Configure various `scrcpy` parameters like resolution, FPS, video codec, and more through application settings.
* **Device Management:** Connect to devices via USB or TCP/IP.
* **Non-Blocking Operations:** Efficiently handle external process output without freezing the UI.

## Requirements

Before running the application, ensure you have the following installed:

* **Python 3.x**: The application is developed in Python.
* **PyQt5**: The GUI framework.
    ```bash
    pip install PyQt5
    ```
* **PyWin32**: Required for Windows-specific window manipulation (embedding `scrcpy` windows).
    ```bash
    pip install pywin32
    ```
* **scrcpy**: The core tool for Android screen mirroring and control. Download and install `scrcpy` from its official GitHub repository or your preferred package manager. Ensure `scrcpy.exe` is in your system's PATH.
    * [scrcpy GitHub](https://github.com/Genymobile/scrcpy)
* **ADB (Android Debug Bridge)**: `scrcpy` relies on `adb`. Ensure `adb.exe` is also in your system's PATH. It typically comes with Android SDK Platform-Tools.
    * [Android SDK Platform-Tools](https://developer.android.com/studio/releases/platform-tools)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone [repository_url]
    cd [repository_directory]
    ```
2.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt # (Assuming you create a requirements.txt from the above list)
    ```
    If you don't have a `requirements.txt`, run:
    ```bash
    pip install PyQt5 pywin32
    ```
3.  **Verify `scrcpy` and `adb` installation:**
    Open a command prompt and type `scrcpy --version` and `adb --version`. Both should return version information without errors.

## Usage

1.  **Run the application:**
    ```bash
    python main.py # (Assuming your main entry point is main.py)
    ```
2.  **Connecting Devices:**
    * Ensure your Android device(s) have USB debugging enabled.
    * Connect your device(s) via USB.
    * For TCP/IP connections, configure the `tcpip_address` in the application's settings (if a settings UI is implemented).
3.  **Managing Instances:**
    * The sidebar on the left will show buttons like "💬1", "💬2", etc. Click these to switch between different `scrcpy` instances.
    * Each instance will attempt to connect to an available Android device or a specified device if configured.
4.  **Edit Mode (Keymap Creation and Modification):**
    * Click the "✏️" (Edit) button in the sidebar to activate edit mode.
    * In edit mode, the `scrcpy` display will show a grid.
    * **Create a Keymap:** Click and drag on the `scrcpy` display to draw a new circular keymap.
    * **Move a Keymap:** Click and drag an existing keymap to reposition it.
    * **Resize a Keymap:** (Implicit from creation, likely by dragging)
    * **Assign Key Combination:**
        * Click on a keymap to select it. It will be highlighted in yellow.
        * Press the desired key or key combination (e.g., `Shift+A`, `Ctrl+B`). The keymap's text will update.
    * **Delete a Keymap:**
        * Select a keymap.
        * Click the "X" button that appears near its top-right corner, or press the `Delete` key.
    * **Toggle "Hold" State:**
        * Select a keymap.
        * Click the "H" button that appears near its top-left corner. This toggles the `hold` property of the keymap.
    * **Exit Edit Mode:** Click the "✏️" (Edit) button again. Changes to keymaps are saved automatically upon exiting edit mode.
5.  **View Mode Toggle:**
    * Click the "↔️" button in the sidebar to toggle between different view modes (e.g., stacked instances, tiled instances). (This functionality is signaled but its implementation details are not in the provided snippets).
6.  **Settings:**
    * Click the "⚙️" (Settings) button to access the application's settings. (The settings UI itself is not provided, but the `MainContentAreaWidget` uses settings for `scrcpy` parameters).

## Configuration (Settings)

The application uses a `settings` dictionary to configure `scrcpy` instances and other behaviors. While a dedicated settings UI is not provided in these files, common configurable `scrcpy` parameters include:

* `use_tcpip`: Boolean to enable TCP/IP connection.
* `tcpip_address`: IP address and port for TCP/IP connection (e.g., "192.168.1.100:5555").
* `video_codec`: Video codec to use (e.g., "h264", "h265").
* `max_fps`: Maximum frames per second (e.g., 30, 60).
* `resolution`: Screen resolution (e.g., "1920x1080", "720x1280").
* `density`: Screen density (e.g., 240, 320).
* `start_app`: Package name of an app to start on connection.
* `turn_screen_off`: Boolean to turn the device screen off.
* `no_audio`: Boolean to disable audio forwarding.
* `no_decorations`: Boolean to remove system decorations from the `scrcpy` window.
* `default_keymap_size`: Default pixel diameter for newly created keymaps (used in `OverlayWidget`).
* `overlay_bg_color`, `overlay_border_color`, `overlay_text_color`: Colors for keymap appearance.

These settings would typically be managed in a configuration file (e.g., JSON, YAML) or a dedicated settings dialog.

## Contributing

(If this is an open-source project, include information on how others can contribute, e.g., "Fork the repository, make your changes, and submit a pull request.")

## License

(Specify the license under which your project is distributed, e.g., MIT, GPL, Apache 2.0.)

---