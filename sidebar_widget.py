from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy, QFrame


class SidebarWidget(QFrame):
    settings_requested = pyqtSignal()
    edit_requested = pyqtSignal()
    instance_selected = pyqtSignal(int)

    def __init__(self, num_instances: int = 5, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(60)
        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(5, 10, 5, 5)
        self.sidebar_layout.setSpacing(10)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        for i in range(num_instances):
            btn = QPushButton("💬")
            btn.setObjectName("SidebarButton")
            btn.clicked.connect(lambda _, index=i: self.on_instance_button_clicked(index))
            self.sidebar_layout.addWidget(btn)

        self.sidebar_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.edit_button = QPushButton("✏️")
        self.edit_button.setObjectName("SidebarButton")
        self.edit_button.clicked.connect(self.edit_requested.emit)
        self.sidebar_layout.addWidget(self.edit_button)

        self.settings_button = QPushButton("⚙️")
        self.settings_button.setObjectName("SidebarButton")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.sidebar_layout.addWidget(self.settings_button)

    def on_instance_button_clicked(self, index: int):
        print(f"Sidebar: Instance button {index + 1} clicked, emitting index {index}.")
        self.instance_selected.emit(index)
