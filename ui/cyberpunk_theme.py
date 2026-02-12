"""
Cyberpunk theme for OpenClaw Dual Display Command Center.
Colors, fonts, and visual effects (glow, scanlines, glitch).
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random

# Cyberpunk color palette (RGB tuples)
COLORS = {
    "background": (10, 10, 15),         # #0a0a0f - Deep dark blue-black
    "panel_bg": (15, 15, 25),           # #0f0f19 - Slightly lighter panel
    "panel_border": (30, 30, 45),       # Border for panels

    # Primary neon colors
    "neon_cyan": (0, 255, 255),         # #00ffff - Primary accent
    "hot_pink": (255, 0, 102),          # #ff0066 - Secondary accent
    "electric_purple": (191, 0, 255),   # #bf00ff - Tertiary accent

    # Status colors
    "amber": (255, 170, 0),             # #ffaa00 - Warning/running
    "neon_green": (0, 255, 102),        # #00ff66 - Success
    "neon_red": (255, 0, 51),           # #ff0033 - Error

    # Text colors
    "text_primary": (238, 238, 255),    # #eeeeff - Main text
    "text_dim": (68, 119, 119),         # #447777 - Dimmed text
    "text_secondary": (100, 150, 150),  # Secondary text

    # Activity type colors
    "type_tool": (0, 255, 255),         # Cyan for tools
    "type_message": (255, 0, 102),      # Hot pink for messages
    "type_status": (191, 0, 255),       # Purple for status
    "type_error": (255, 0, 51),         # Red for errors
    "type_notification": (255, 170, 0), # Amber for notifications

    # Button states
    "button_normal": (20, 20, 30),      # Default button bg
    "button_border": (0, 255, 255),     # Cyan border
    "button_pressed": (255, 0, 102),    # Hot pink when pressed
    "button_running": (255, 170, 0),    # Amber when running
    "button_success": (0, 255, 102),    # Green flash on success
    "button_error": (255, 0, 51),       # Red flash on error
}

# Dimmed versions of colors (for glow outer layers)
COLORS_DIM = {
    "neon_cyan": (0, 128, 128),
    "hot_pink": (128, 0, 51),
    "electric_purple": (96, 0, 128),
    "amber": (128, 85, 0),
    "neon_green": (0, 128, 51),
    "neon_red": (128, 0, 26),
}


class CyberpunkTheme:
    """Renderer for cyberpunk visual effects."""

    def __init__(self):
        self.fonts = {}
        self._load_fonts()

    def _load_fonts(self):
        """Load fonts for cyberpunk rendering."""
        font_paths = {
            "default": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        }

        sizes = {
            "small": 11,
            "medium": 14,
            "large": 18,
            "title": 22,
            "header": 16,
        }

        try:
            for size_name, size in sizes.items():
                self.fonts[f"regular_{size_name}"] = ImageFont.truetype(
                    font_paths["default"], size
                )
                self.fonts[f"bold_{size_name}"] = ImageFont.truetype(
                    font_paths["bold"], size
                )
                self.fonts[f"mono_{size_name}"] = ImageFont.truetype(
                    font_paths["mono"], size
                )
        except (IOError, OSError):
            # Fallback to default font
            default = ImageFont.load_default()
            for size_name in sizes:
                self.fonts[f"regular_{size_name}"] = default
                self.fonts[f"bold_{size_name}"] = default
                self.fonts[f"mono_{size_name}"] = default

    def get_font(self, style="regular", size="medium"):
        """Get a font by style and size."""
        key = f"{style}_{size}"
        return self.fonts.get(key, self.fonts.get("regular_medium"))

    def draw_scanlines(self, image, spacing=2, opacity=25):
        """
        Draw horizontal scanlines over the image.

        Args:
            image: PIL Image to draw on
            spacing: Pixels between scanlines
            opacity: Scanline darkness (0-255)
        """
        draw = ImageDraw.Draw(image, 'RGBA')
        width, height = image.size

        scanline_color = (0, 0, 0, opacity)

        for y in range(0, height, spacing):
            draw.line([(0, y), (width, y)], fill=scanline_color)

        return image

    def draw_glow(self, draw, shape_type, coords, color, layers=2, base_width=1):
        """
        Draw a shape with outer glow effect.

        Args:
            draw: ImageDraw object
            shape_type: "rectangle", "ellipse", "line", or "text"
            coords: Shape coordinates
            color: Main color (RGB tuple)
            layers: Number of glow layers
            base_width: Base line width
        """
        # Get dimmed color for outer glow
        dim_color = COLORS_DIM.get(
            self._find_color_name(color),
            tuple(c // 2 for c in color)
        )

        # Draw outer glow layers (from outside in)
        for i in range(layers, 0, -1):
            alpha = int(80 / i)  # Decreasing opacity
            glow_color = (*dim_color, alpha)
            expand = i * 2

            if shape_type == "rectangle":
                x1, y1, x2, y2 = coords
                draw.rectangle(
                    [x1 - expand, y1 - expand, x2 + expand, y2 + expand],
                    outline=glow_color,
                    width=base_width + i
                )
            elif shape_type == "ellipse":
                x1, y1, x2, y2 = coords
                draw.ellipse(
                    [x1 - expand, y1 - expand, x2 + expand, y2 + expand],
                    outline=glow_color,
                    width=base_width + i
                )
            elif shape_type == "line":
                draw.line(coords, fill=glow_color, width=base_width + i * 2)

        # Draw main shape
        if shape_type == "rectangle":
            draw.rectangle(coords, outline=color, width=base_width)
        elif shape_type == "ellipse":
            draw.ellipse(coords, outline=color, width=base_width)
        elif shape_type == "line":
            draw.line(coords, fill=color, width=base_width)

    def draw_neon_text(self, draw, pos, text, font, color, glow_layers=1):
        """
        Draw text with neon glow effect.

        Args:
            draw: ImageDraw object
            pos: (x, y) position
            text: Text string
            font: PIL font
            color: Main text color
            glow_layers: Number of glow layers
        """
        x, y = pos

        # Get dimmed color for glow
        dim_color = COLORS_DIM.get(
            self._find_color_name(color),
            tuple(c // 2 for c in color)
        )

        # Draw glow layers
        for i in range(glow_layers, 0, -1):
            offset = i
            glow_alpha = int(100 / i)
            glow_color = (*dim_color[:3], glow_alpha) if len(dim_color) == 3 else dim_color

            # Draw in 4 directions for glow effect
            for dx, dy in [(-offset, 0), (offset, 0), (0, -offset), (0, offset)]:
                draw.text((x + dx, y + dy), text, font=font, fill=glow_color)

        # Draw main text
        draw.text(pos, text, font=font, fill=color)

    def draw_glitch_effect(self, image, intensity=2):
        """
        Apply RGB channel split glitch effect.

        Args:
            image: PIL Image
            intensity: Pixel offset for RGB split

        Returns:
            New image with glitch effect
        """
        if image.mode != 'RGB':
            image = image.convert('RGB')

        r, g, b = image.split()

        # Offset channels slightly
        width, height = image.size

        # Create offset versions
        r_offset = Image.new('L', (width, height), 0)
        b_offset = Image.new('L', (width, height), 0)

        # Paste with offset
        r_offset.paste(r, (intensity, 0))
        b_offset.paste(b, (-intensity, 0))

        # Merge back
        return Image.merge('RGB', (r_offset, g, b_offset))

    def draw_panel_border(self, draw, coords, color=None, width=1, corner_accent=True):
        """
        Draw a cyberpunk-style panel border with optional corner accents.

        Args:
            draw: ImageDraw object
            coords: (x1, y1, x2, y2) rectangle coordinates
            color: Border color (default: neon_cyan)
            width: Border width
            corner_accent: Add corner accent marks
        """
        if color is None:
            color = COLORS["neon_cyan"]

        x1, y1, x2, y2 = coords

        # Main border
        draw.rectangle(coords, outline=color, width=width)

        # Corner accents (small lines at corners)
        if corner_accent:
            accent_len = 8
            # Top-left
            draw.line([(x1, y1), (x1 + accent_len, y1)], fill=color, width=width + 1)
            draw.line([(x1, y1), (x1, y1 + accent_len)], fill=color, width=width + 1)
            # Top-right
            draw.line([(x2 - accent_len, y1), (x2, y1)], fill=color, width=width + 1)
            draw.line([(x2, y1), (x2, y1 + accent_len)], fill=color, width=width + 1)
            # Bottom-left
            draw.line([(x1, y2 - accent_len), (x1, y2)], fill=color, width=width + 1)
            draw.line([(x1, y2), (x1 + accent_len, y2)], fill=color, width=width + 1)
            # Bottom-right
            draw.line([(x2 - accent_len, y2), (x2, y2)], fill=color, width=width + 1)
            draw.line([(x2, y2 - accent_len), (x2, y2)], fill=color, width=width + 1)

    def draw_status_dot(self, draw, pos, color, size=10, glow=True):
        """
        Draw a glowing status indicator dot.

        Args:
            draw: ImageDraw object
            pos: (x, y) center position
            color: Dot color
            size: Dot diameter
            glow: Whether to add glow effect
        """
        x, y = pos
        radius = size // 2

        if glow:
            # Outer glow
            dim_color = COLORS_DIM.get(
                self._find_color_name(color),
                tuple(c // 2 for c in color)
            )
            draw.ellipse(
                [x - radius - 3, y - radius - 3, x + radius + 3, y + radius + 3],
                fill=(*dim_color, 60) if len(dim_color) == 3 else dim_color
            )
            draw.ellipse(
                [x - radius - 1, y - radius - 1, x + radius + 1, y + radius + 1],
                fill=(*dim_color, 100) if len(dim_color) == 3 else dim_color
            )

        # Main dot
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=color
        )

    def _find_color_name(self, color):
        """Find the name of a color in the COLORS dict."""
        for name, c in COLORS.items():
            if c == color:
                return name
        return None

    def create_gradient_bar(self, width, height, color_start, color_end, vertical=False):
        """
        Create a gradient bar image.

        Args:
            width: Bar width
            height: Bar height
            color_start: Starting color (RGB)
            color_end: Ending color (RGB)
            vertical: If True, gradient is vertical

        Returns:
            PIL Image with gradient
        """
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)

        steps = height if vertical else width

        for i in range(steps):
            ratio = i / max(steps - 1, 1)
            r = int(color_start[0] + (color_end[0] - color_start[0]) * ratio)
            g = int(color_start[1] + (color_end[1] - color_start[1]) * ratio)
            b = int(color_start[2] + (color_end[2] - color_start[2]) * ratio)

            if vertical:
                draw.line([(0, i), (width, i)], fill=(r, g, b))
            else:
                draw.line([(i, 0), (i, height)], fill=(r, g, b))

        return image

    def add_noise(self, image, amount=5):
        """
        Add subtle noise to an image for CRT effect.

        Args:
            image: PIL Image
            amount: Noise intensity (0-255)

        Returns:
            Image with noise
        """
        if image.mode != 'RGB':
            image = image.convert('RGB')

        pixels = image.load()
        width, height = image.size

        for y in range(height):
            for x in range(width):
                if random.random() < 0.1:  # Only affect 10% of pixels
                    r, g, b = pixels[x, y]
                    noise = random.randint(-amount, amount)
                    pixels[x, y] = (
                        max(0, min(255, r + noise)),
                        max(0, min(255, g + noise)),
                        max(0, min(255, b + noise))
                    )

        return image
