# sidebar_widget.py
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy, QFrame


class SidebarWidget(QFrame):
    settings_requested = pyqtSignal()
    edit_requested = pyqtSignal()
    instance_selected = pyqtSignal(int)
    # New signal for toggling view mode
    view_mode_toggled = pyqtSignal()

    def __init__(self, num_instances: int = 5, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(60)
        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(5, 10, 5, 5)
        self.sidebar_layout.setSpacing(10)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)


        self.instance_buttons = []  # Store instance buttons for later updates
        for i in range(num_instances):
            btn = QPushButton(f"💬{i + 1}")  # Added instance number to button text
            btn.setObjectName("SidebarButton")
            btn.setCheckable(True)  # Make instance buttons checkable
            btn.clicked.connect(lambda _, index=i: self.on_instance_button_clicked(index))
            self.sidebar_layout.addWidget(btn)
            self.instance_buttons.append(btn)

        self.sidebar_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # New button for view mode toggle
        self.view_mode_button = QPushButton("↔️")  # Unicode for left-right arrow
        self.view_mode_button.setObjectName("SidebarButton")
        self.view_mode_button.setCheckable(True)  # Make it toggleable
        self.view_mode_button.clicked.connect(self.view_mode_toggled.emit)
        self.sidebar_layout.addWidget(self.view_mode_button)

        self.edit_button = QPushButton("✏️")
        self.edit_button.setObjectName("SidebarButton")
        self.edit_button.clicked.connect(self.edit_requested.emit)
        self.sidebar_layout.addWidget(self.edit_button)

        self.settings_button = QPushButton("⚙️")
        self.settings_button.setObjectName("SidebarButton")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.sidebar_layout.addWidget(self.settings_button)

        self.update_instance_buttons(num_instances)  # Call this to ensure initial state

    def update_instance_buttons(self, num_instances: int):
        # Clear existing buttons
        for btn in self.instance_buttons:
            self.sidebar_layout.removeWidget(btn)
            btn.deleteLater()
        self.instance_buttons.clear()

        # Add new buttons based on num_instances
        # This loop needs to insert buttons before the spacer.
        # Find the index of the spacer item to insert before it.
        spacer_index = self.sidebar_layout.count() - 3  # -3 for view_mode_button, edit_button, settings_button
        if spacer_index < 0:  # In case there are no other buttons yet
            spacer_index = 0

        for i in range(num_instances):
            btn = QPushButton(f"💬{i + 1}")
            btn.setObjectName("SidebarButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, index=i: self.on_instance_button_clicked(index))
            self.sidebar_layout.insertWidget(spacer_index + i, btn)  # Insert before spacer
            self.instance_buttons.append(btn)

        # Ensure only one instance button is checked at a time when view is stacked
        if self.instance_buttons:
            self.instance_buttons[0].setChecked(True)  # Select first instance by default

    def on_instance_button_clicked(self, index: int):
        # Uncheck all other instance buttons
        for i, btn in enumerate(self.instance_buttons):
            if i != index:
                btn.setChecked(False)
        self.instance_selected.emit(index)

    def set_instance_button_checked(self, index: int):
        if 0 <= index < len(self.instance_buttons):
            self.instance_buttons[index].setChecked(True)
            for i, btn in enumerate(self.instance_buttons):
                if i != index:
                    btn.setChecked(False)