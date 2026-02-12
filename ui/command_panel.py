"""
Command Panel for the small display.
Touch-enabled cyberpunk button grid for sending commands to OpenClaw.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Callable
from datetime import datetime
import time
from PIL import Image, ImageDraw

from .cyberpunk_theme import COLORS, CyberpunkTheme


@dataclass
class CommandButton:
    """A single command button."""
    id: str
    label: str
    command: str       # Command/message to send
    x: int
    y: int
    width: int = 150
    height: int = 62
    state: str = "normal"  # normal, pressed, running, success, error


# Button definitions (2x3 grid)
# Layout: 320x240 display
# Status bar: 35px at top
# Footer: 0px (no footer needed, buttons extend to bottom)
# Button area: 240 - 35 = 205px height
# 3 rows of buttons: ~68px each, with ~4px spacing
# 2 columns: ~157px each, with ~6px spacing
DEFAULT_BUTTONS = [
    CommandButton(
        id="inbox",
        label="INBOX",
        command="Check inbox and summarize urgent items",
        x=5, y=40, width=152, height=62
    ),
    CommandButton(
        id="brief",
        label="BRIEF",
        command="Give me a briefing of my day",
        x=163, y=40, width=152, height=62
    ),
    CommandButton(
        id="queue",
        label="QUEUE",
        command="Execute next queued automation",
        x=5, y=107, width=152, height=62
    ),
    CommandButton(
        id="focus",
        label="FOCUS",
        command="Activate focus mode",
        x=163, y=107, width=152, height=62
    ),
    CommandButton(
        id="status",
        label="STATUS",
        command="Report your current status",
        x=5, y=174, width=152, height=62
    ),
    CommandButton(
        id="random",
        label="RANDOM",
        command="Do something useful",
        x=163, y=174, width=152, height=62
    ),
]

# Button state colors
STATE_COLORS = {
    "normal": {
        "bg": COLORS["button_normal"],
        "border": COLORS["neon_cyan"],
        "text": COLORS["text_primary"],
        "glow": False,
    },
    "pressed": {
        "bg": (40, 0, 25),
        "border": COLORS["hot_pink"],
        "text": COLORS["hot_pink"],
        "glow": True,
    },
    "running": {
        "bg": (30, 25, 0),
        "border": COLORS["amber"],
        "text": COLORS["amber"],
        "glow": True,
    },
    "success": {
        "bg": (0, 30, 15),
        "border": COLORS["neon_green"],
        "text": COLORS["neon_green"],
        "glow": True,
    },
    "error": {
        "bg": (30, 0, 0),
        "border": COLORS["neon_red"],
        "text": COLORS["neon_red"],
        "glow": True,
    },
}


class CommandPanel:
    """
    Touch command panel for the small display.
    Renders cyberpunk-styled buttons with state feedback.
    """

    def __init__(self, theme: CyberpunkTheme = None, buttons: List[CommandButton] = None):
        """
        Initialize the command panel.

        Args:
            theme: CyberpunkTheme instance
            buttons: List of CommandButton objects (uses defaults if None)
        """
        self.theme = theme or CyberpunkTheme()
        self.buttons = buttons or [
            CommandButton(**{k: v for k, v in btn.__dict__.items()})
            for btn in DEFAULT_BUTTONS
        ]
        self._button_flash_times = {}  # Track when buttons were pressed for flash timing
        self._last_layout_size = None  # Track last layout size to avoid redundant recalc

    def layout_buttons(self, width: int, height: int):
        """Recalculate button positions for the given content dimensions."""
        size = (width, height)
        if self._last_layout_size == size:
            return
        self._last_layout_size = size

        status_bar_h = 35
        padding = 5
        gap = 5
        cols = 2
        rows = 3

        button_area_y = status_bar_h + 2
        button_area_h = height - button_area_y - padding
        button_area_w = width - 2 * padding

        btn_w = (button_area_w - (cols - 1) * gap) // cols
        btn_h = (button_area_h - (rows - 1) * gap) // rows

        for i, button in enumerate(self.buttons):
            col = i % cols
            row = i // cols
            button.x = padding + col * (btn_w + gap)
            button.y = button_area_y + row * (btn_h + gap)
            button.width = btn_w
            button.height = btn_h

    def find_button(self, x: int, y: int) -> Optional[CommandButton]:
        """
        Find which button contains the given coordinates.

        Args:
            x: Touch X coordinate
            y: Touch Y coordinate

        Returns:
            CommandButton if found, None otherwise
        """
        for button in self.buttons:
            if (button.x <= x <= button.x + button.width and
                button.y <= y <= button.y + button.height):
                return button
        return None

    def set_button_state(self, button_id: str, state: str):
        """
        Update a button's visual state.

        Args:
            button_id: Button identifier
            state: New state (normal, pressed, running, success, error)
        """
        for button in self.buttons:
            if button.id == button_id:
                button.state = state
                if state in ("pressed", "success", "error"):
                    self._button_flash_times[button_id] = time.time()
                break

    def update_flash_states(self):
        """
        Auto-reset buttons that have been in flash states too long.
        Called during render to manage button state timing.
        """
        current_time = time.time()
        flash_duration = 0.15  # 150ms flash

        for button in self.buttons:
            if button.state == "pressed":
                flash_time = self._button_flash_times.get(button.id, 0)
                if current_time - flash_time > flash_duration:
                    # Don't auto-reset pressed to normal (let running state take over)
                    pass
            elif button.state in ("success", "error"):
                flash_time = self._button_flash_times.get(button.id, 0)
                if current_time - flash_time > 1.0:  # 1 second for success/error
                    button.state = "normal"

    def reset_all_buttons(self):
        """Reset all buttons to normal state."""
        for button in self.buttons:
            button.state = "normal"
        self._button_flash_times.clear()

    def render(self, image: Image.Image, connected: bool, model: str = "",
               cost: float = 0.0) -> Image.Image:
        """
        Render the command panel onto an image.

        Args:
            image: PIL Image to draw on
            connected: Whether connected to OpenClaw
            model: Current model name
            cost: Current API cost

        Returns:
            The modified image
        """
        draw = ImageDraw.Draw(image, 'RGBA')
        width, height = image.size

        # Recalculate button layout for current content size
        self.layout_buttons(width, height)

        # Update flash states
        self.update_flash_states()

        # Background
        draw.rectangle([0, 0, width, height], fill=COLORS["background"])

        # Status bar at top
        self._draw_status_bar(draw, 0, 0, width, 35, connected, model, cost)

        # Draw all buttons
        for button in self.buttons:
            self._draw_button(draw, button)

        return image

    def _draw_status_bar(self, draw: ImageDraw.Draw, x: int, y: int,
                         width: int, height: int, connected: bool,
                         model: str, cost: float):
        """Draw the status bar at top of panel."""
        # Status bar background
        draw.rectangle(
            [x, y, x + width, y + height],
            fill=COLORS["panel_bg"]
        )

        # Connection indicator dot
        dot_color = COLORS["neon_green"] if connected else COLORS["neon_red"]
        dot_x = x + 12
        dot_y = y + height // 2

        # Glow
        draw.ellipse(
            [dot_x - 6, dot_y - 6, dot_x + 6, dot_y + 6],
            fill=(*dot_color[:3], 60)
        )
        draw.ellipse(
            [dot_x - 4, dot_y - 4, dot_x + 4, dot_y + 4],
            fill=dot_color
        )

        # Model name (truncated)
        model_font = self.theme.get_font("mono", "small")
        if model:
            model_text = model[:15] + "..." if len(model) > 15 else model
        else:
            model_text = "---"

        draw.text(
            (dot_x + 14, y + 10),
            model_text,
            font=model_font,
            fill=COLORS["text_primary"] if connected else COLORS["text_dim"]
        )

        # API cost (right side)
        cost_text = f"${cost:.4f}"
        cost_font = self.theme.get_font("mono", "small")
        cost_bbox = cost_font.getbbox(cost_text)
        cost_width = cost_bbox[2] - cost_bbox[0]

        cost_color = COLORS["neon_red"] if cost > 1.0 else COLORS["neon_green"]
        draw.text(
            (x + width - cost_width - 10, y + 10),
            cost_text,
            font=cost_font,
            fill=cost_color
        )

        # Bottom border
        draw.line(
            [(x, y + height - 1), (x + width, y + height - 1)],
            fill=COLORS["neon_cyan"],
            width=1
        )

    def _draw_button(self, draw: ImageDraw.Draw, button: CommandButton):
        """Draw a single button."""
        state_style = STATE_COLORS.get(button.state, STATE_COLORS["normal"])

        x1, y1 = button.x, button.y
        x2, y2 = button.x + button.width, button.y + button.height

        # Button background
        draw.rectangle([x1, y1, x2, y2], fill=state_style["bg"])

        # Glow effect for active states
        if state_style["glow"]:
            border_color = state_style["border"]
            # Outer glow
            for glow_offset in range(3, 0, -1):
                glow_alpha = 30 * glow_offset
                draw.rectangle(
                    [x1 - glow_offset, y1 - glow_offset,
                     x2 + glow_offset, y2 + glow_offset],
                    outline=(*border_color[:3], glow_alpha),
                    width=1
                )

        # Border
        draw.rectangle(
            [x1, y1, x2, y2],
            outline=state_style["border"],
            width=2
        )

        # Corner accents
        accent_len = 6
        accent_color = state_style["border"]
        # Top-left
        draw.line([(x1, y1), (x1 + accent_len, y1)], fill=accent_color, width=3)
        draw.line([(x1, y1), (x1, y1 + accent_len)], fill=accent_color, width=3)
        # Top-right
        draw.line([(x2 - accent_len, y1), (x2, y1)], fill=accent_color, width=3)
        draw.line([(x2, y1), (x2, y1 + accent_len)], fill=accent_color, width=3)
        # Bottom-left
        draw.line([(x1, y2 - accent_len), (x1, y2)], fill=accent_color, width=3)
        draw.line([(x1, y2), (x1 + accent_len, y2)], fill=accent_color, width=3)
        # Bottom-right
        draw.line([(x2 - accent_len, y2), (x2, y2)], fill=accent_color, width=3)
        draw.line([(x2, y2 - accent_len), (x2, y2)], fill=accent_color, width=3)

        # Button label (centered)
        font = self.theme.get_font("bold", "medium")
        label_bbox = font.getbbox(button.label)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]

        label_x = x1 + (button.width - label_width) // 2
        label_y = y1 + (button.height - label_height) // 2 - 2

        draw.text(
            (label_x, label_y),
            button.label,
            font=font,
            fill=state_style["text"]
        )

        # Running state gets animated dots
        if button.state == "running":
            dots = "..." [:int(time.time() * 3) % 4]
            dot_font = self.theme.get_font("mono", "small")
            dot_y = y2 - 16
            draw.text(
                (label_x + label_width + 4, label_y),
                dots,
                font=dot_font,
                fill=state_style["text"]
            )

    def apply_scanlines(self, image: Image.Image, spacing: int = 2,
                        opacity: int = 20) -> Image.Image:
        """
        Apply scanline effect to the rendered image.

        Args:
            image: PIL Image
            spacing: Pixels between scanlines
            opacity: Scanline darkness (0-255)

        Returns:
            Image with scanlines
        """
        draw = ImageDraw.Draw(image, 'RGBA')
        width, height = image.size

        for y in range(0, height, spacing):
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, opacity))

        return image
