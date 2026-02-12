"""
Molty - The Space Lobster Mascot
Character state machine with Pillow-generated fallback sprites.
"""

from enum import Enum
from pathlib import Path
from PIL import Image, ImageDraw
import os

from .cyberpunk_theme import COLORS


class MoltyState(Enum):
    """States for Molty character."""
    IDLE = "idle"
    LISTENING = "listening"
    WORKING = "working"
    SUCCESS = "success"
    ERROR = "error"
    THINKING = "thinking"


# State labels and colors
STATE_INFO = {
    MoltyState.IDLE: {
        "label": "Ready",
        "color": COLORS["neon_cyan"],
        "body_color": COLORS["neon_cyan"],
        "claw_color": COLORS["hot_pink"],
        "eye_color": COLORS["electric_purple"],
    },
    MoltyState.LISTENING: {
        "label": "Listening...",
        "color": COLORS["electric_purple"],
        "body_color": COLORS["electric_purple"],
        "claw_color": COLORS["neon_cyan"],
        "eye_color": COLORS["hot_pink"],
    },
    MoltyState.WORKING: {
        "label": "Working...",
        "color": COLORS["amber"],
        "body_color": COLORS["amber"],
        "claw_color": COLORS["hot_pink"],
        "eye_color": COLORS["neon_cyan"],
    },
    MoltyState.SUCCESS: {
        "label": "Done!",
        "color": COLORS["neon_green"],
        "body_color": COLORS["neon_green"],
        "claw_color": COLORS["neon_cyan"],
        "eye_color": COLORS["hot_pink"],
    },
    MoltyState.ERROR: {
        "label": "Error!",
        "color": COLORS["neon_red"],
        "body_color": COLORS["neon_red"],
        "claw_color": COLORS["amber"],
        "eye_color": COLORS["electric_purple"],
    },
    MoltyState.THINKING: {
        "label": "Thinking...",
        "color": COLORS["hot_pink"],
        "body_color": COLORS["hot_pink"],
        "claw_color": COLORS["neon_cyan"],
        "eye_color": COLORS["electric_purple"],
    },
}


class Molty:
    """
    Space Lobster mascot character with state-based sprites.
    Uses Pillow to generate fallback sprites if PNGs are not available.
    """

    SPRITE_SIZE = (80, 80)

    def __init__(self, sprite_dir=None):
        """
        Initialize Molty with optional sprite directory.

        Args:
            sprite_dir: Path to sprite PNG files (optional)
        """
        self.sprite_dir = Path(sprite_dir) if sprite_dir else None
        self.state = MoltyState.IDLE
        self.sprites = {}
        self._load_sprites()

    def _load_sprites(self):
        """Load or generate sprites for all states."""
        for state in MoltyState:
            sprite = None

            # Try to load PNG sprite
            if self.sprite_dir:
                sprite_path = self.sprite_dir / f"molty_{state.value}.png"
                if sprite_path.exists():
                    try:
                        sprite = Image.open(sprite_path).convert('RGBA')
                        sprite = sprite.resize(self.SPRITE_SIZE, Image.Resampling.LANCZOS)
                    except Exception as e:
                        print(f"[Molty] Failed to load sprite {sprite_path}: {e}")

            # Generate fallback sprite if no PNG
            if sprite is None:
                sprite = self._generate_fallback_sprite(state)

            self.sprites[state] = sprite

    def _generate_fallback_sprite(self, state):
        """
        Generate a Pillow-drawn lobster sprite for the given state.

        Args:
            state: MoltyState enum value

        Returns:
            PIL Image (RGBA, 80x80)
        """
        width, height = self.SPRITE_SIZE
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        info = STATE_INFO[state]
        body_color = info["body_color"]
        claw_color = info["claw_color"]
        eye_color = info["eye_color"]

        # Offset for animation based on state
        y_offset = 0
        claw_spread = 0
        if state == MoltyState.WORKING:
            y_offset = -2  # Bouncing up
            claw_spread = 5
        elif state == MoltyState.SUCCESS:
            y_offset = -4  # Jump up
            claw_spread = 10  # Claws up!
        elif state == MoltyState.ERROR:
            y_offset = 2  # Sink down
            claw_spread = -5  # Claws droop
        elif state == MoltyState.LISTENING:
            claw_spread = 3
        elif state == MoltyState.THINKING:
            y_offset = -1
            claw_spread = 2

        cx = width // 2  # Center X
        base_y = height // 2 + 5 + y_offset  # Body center Y

        # === TAIL (segmented) ===
        tail_segments = 4
        for i in range(tail_segments):
            seg_y = base_y + 12 + i * 6
            seg_width = 16 - i * 2
            draw.ellipse(
                [cx - seg_width//2, seg_y - 3, cx + seg_width//2, seg_y + 3],
                fill=body_color,
                outline=self._darken(body_color)
            )

        # === BODY (main ellipse) ===
        body_width = 36
        body_height = 28
        body_top = base_y - body_height // 2
        body_left = cx - body_width // 2

        # Outer glow for body
        for glow in range(2, 0, -1):
            glow_alpha = 40 * glow
            draw.ellipse(
                [body_left - glow, body_top - glow,
                 body_left + body_width + glow, body_top + body_height + glow],
                fill=(*body_color[:3], glow_alpha)
            )

        # Main body
        draw.ellipse(
            [body_left, body_top, body_left + body_width, body_top + body_height],
            fill=body_color,
            outline=self._darken(body_color),
            width=2
        )

        # === CLAWS ===
        claw_base_y = base_y - 5
        claw_size = 14

        # Left claw
        left_claw_x = cx - 28 - claw_spread
        left_claw_y = claw_base_y - claw_spread // 2
        self._draw_claw(draw, left_claw_x, left_claw_y, claw_size, claw_color, flip=False)

        # Right claw
        right_claw_x = cx + 28 + claw_spread
        right_claw_y = claw_base_y - claw_spread // 2
        self._draw_claw(draw, right_claw_x, right_claw_y, claw_size, claw_color, flip=True)

        # === ARMS connecting to claws ===
        arm_color = self._darken(body_color)
        # Left arm
        draw.line(
            [body_left + 5, base_y - 5, left_claw_x + claw_size//2, left_claw_y + claw_size//2],
            fill=arm_color, width=3
        )
        # Right arm
        draw.line(
            [body_left + body_width - 5, base_y - 5, right_claw_x - claw_size//2, right_claw_y + claw_size//2],
            fill=arm_color, width=3
        )

        # === LEGS ===
        leg_color = self._darken(body_color)
        for i, offset in enumerate([-12, -4, 4, 12]):
            leg_x = cx + offset
            leg_y_start = base_y + 8
            leg_y_end = base_y + 18 + abs(offset) // 3
            draw.line(
                [leg_x, leg_y_start, leg_x + (offset // 2), leg_y_end],
                fill=leg_color, width=2
            )

        # === EYES ===
        eye_spacing = 10
        eye_y = base_y - 8

        # Eye stalks
        for dx in [-eye_spacing, eye_spacing]:
            stalk_x = cx + dx
            draw.line(
                [stalk_x, base_y - 5, stalk_x, eye_y - 5],
                fill=body_color, width=3
            )

        # Eye outer glow
        eye_size = 6
        for dx in [-eye_spacing, eye_spacing]:
            eye_x = cx + dx
            for glow in range(2, 0, -1):
                draw.ellipse(
                    [eye_x - eye_size//2 - glow, eye_y - eye_size//2 - glow - 5,
                     eye_x + eye_size//2 + glow, eye_y + eye_size//2 + glow - 5],
                    fill=(*eye_color[:3], 60 * glow)
                )

        # Eye balls
        for dx in [-eye_spacing, eye_spacing]:
            eye_x = cx + dx
            # White of eye
            draw.ellipse(
                [eye_x - eye_size//2, eye_y - eye_size//2 - 5,
                 eye_x + eye_size//2, eye_y + eye_size//2 - 5],
                fill=(255, 255, 255),
                outline=eye_color
            )
            # Pupil
            pupil_size = 3
            draw.ellipse(
                [eye_x - pupil_size//2, eye_y - pupil_size//2 - 5,
                 eye_x + pupil_size//2, eye_y + pupil_size//2 - 5],
                fill=(0, 0, 0)
            )

        # === ANTENNAE ===
        antenna_color = claw_color
        for dx, curve in [(-8, -3), (8, 3)]:
            start_x = cx + dx
            start_y = base_y - 12
            end_x = cx + dx * 2 + curve
            end_y = base_y - 25

            # Draw curved antenna (simplified as line)
            draw.line(
                [start_x, start_y, end_x, end_y],
                fill=antenna_color, width=2
            )
            # Antenna tip
            draw.ellipse(
                [end_x - 2, end_y - 2, end_x + 2, end_y + 2],
                fill=antenna_color
            )

        return image

    def _draw_claw(self, draw, x, y, size, color, flip=False):
        """Draw a single claw."""
        # Claw glow
        for glow in range(2, 0, -1):
            draw.ellipse(
                [x - size//2 - glow, y - size//2 - glow,
                 x + size//2 + glow, y + size//2 + glow],
                fill=(*color[:3], 50 * glow)
            )

        # Main claw body (circle)
        draw.ellipse(
            [x - size//2, y - size//2, x + size//2, y + size//2],
            fill=color,
            outline=self._darken(color),
            width=2
        )

        # Claw pincer lines
        if flip:
            # Right claw - pincer opens left
            draw.arc(
                [x - size//2 - 4, y - size//3, x + size//4, y + size//3],
                start=160, end=200,
                fill=self._darken(color), width=2
            )
        else:
            # Left claw - pincer opens right
            draw.arc(
                [x - size//4, y - size//3, x + size//2 + 4, y + size//3],
                start=-20, end=20,
                fill=self._darken(color), width=2
            )

    def _darken(self, color, factor=0.6):
        """Darken a color by a factor."""
        if len(color) == 4:
            return (int(color[0] * factor), int(color[1] * factor),
                    int(color[2] * factor), color[3])
        return (int(color[0] * factor), int(color[1] * factor),
                int(color[2] * factor))

    def set_state(self, state):
        """
        Set Molty's current state.

        Args:
            state: MoltyState enum value or string
        """
        if isinstance(state, str):
            state = MoltyState(state)
        self.state = state

    def get_state_label(self):
        """Get the display label for current state."""
        return STATE_INFO[self.state]["label"]

    def get_state_color(self):
        """Get the primary color for current state."""
        return STATE_INFO[self.state]["color"]

    def render(self, target_image, position):
        """
        Render Molty onto a target image.

        Args:
            target_image: PIL Image to paste onto
            position: (x, y) top-left position
        """
        sprite = self.sprites[self.state]
        target_image.paste(sprite, position, sprite)

    def get_sprite(self):
        """Get the current state's sprite image."""
        return self.sprites[self.state]
