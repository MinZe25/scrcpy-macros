class Keymap:
    """
    Represents a single keymap with its visual properties and associated key combination.
    Stores position and size as normalized floats (0.0 to 1.0).
    """

    def __init__(self, normalized_size: tuple, keycombo: list, normalized_position: tuple, type: str = "circle"):
        """
        Initialize a Keymap object.
        Args:
            normalized_size (tuple): A tuple (normalized_width, normalized_height) floats (0.0-1.0).
            keycombo (list): A list of Qt.Key values (integers) representing the key combination.
            normalized_position (tuple): A tuple (normalized_x, normalized_y) floats (0.0-1.0).
            type (str): The type of visual element for the keymap (e.g., "circle", "rectangle", "text").
        """
        self.normalized_size = QSizeF(normalized_size[0], normalized_size[1])
        self.keycombo = keycombo
        self.normalized_position = QPointF(normalized_position[0], normalized_position[1])
        self.type = type

    def to_dict(self):
        """Converts the Keymap object to a dictionary for JSON serialization."""
        return {
            "normalized_size": [self.normalized_size.width(), self.normalized_size.height()],
            "keycombo": self.keycombo,
            "normalized_position": [self.normalized_position.x(), self.normalized_position.y()],
            "type": self.type
        }

    @staticmethod
    def from_dict(data: dict):
        """Creates a Keymap object from a dictionary."""
        return Keymap(
            normalized_size=tuple(data["normalized_size"]),
            keycombo=data["keycombo"],
            normalized_position=tuple(data["normalized_position"]),
            type=data["type"]
        )
