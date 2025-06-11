from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QRectF, QRect, QPoint


class OverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Essential for transparent background
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Set window flags to ensure it stays on top and is fully visible
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool  # Tool windows are shown on top of the application
        )

        # Set focus policy to allow keyboard events
        self.setFocusPolicy(Qt.StrongFocus)

        # Make sure the widget is visible
        self.setVisible(True)
        self.raise_()  # Ensure this widget is on top

        # We'll explicitly call raise_() from the parent to ensure z-order

    def showEvent(self, event):
        """Called when the widget is shown"""
        print(f"Overlay widget shown: size={self.size()}, geometry={self.geometry()}")
        super().showEvent(event)
        self.raise_()

    def ensure_on_top(self):
        """Ensures the overlay is on top of all other windows"""
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event):
        # Get the ScrcpyIntegratedApp instance (parent)
        main_app = self.parent()
        if not main_app:
            print("No parent app found")
            return

        # Access DRAWING_PRIMITIVES and other variables from the main app
        if not hasattr(main_app, 'DRAWING_PRIMITIVES') or not hasattr(main_app, 'scrcpy_container'):
            print("Missing required attributes in parent app")
            return

        # Check if required attributes exist
        if not main_app.scrcpy_container or not main_app.scrcpy_container.isVisible():
            print("Scrcpy container not visible or not initialized")
            return

        # Debug information
        print(f"Overlay paintEvent - size: {self.width()}x{self.height()}, visible: {self.isVisible()}, geometry: {self.geometry()}")

        # Create a painter for the overlay
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # For smoother circles
        painter.setRenderHint(QPainter.TextAntialiasing)  # For high quality text

        # Create a transparent background with just a border for debugging
        border_pen = QPen(QColor(255, 0, 0, 180), 2)  # Red border
        painter.setPen(border_pen)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        # Draw an indicator text to make it obvious when the overlay is visible
        painter.setPen(QPen(QColor(255, 255, 255, 220)))
        painter.setFont(painter.font())
        painter.drawText(10, 20, "Overlay active")

        # Calculate the container rect relative to the overlay
        container_rect = QRect(QPoint(0, 0), self.size())

        # Debug output if needed
        # print(f"Overlay rect: {self.geometry().x()}, {self.geometry().y()}, {self.width()}x{self.height()}")

        # Draw edit mode overlay
        if main_app.edit_mode_active:
            # Semi-transparent overlay to indicate edit mode
            painter.fillRect(container_rect, QColor(50, 50, 50, 40))

            # Draw guide grid
            grid_color = QColor(200, 200, 200, 80)  # More visible grid
            painter.setPen(QPen(grid_color, 1, Qt.DashLine))

            # Calculate scale factors
            scale_factor_x = container_rect.width() / main_app.device_width
            scale_factor_y = container_rect.height() / main_app.device_height
            actual_scale = min(scale_factor_x, scale_factor_y)

            # Calculate content area size and offset
            scaled_content_width = main_app.device_width * actual_scale
            scaled_content_height = main_app.device_height * actual_scale
            offset_x = container_rect.x() + (container_rect.width() - scaled_content_width) / 2
            offset_y = container_rect.y() + (container_rect.height() - scaled_content_height) / 2

            # Draw horizontal grid lines
            for y in range(0, main_app.device_height + 1, 100):
                scaled_y = offset_y + y * actual_scale
                painter.drawLine(
                    int(offset_x), int(scaled_y),
                    int(offset_x + scaled_content_width), int(scaled_y)
                )

            # Draw vertical grid lines
            for x in range(0, main_app.device_width + 1, 100):
                scaled_x = offset_x + x * actual_scale
                painter.drawLine(
                    int(scaled_x), int(offset_y),
                    int(scaled_x), int(offset_y + scaled_content_height)
                )

        # Draw all primitives
        # Calculate scale factors
        container_width = container_rect.width()
        container_height = container_rect.height()

        scale_factor_x = container_width / main_app.device_width
        scale_factor_y = container_height / main_app.device_height
        actual_scale = min(scale_factor_x, scale_factor_y)

        # Calculate content area size and offset
        scaled_content_width = main_app.device_width * actual_scale
        scaled_content_height = main_app.device_height * actual_scale
        offset_x = container_rect.x() + (container_width - scaled_content_width) / 2
        offset_y = container_rect.y() + (container_height - scaled_content_height) / 2

        # Draw all primitives from the main application
        for p_id, p_data in main_app.DRAWING_PRIMITIVES.items():
            p_type = p_data['type']
            color_rgb = p_data['color']
            opacity = p_data['opacity']
            center_x, center_y = p_data['center_coords']
            dimensions = p_data['dimensions']

            # Calculate scaled coordinates - use integer coordinates to avoid anti-aliasing artifacts
            scaled_center_x = int(offset_x + center_x * actual_scale)
            scaled_center_y = int(offset_y + center_y * actual_scale)

            # Set color with opacity
            color = QColor(color_rgb[0], color_rgb[1], color_rgb[2])
            color.setAlphaF(opacity)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)

            if p_type == 'circle':
                radius = dimensions
                scaled_radius = int(radius * actual_scale)
                # Use QPoint for integer-based drawing to avoid artifacts
                painter.drawEllipse(
                    QPoint(scaled_center_x, scaled_center_y),
                    scaled_radius, scaled_radius
                )

                # Draw key combo text if assigned
                key_combo = p_data.get('key_combo')
                if key_combo:
                    # Save current painter state
                    painter.save()

                    # Calculate appropriate font size based on circle size
                    font_size = max(int(scaled_radius * 0.4), 8)
                    font_size = min(font_size, 16)  # Limit maximum size

                    # Set up font for key combo
                    font = painter.font()
                    font.setPointSize(font_size)
                    font.setBold(True)
                    painter.setFont(font)

                    # Draw text background for better visibility
                    text_width = painter.fontMetrics().width(key_combo)
                    text_height = painter.fontMetrics().height()
                    bg_width = text_width + 10  # Add padding
                    bg_height = text_height + 6

                    # Create semi-transparent background rectangle
                    bg_rect = QRectF(
                        scaled_center_x - bg_width / 2,
                        scaled_center_y - bg_height / 2,
                        bg_width,
                        bg_height
                    )

                    # Draw rounded rectangle background
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(0, 0, 0, 180))
                    painter.drawRoundedRect(bg_rect, 4, 4)

                    # Draw text with solid white color and better contrast
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 1, Qt.SolidLine))
                    painter.drawText(bg_rect, Qt.AlignCenter, key_combo)

                    # Restore painter state
                    painter.restore()

                # Draw selection indicator for selected primitive
                if main_app.edit_mode_active and p_id == main_app.selected_primitive_id:
                    # Draw selection outline
                    select_pen = QPen(Qt.white, 2, Qt.DashLine)
                    painter.setPen(select_pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(
                        QPoint(scaled_center_x, scaled_center_y),
                        scaled_radius + 5, scaled_radius + 5
                    )

                    # Draw delete button
                    delete_x = int(scaled_center_x + scaled_radius * 0.7)
                    delete_y = int(scaled_center_y - scaled_radius * 0.7)
                    delete_button_radius = int(main_app.delete_button_size / 2)

                    # Draw red circle for delete button
                    delete_color = QColor(255, 50, 50, 230)
                    painter.setBrush(delete_color)
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(
                        QPoint(delete_x, delete_y),
                        delete_button_radius, delete_button_radius
                    )

                    # Draw X inside button
                    painter.setPen(QPen(Qt.white, 2))
                    x_size = delete_button_radius * 0.7
                    painter.drawLine(
                        int(delete_x - x_size), int(delete_y - x_size),
                        int(delete_x + x_size), int(delete_y + x_size)
                    )
                    painter.drawLine(
                        int(delete_x + x_size), int(delete_y - x_size),
                        int(delete_x - x_size), int(delete_y + x_size)
                    )

        # Draw primitive being created
        if main_app.edit_mode_active and main_app.primitive_being_created:
            p_data = main_app.primitive_being_created
            color_rgb = p_data['color']
            opacity = p_data['opacity']
            center_x, center_y = p_data['center_coords']
            dimensions = p_data['dimensions']

            # Calculate scaled coordinates with integer precision to avoid artifacts
            scaled_center_x = int(offset_x + center_x * actual_scale)
            scaled_center_y = int(offset_y + center_y * actual_scale)

            # Set color with opacity
            color = QColor(color_rgb[0], color_rgb[1], color_rgb[2])
            color.setAlphaF(opacity)
            painter.setBrush(color)

            # Draw with dashed outline
            outline_pen = QPen(QColor(255, 255, 255, 200), 2, Qt.DashLine)  # More visible outline
            outline_pen.setCosmetic(True)  # Make pen width consistent regardless of transformation
            painter.setPen(outline_pen)

            if p_data['type'] == 'circle':
                radius = dimensions
                scaled_radius = int(radius * actual_scale)
                painter.drawEllipse(
                    QPoint(scaled_center_x, scaled_center_y),
                    scaled_radius, scaled_radius
                )

                # Display radius information during creation
                text = f"R: {int(radius)}px"
                text_rect = QRectF(
                    scaled_center_x - 50,
                    scaled_center_y + scaled_radius + 10,
                    100,
                    20
                )

                # Draw text background with rounded corners
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 180))
                painter.drawRoundedRect(text_rect, 3, 3)

                # Draw text with solid white color for better visibility
                painter.setPen(QPen(QColor(255, 255, 255, 255)))
                painter.drawText(text_rect, Qt.AlignCenter, text)
