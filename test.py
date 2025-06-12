import subprocess
import re
import json


def get_scrcpy_displays_as_json(device_ip=None):
    """
    Executes 'scrcpy --list-displays' and parses its output into a JSON-like structure.

    Args:
        device_ip (str, optional): The IP address of the Android device to target.
                                   If None, it assumes there's only one device or it's connected via USB.

    Returns:
        list: A list of dictionaries, where each dictionary represents a display
              with 'id', 'width', and 'height'. Returns an empty list if no displays are found
              or an error occurs.
    """
    command = ["scrcpy", "--list-displays"]
    if device_ip:
        command.extend(["-s", device_ip])

    try:
        # Using shell=True for simpler command execution if scrcpy path is complex
        # but generally False is safer. Assuming scrcpy is in PATH or full path is provided.
        process = subprocess.run(command, capture_output=True, text=True, check=True)

        # stderr might contain INFO messages from scrcpy, so we check both.
        # The display list is usually in stdout.
        output_lines = (process.stdout + process.stderr).strip().split('\n')

        displays = []
        # CORRECTED REGEX: changed '--display=' to '--display-id='
        display_pattern = re.compile(r"--display-id=(\d+)\s+\((\d+)x(\d+)\)")

        for line in output_lines:
            # Strip leading/trailing whitespace from the line before matching
            line = line.strip()
            match = display_pattern.search(line)
            if match:
                display_id = int(match.group(1))
                width = int(match.group(2))
                height = int(match.group(3))
                displays.append({
                    "id": display_id,
                    "width": width,
                    "height": height
                })
        return displays

    except FileNotFoundError:
        print("Error: 'scrcpy' command not found. Ensure scrcpy is installed and in your PATH.")
        return []
    except subprocess.CalledProcessError as e:
        print(f"Error running scrcpy --list-displays: {e.stderr}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []


# --- Example Usage ---
# Use the device IP from your scrcpy output
device_ip = "192.168.1.38"  # Use the full IP:port from your scrcpy output

displays_info = get_scrcpy_displays_as_json(device_ip)

if displays_info:
    print("Detected Displays (JSON format):")
    print(json.dumps(displays_info, indent=2))

    # You can then access specific display info:
    for display in displays_info:
        print(f"Display ID: {display['id']}, Resolution: {display['width']}x{display['height']}")
else:
    print("No displays found or an error occurred.")