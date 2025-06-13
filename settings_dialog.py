import json
import sys
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QLineEdit, QCheckBox, QSpinBox, QComboBox, QPushButton,
    QLabel, QSpacerItem, QSizePolicy, QDoubleSpinBox
)
from PyQt5.QtCore import Qt


# --- Settings Dialog for Scrcpy Instances ---

class SettingsDialog(QDialog):
    """
    A dialog for configuring multiple scrcpy instances.
    Each instance's settings are managed in a separate tab.
    """

    def __init__(self, current_settings=None, parent=None):
        """
        Initializes the settings dialog.

        Args:
            current_settings (list or dict, optional): A list of dictionaries for scrcpy instances,
                                                        or a dictionary containing 'instances' and 'general_settings'.
                                                        Defaults to None, which creates one default tab.
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle("Scrcpy Settings")
        self.setMinimumSize(500, 450)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Store the initial settings and a placeholder for the new settings on save
        # Handle both old list format and new dict format
        if isinstance(current_settings, dict) and "instances" in current_settings:
            self.initial_instance_settings = current_settings.get("instances", [])
            self.initial_general_settings = current_settings.get("general_settings", {})
        else:
            self.initial_instance_settings = current_settings or []
            self.initial_general_settings = {} # Default empty general settings

        self.final_settings = {} # This will store both instance and general settings

        print("Initializing settings")
        # --- Main Layout ---
        main_layout = QVBoxLayout(self)

        # --- Tab Widget for Instances ---
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Add General Tab First
        self._add_general_tab()


        # --- Tab Management Buttons ---
        tab_management_layout = QHBoxLayout()
        add_instance_btn = QPushButton("＋ Add Instance")
        add_instance_btn.clicked.connect(self._add_new_tab)
        tab_management_layout.addWidget(add_instance_btn)

        remove_instance_btn = QPushButton("－ Remove Current Instance")
        remove_instance_btn.clicked.connect(self._remove_current_tab)
        tab_management_layout.addWidget(remove_instance_btn)
        tab_management_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        main_layout.addLayout(tab_management_layout)

        # --- Dialog Action Buttons ---
        button_layout = QHBoxLayout()
        button_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        save_btn = QPushButton("Save & Close")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        main_layout.addLayout(button_layout)

        # Populate the tabs with the provided settings
        self._load_initial_instance_settings()

    def _add_general_tab(self):
        """Adds the General settings tab."""
        general_tab_widget = self._create_general_tab(self.initial_general_settings)
        self.tab_widget.addTab(general_tab_widget, "General")

    def _create_general_tab(self, settings: dict = None) -> QWidget:
        """
        Creates a widget for the General settings tab.

        Args:
            settings (dict, optional): A dictionary of general settings to populate the fields with.
                                       If None, defaults are used.

        Returns:
            QWidget: The configured widget to be used as the General tab page.
        """
        if settings is None:
            settings = {}

        tab_page = QWidget()
        layout = QFormLayout(tab_page)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        layout.setLabelAlignment(Qt.AlignRight)

        # Background Color
        bg_color_field = QLineEdit(settings.get("overlay_bg_color", "#3498db")) # Default blue
        bg_color_field.setPlaceholderText("e.g., #RRGGBB or blue")
        layout.addRow("Overlay Background Color:", bg_color_field)
        tab_page.overlay_bg_color_field = bg_color_field

        # Border Color
        border_color_field = QLineEdit(settings.get("overlay_border_color", "#2c3e50")) # Default dark blue/grey
        border_color_field.setPlaceholderText("e.g., #RRGGBB or black")
        layout.addRow("Overlay Border Color:", border_color_field)
        tab_page.overlay_border_color_field = border_color_field

        # Text Color
        text_color_field = QLineEdit(settings.get("overlay_text_color", "#ffffff")) # Default white
        text_color_field.setPlaceholderText("e.g., #RRGGBB or white")
        layout.addRow("Overlay Text Color:", text_color_field)
        tab_page.overlay_text_color_field = text_color_field

        # Default New Keymap Size
        default_keymap_size_spinbox = QSpinBox()
        default_keymap_size_spinbox.setRange(10, 500)
        default_keymap_size_spinbox.setValue(settings.get("default_keymap_size", 50))
        default_keymap_size_spinbox.setSuffix(" px")
        layout.addRow("Default New Keymap Size:", default_keymap_size_spinbox)
        tab_page.default_keymap_size_field = default_keymap_size_spinbox

        # Overlay Opacity
        overlay_opacity_spinbox = QDoubleSpinBox()
        overlay_opacity_spinbox.setRange(0.1, 1.0)
        overlay_opacity_spinbox.setSingleStep(0.05)
        overlay_opacity_spinbox.setValue(settings.get("overlay_opacity", 0.7))
        overlay_opacity_spinbox.setSuffix("") # No suffix as it's a ratio
        layout.addRow("Overlay Opacity:", overlay_opacity_spinbox)
        tab_page.overlay_opacity_field = overlay_opacity_spinbox

        # Spacer to push elements to top
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        return tab_page


    def _load_initial_instance_settings(self):
        """Loads the initial list of instance settings into the tab widget."""
        if not self.initial_instance_settings:
            # If no settings are provided, create one default tab
            self._add_new_tab(is_default=True)
        else:
            # Create a tab for each setting dictionary provided
            for settings_data in self.initial_instance_settings:
                instance_name = settings_data.get("instance_name", f"Instance {self.tab_widget.count()}") # Adjust count due to General tab
                new_tab_widget = self._create_instance_tab(settings_data)
                self.tab_widget.addTab(new_tab_widget, instance_name)

    def _create_instance_tab(self, settings: dict = None) -> QWidget:
        """
        Creates a widget for a single tab, containing all the scrcpy settings fields.

        Args:
            settings (dict, optional): A dictionary of settings to populate the fields with.
                                       If None, defaults are used.

        Returns:
            QWidget: The configured widget to be used as a tab page.
        """
        if settings is None:
            settings = {}

        # --- Create main widget and layout for the tab ---
        tab_page = QWidget()
        layout = QFormLayout(tab_page)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        layout.setLabelAlignment(Qt.AlignRight)

        # --- Instance Name ---
        # Adjust count due to General tab
        instance_name = QLineEdit(settings.get("instance_name", f"Instance {self.tab_widget.count()}"))
        instance_name.setPlaceholderText("e.g., Dofus-1 or Main-Account")
        instance_name.textChanged.connect(lambda text: self.tab_widget.setTabText(self.tab_widget.currentIndex(), text))
        layout.addRow("Instance Name:", instance_name)
        # Store widget reference to retrieve value later
        tab_page.instance_name_field = instance_name

        # --- Connection Type (TCP/IP vs USB) ---
        use_tcpip_checkbox = QCheckBox("Enable TCP/IP Connection")
        use_tcpip_checkbox.setChecked(settings.get("use_tcpip", True))
        layout.addRow(use_tcpip_checkbox)
        tab_page.use_tcpip_field = use_tcpip_checkbox

        tcpip_address_field = QLineEdit(settings.get("tcpip_address", "192.168.1.38"))
        tcpip_address_field.setPlaceholderText("Enter device IP address")
        tcpip_address_label = QLabel("IP Address:")
        layout.addRow(tcpip_address_label, tcpip_address_field)

        # Toggle visibility of the IP address field based on the checkbox
        use_tcpip_checkbox.toggled.connect(tcpip_address_field.setVisible)
        use_tcpip_checkbox.toggled.connect(tcpip_address_label.setVisible)
        tcpip_address_field.setVisible(use_tcpip_checkbox.isChecked())
        tcpip_address_label.setVisible(use_tcpip_checkbox.isChecked())
        tab_page.tcpip_address_field = tcpip_address_field

        # --- Video Settings ---
        video_codec_combo = QComboBox()
        video_codec_combo.addItems(["h265", "h264", "av1"])
        video_codec_combo.setCurrentText(settings.get("video_codec", "h265"))
        layout.addRow("Video Codec:", video_codec_combo)
        tab_page.video_codec_field = video_codec_combo

        max_fps_spinbox = QSpinBox()
        max_fps_spinbox.setRange(1, 120)
        max_fps_spinbox.setValue(settings.get("max_fps", 60))
        max_fps_spinbox.setSuffix(" FPS")
        layout.addRow("Max Framerate:", max_fps_spinbox)
        tab_page.max_fps_field = max_fps_spinbox

        # --- Display Settings ---
        resolution_field = QLineEdit(settings.get("resolution", "1920x1080"))
        resolution_field.setPlaceholderText("e.g., 1920x1080")
        layout.addRow("Resolution (WxH):", resolution_field)
        tab_page.resolution_field = resolution_field


        # --- App & Window Settings ---
        start_app_field = QLineEdit(settings.get("start_app", "com.ankama.dofustouch"))
        start_app_field.setPlaceholderText("e.g., com.android.chrome")
        layout.addRow("Start App on Connect:", start_app_field)
        tab_page.start_app_field = start_app_field

        # --- Other Boolean Flags ---
        flags_layout = QHBoxLayout()
        turn_screen_off_check = QCheckBox("Turn Screen Off (-S)")
        turn_screen_off_check.setChecked(settings.get("turn_screen_off", True))
        flags_layout.addWidget(turn_screen_off_check)
        tab_page.turn_screen_off_field = turn_screen_off_check

        no_decorations_check = QCheckBox("No System Decorations")
        no_decorations_check.setChecked(settings.get("no_decorations", False))
        flags_layout.addWidget(no_decorations_check)
        tab_page.no_decorations_field = no_decorations_check
        no_audio_check = QCheckBox("No Audio")
        no_audio_check.setChecked(settings.get("no_audio", False))
        flags_layout.addWidget(no_audio_check)
        tab_page.no_audio_field = no_audio_check

        flags_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addRow("Other Flags:", flags_layout)

        return tab_page

    def _add_new_tab(self, is_default=False):
        """Adds a new, empty tab to the tab widget."""
        # For the first default tab, don't show a confirmation if the user tries to remove it
        # Otherwise, every new tab is just a standard instance.
        instance_name = f"Instance {self.tab_widget.count()}" # Adjust count due to General tab
        new_tab_widget = self._create_instance_tab()
        self.tab_widget.addTab(new_tab_widget, instance_name)
        self.tab_widget.setCurrentWidget(new_tab_widget)

    def _remove_current_tab(self):
        """Removes the currently selected tab, but not if it's the last one or the General tab."""
        current_index = self.tab_widget.currentIndex()
        # Prevent removal of General tab (index 0) and ensure at least one instance tab remains
        if current_index == 0 or self.tab_widget.count() <= 2: # 1 for General, 1 for instance
            print("Cannot remove the General tab or the last instance tab.")
            return

        self.tab_widget.removeTab(current_index)


    def _save_settings(self):
        """
        Gathers all settings from all tabs and stores them in self.final_settings.
        Then, accepts the dialog.
        """
        # Save General Settings first (assuming it's always the first tab)
        general_tab = self.tab_widget.widget(0)
        self.final_settings["general_settings"] = {
            "overlay_bg_color": general_tab.overlay_bg_color_field.text(),
            "overlay_border_color": general_tab.overlay_border_color_field.text(),
            "overlay_text_color": general_tab.overlay_text_color_field.text(),
            "default_keymap_size": general_tab.default_keymap_size_field.value(),
            "overlay_opacity": general_tab.overlay_opacity_field.value(),
        }

        # Save Instance Settings (starting from the second tab)
        instance_settings_list = []
        for i in range(1, self.tab_widget.count()): # Start from 1 to skip General tab
            tab = self.tab_widget.widget(i)
            settings_data = {
                "instance_name": tab.instance_name_field.text(),
                "use_tcpip": tab.use_tcpip_field.isChecked(),
                "tcpip_address": tab.tcpip_address_field.text(),
                "video_codec": tab.video_codec_field.currentText(),
                "max_fps": tab.max_fps_field.value(),
                "resolution": tab.resolution_field.text(),
                "start_app": tab.start_app_field.text(),
                "turn_screen_off": tab.turn_screen_off_field.isChecked(),
                "no_decorations": tab.no_decorations_field.isChecked(),
                "no_audio": tab.no_audio_field.isChecked(),
            }
            instance_settings_list.append(settings_data)
        self.final_settings["instances"] = instance_settings_list

        print("Settings saved:")
        with open('settings.json', 'w') as f:
            json.dump(self.final_settings, f, indent=2)

        self.accept()

    def get_settings(self):
        """
        Public method to retrieve the saved settings after the dialog is closed.

        Returns:
            dict: A dictionary containing 'instances' and 'general_settings', or None if cancelled.
        """
        return self.final_settings


# --- Example Usage (for standalone testing) ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    def load_settings_from_local_json():
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                return json.load(f)
            print(f"Keymaps loaded from {'settings.json'}.")
        except Exception as e:
            print(f"Error loading keymaps from {'settings.json'}: {e}. Starting with empty keymaps.")
            return None # Return None if loading fails

    # Example of pre-existing settings you might load from a file
    # If this is None or empty, the dialog will start with one default tab
    sample_settings = load_settings_from_local_json()

    dialog = SettingsDialog(current_settings=sample_settings)

    # The exec_() method shows the dialog modally and blocks until it's closed.
    # It returns True if the dialog was accepted (Save), False if rejected (Cancel/Close).
    if dialog.exec_():
        # If saved, retrieve the new settings
        new_settings = dialog.get_settings()
        print("\nDialog accepted. Final settings:")
        print(json.dumps(new_settings, indent=2))
        # Here you would save `new_settings` to your config file
    else:
        print("\nDialog cancelled. No changes were made.")

    sys.exit()