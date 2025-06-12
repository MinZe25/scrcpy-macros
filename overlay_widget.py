import math

from PyQt5.QtCore import pyqtSignal, Qt, QPoint, QRectF, QPointF, QSizeF
from PyQt5.QtGui import QKeySequence, QPainter, QColor, QFontMetrics, QMouseEvent, QKeyEvent
from PyQt5.QtWidgets import QWidget

from keymap import Keymap


class OverlayWidget(QWidget):
    keymaps_changed = pyqtSignal(list)  # Signal to notify parent of keymap changes

    def __init__(self, keymaps: list = None, parent=None, is_transparent_to_mouse: bool = False):
        """
        Initialize an OverlayWidget.
        Args:
            keymaps (list): A reference to the list of keymap objects.
            parent (QWidget): The parent widget.
            is_transparent_to_mouse (bool): If True, mouse events will pass through this widget.
        """
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Set transparency attribute ONLY ONCE based on init parameter
        self.setAttribute(Qt.WA_TransparentForMouseEvents, is_transparent_to_mouse)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)

        # Set focus policy to allow key events when in edit mode (if not transparent to mouse)
        # Otherwise, focus policy should allow events to pass through implicitly.
        self.setFocusPolicy(Qt.StrongFocus if not is_transparent_to_mouse else Qt.NoFocus)

        self.keymaps = keymaps if keymaps is not None else []
        self.edit_mode_active = False  # Controls visual elements like grid and selection
        self._dragging_keymap = None
        self._creating_keymap = False
        self._drag_start_pos_local = QPoint()  # Stores the QPoint of mousePressEvent (pixel)
        self._keymap_original_pixel_pos = QPoint()  # Original pixel position of keymap when drag starts
        self._selected_keymap_for_combo_edit = None
        self._pending_modifier_key = None  # To handle Shift+A, Ctrl+B etc.

        # Enable mouse tracking to show appropriate cursor in edit mode
        self.setMouseTracking(True)

    def _get_key_text(self, qt_key_code: int) -> str:
        """Converts a Qt.Key code to its string representation for display."""
        if qt_key_code == Qt.Key_Shift:
            return "S"
        elif qt_key_code == Qt.Key_Control:
            return "C"
        elif qt_key_code == Qt.Key_Alt:
            return "A"
        # For other keys, use QKeySequence to get the standard string
        return QKeySequence(qt_key_code).toString()

    def set_keymaps(self, keymaps_list: list):
        """Sets the keymaps from an external source. Assumes it's a shared list."""
        self.keymaps = keymaps_list  # We are given a reference to the shared list
        self.update()  # Redraw to show updated keymaps

    def set_edit_mode(self, active: bool):
        """
        Activates or deactivates the keymap editing mode for this specific overlay.
        This primarily affects drawing (grid, selection) and focus policy if this overlay is meant to interact.
        It DOES NOT change mouse transparency here.
        """
        self.edit_mode_active = active

        # Only set focus policy if this overlay is designed to capture events (i.e., not transparent to mouse)
        if not self.testAttribute(Qt.WA_TransparentForMouseEvents):
            self.setFocusPolicy(Qt.StrongFocus if active else Qt.NoFocus)

        if not active:
            # Clear any active editing states when leaving edit mode
            self._dragging_keymap = None
            self._creating_keymap = False
            self._selected_keymap_for_combo_edit = None
            self._pending_modifier_key = None
            self.unsetCursor()  # Reset cursor

            # Emit signal when exiting edit mode to save changes (only the edit overlay will do this)
            self.keymaps_changed.emit(self.keymaps)

        self.update()  # Request repaint to show/hide grid/selection

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        # Draw semi-transparent background if in edit mode (only the edit overlay)
        if self.edit_mode_active:
            painter.setBrush(QColor(0, 0, 0, 60))  # Black with 60 alpha (more transparent)
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())  # Cover the entire widget

            grid_size = 50  # Size of each grid cell
            painter.setPen(QColor(100, 100, 100, 80))  # Light grey, semi-transparent
            for x in range(0, self.width(), grid_size):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), grid_size):
                painter.drawLine(0, y, self.width(), y)

        for keymap in self.keymaps:
            # Convert normalized position and size to pixel coordinates
            pixel_x = keymap.normalized_position.x() * self.width()
            pixel_y = keymap.normalized_position.y() * self.height()
            pixel_width = keymap.normalized_size.width() * self.width()
            pixel_height = keymap.normalized_size.height() * self.height()
            keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)

            # Highlight selected keymap in edit mode
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                painter.setPen(QColor(255, 255, 0))  # Yellow highlight
                painter.setBrush(QColor(255, 255, 0, 50))  # Light yellow fill
                painter.drawRoundedRect(keymap_rect.adjusted(-5, -5, 5, 5), 5,
                                        5)  # Draw a slightly larger, rounded highlight
            elif self.edit_mode_active and keymap == self._dragging_keymap:
                painter.setPen(QColor(0, 255, 255))  # Cyan highlight for dragging
                painter.setBrush(QColor(0, 255, 255, 50))
                painter.drawRoundedRect(keymap_rect.adjusted(-3, -3, 3, 3), 3, 3)

            if keymap.type == "circle":
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 120))  # Red, 120 alpha
                painter.drawEllipse(keymap_rect)  # Draw ellipse using the keymap's rect

                # Prepare and draw text for the key combination
                key_texts = [self._get_key_text(kc) for kc in keymap.keycombo]
                display_text = "+".join(key_texts) if key_texts else "KEY"  # Default text if no key is set

                # Dynamically adjust font size to fit text within the keymap rectangle
                font = painter.font()
                font.setFamily("Inter")  # Use a clean, readable font
                max_font_size = 72  # Start with a large font size
                min_font_size = 6  # Minimum readable font size

                for font_size in range(max_font_size, min_font_size - 1, -1):
                    font.setPointSize(font_size)
                    painter.setFont(font)
                    metrics = QFontMetrics(font)
                    text_bounding_rect = metrics.boundingRect(display_text)
                    if text_bounding_rect.width() <= keymap_rect.width() * 0.9 and \
                            text_bounding_rect.height() <= keymap_rect.height() * 0.9:
                        break  # Found a font size that fits

                painter.setPen(QColor(255, 255, 255))  # White text for key combo
                painter.drawText(keymap_rect, Qt.AlignCenter, display_text)

            # Draw the 'X' button if in edit mode and this keymap is selected
            if self.edit_mode_active and keymap == self._selected_keymap_for_combo_edit:
                x_button_size_pixels = 25
                x_button_rect = QRectF(
                    keymap_rect.right() - x_button_size_pixels / 2,
                    keymap_rect.top() - x_button_size_pixels / 2,
                    x_button_size_pixels,
                    x_button_size_pixels
                )
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 0, 0, 200))
                painter.drawEllipse(x_button_rect)
                font = painter.font()
                font.setPointSize(int(x_button_size_pixels * 0.7))
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(x_button_rect, Qt.AlignCenter, "X")

        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mousePressEvent(event)
            return

        if event.button() == Qt.LeftButton:
            self._drag_start_pos_local = event.pos()

            if self._selected_keymap_for_combo_edit:
                selected_keymap = self._selected_keymap_for_combo_edit
                pixel_x = selected_keymap.normalized_position.x() * self.width()
                pixel_y = selected_keymap.normalized_position.y() * self.height()
                pixel_width = selected_keymap.normalized_size.width() * self.width()
                pixel_height = selected_keymap.normalized_size.height() * self.height()
                selected_keymap_pixel_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)

                x_button_size_pixels = 25
                x_button_rect = QRectF(
                    selected_keymap_pixel_rect.right() - x_button_size_pixels / 2,
                    selected_keymap_pixel_rect.top() - x_button_size_pixels / 2,
                    x_button_size_pixels,
                    x_button_size_pixels
                )

                if x_button_rect.contains(event.pos()):
                    self.keymaps.remove(selected_keymap)
                    self._selected_keymap_for_combo_edit = None
                    self.keymaps_changed.emit(self.keymaps)
                    self.update()
                    event.accept()
                    return

            self._selected_keymap_for_combo_edit = None
            clicked_on_existing_keymap = False

            for keymap in self.keymaps:
                pixel_x = keymap.normalized_position.x() * self.width()
                pixel_y = keymap.normalized_position.y() * self.height()
                pixel_width = keymap.normalized_size.width() * self.width()
                pixel_height = keymap.normalized_size.height() * self.height()
                keymap_rect = QRectF(pixel_x, pixel_y, pixel_width, pixel_height)

                if keymap_rect.contains(event.pos()):
                    self._dragging_keymap = keymap
                    self._keymap_original_pixel_pos = QPoint(int(pixel_x), int(pixel_y))
                    clicked_on_existing_keymap = True
                    break

            if not clicked_on_existing_keymap:
                self._creating_keymap = True
                new_keymap = Keymap(normalized_size=(0.01, 0.01),
                                    keycombo=[],
                                    normalized_position=(event.pos().x() / self.width(),
                                                         event.pos().y() / self.height()))
                self.keymaps.append(new_keymap)
                self._dragging_keymap = new_keymap

            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mouseMoveEvent(event)
            return

        if self._dragging_keymap:
            if self._creating_keymap:
                dx = event.pos().x() - self._drag_start_pos_local.x()
                dy = event.pos().y() - self._drag_start_pos_local.y()
                side_length = min(abs(dx), abs(dy))

                current_pixel_x = self._drag_start_pos_local.x()
                if dx < 0:
                    current_pixel_x = self._drag_start_pos_local.x() - side_length

                current_pixel_y = self._drag_start_pos_local.y()
                if dy < 0:
                    current_pixel_y = self._drag_start_pos_local.y() - side_length

                self._dragging_keymap.normalized_position = QPointF(current_pixel_x / self.width(),
                                                                    current_pixel_y / self.height())
                self._dragging_keymap.normalized_size = QSizeF(side_length / self.width(),
                                                               side_length / self.height())

                min_norm_size_w = 10 / self.width()
                min_norm_size_h = 10 / self.height()
                if self._dragging_keymap.normalized_size.width() < min_norm_size_w:
                    self._dragging_keymap.normalized_size.setWidth(min_norm_size_w)
                if self._dragging_keymap.normalized_size.height() < min_norm_size_h:
                    self._dragging_keymap.normalized_size.setHeight(min_norm_size_h)
            else:
                delta = event.pos() - self._drag_start_pos_local
                new_pixel_x = self._keymap_original_pixel_pos.x() + delta.x()
                new_pixel_y = self._keymap_original_pixel_pos.y() + delta.y()
                self._dragging_keymap.normalized_position = QPointF(new_pixel_x / self.width(),
                                                                    new_pixel_y / self.height())

            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.edit_mode_active:
            super().mouseReleaseEvent(event)
            return

        if event.button() == Qt.LeftButton:
            release_pos = event.pos()

            try:
                distance_moved = QPointF(release_pos - self._drag_start_pos_local).norm()
            except AttributeError:
                dx = release_pos.x() - self._drag_start_pos_local.x()
                dy = release_pos.y() - self._drag_start_pos_local.y()
                distance_moved = math.sqrt(dx * dx + dy * dy)

            if self._dragging_keymap:
                if self._creating_keymap:
                    if distance_moved < 5:
                        self.keymaps.remove(self._dragging_keymap)
                        default_pixel_diameter = 100
                        new_norm_width = default_pixel_diameter / self.width()
                        new_norm_height = default_pixel_diameter / self.height()
                        new_norm_x = (release_pos.x() - default_pixel_diameter // 2) / self.width()
                        new_norm_y = (release_pos.y() - default_pixel_diameter // 2) / self.height()
                        new_keymap = Keymap(normalized_size=(new_norm_width, new_norm_height),
                                            keycombo=[],
                                            normalized_position=(new_norm_x, new_norm_y))
                        self.keymaps.append(new_keymap)
                        self._selected_keymap_for_combo_edit = new_keymap
                    else:
                        self._selected_keymap_for_combo_edit = self._dragging_keymap
                else:
                    if distance_moved < 5:
                        self._selected_keymap_for_combo_edit = self._dragging_keymap

                self._dragging_keymap = None
                self._creating_keymap = False
                self.update()
                self.keymaps_changed.emit(self.keymaps)

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if not self.edit_mode_active:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Delete and self._selected_keymap_for_combo_edit:
            self.keymaps.remove(self._selected_keymap_for_combo_edit)
            self._selected_keymap_for_combo_edit = None
            self.update()
            self.keymaps_changed.emit(self.keymaps)
            print("Keymap deleted.")
            event.accept()
            return

        if self._selected_keymap_for_combo_edit:
            key = event.key()
            is_modifier_key = (
                    key in [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R])

            if is_modifier_key:
                self._pending_modifier_key = key
                print(f"Pending modifier: {self._get_key_text(key)}")
            else:
                new_combo = []
                if self._pending_modifier_key:
                    new_combo.append(self._pending_modifier_key)
                    self._pending_modifier_key = None
                new_combo.append(key)
                self._selected_keymap_for_combo_edit.keycombo = new_combo
                self._selected_keymap_for_combo_edit = None
                print(f"Keymap combo set to: {[self._get_key_text(k) for k in new_combo]}")
                self.update()
                self.keymaps_changed.emit(self.keymaps)

            event.accept()
        else:
            super().keyPressEvent(event)
