# Scrcpy Integrated Controller

This application embeds the scrcpy window directly into a Qt interface, providing a seamless experience for controlling and annotating Android devices.

## Features

- Embedded scrcpy window within the application
- Drawing tools for adding interactive elements to the screen
- Device controls for common Android actions
- Color and opacity controls for drawing elements
- Edit mode for adding and manipulating screen elements

## Requirements

- Python 3.x
- PyQt5
- scrcpy (must be in your PATH)
- adb (Android Debug Bridge)
- A connected Android device with USB debugging enabled

## Installation

1. Ensure you have scrcpy installed and in your PATH
2. Install the required Python packages:

```
pip install PyQt5 pywin32
```

## Usage

1. Connect your Android device via USB and ensure USB debugging is enabled
2. Run the application:

```
python scrcpy_integrated.py
```

3. The application will automatically start scrcpy and embed it in the window

### Drawing Mode

1. Click "Enable Edit Mode" to enter drawing mode
2. Click and drag on the screen to create circles
3. Select a circle to move it or delete it
4. Use the color picker and opacity slider to customize new circles

### Device Control

- Use the Device Control tab to send common Android commands
- Set the correct device resolution for accurate coordinate mapping

## Troubleshooting

- If scrcpy doesn't start, ensure it's installed and in your PATH
- If the application can't find your device, check your ADB connection
- Use the "Restart Scrcpy" button if the connection is lost

## License

This project is open source and available under the MIT License.
