"""
Display 1: 4" ILI9488 - Cyberpunk Mission Control
Features Molty (space lobster mascot) and activity feed.

Uses raw spidev + RPi.GPIO instead of luma.lcd.
"""

import threading
import time
from datetime import datetime
from typing import Optional, Callable, Dict, List
from PIL import Image, ImageDraw, ImageFont

try:
    import spidev
    import RPi.GPIO as GPIO
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

import config
from spi_lock import spi_lock
from ui.cyberpunk_theme import CyberpunkTheme, COLORS
from ui.molty import Molty, MoltyState
from ui.activity_feed import ActivityFeed


class ConversationDisplay:
    """
    Manages the 4" display (ILI9488) with Molty character and activity feed.

    Layout (480x320):
    ┌─────────────┬────────────────────────────────┐
    │             │ OPENCLAW            12:34:07   │  Header 30px
    │   MOLTY     ├────────────────────────────────┤
    │  160x290    │  Activity Feed (5 entries)     │  270px
    │             │                                │
    │  State      ├────────────────────────────────┤
    │  Label      │ ▌Waiting for commands...       │  Status 20px
    └─────────────┴────────────────────────────────┘
    """

    def __init__(self, demo_mode=False):
        self.demo_mode = demo_mode
        self.spi = None
        self.lock = threading.Lock()
        self.running = False
        self.fonts = {}

        # Cyberpunk UI components
        self.theme = CyberpunkTheme()
        self.molty = Molty(sprite_dir=config.SPRITES.get("molty_dir"))
        self.activity_feed = ActivityFeed(theme=self.theme)

        # Status text
        self._status_text = "Waiting for commands..."

        # Scroll offset for activity feed (controlled by rotary encoder)
        self._scroll_offset = 0

        # Refresh rate control
        self._last_render_time = 0

        # Legacy support for messages (kept for bridge compatibility)
        self.messages = []
        self._streaming_content = ""
        self._is_streaming = False
        self._cursor_visible = True
        self._last_cursor_toggle = time.time()

        self._load_fonts()

    def _load_fonts(self):
        """Load fonts for rendering."""
        try:
            self.fonts["regular"] = ImageFont.truetype(
                config.FONTS["default_path"],
                config.FONTS["size_medium"]
            )
            self.fonts["small"] = ImageFont.truetype(
                config.FONTS["default_path"],
                config.FONTS["size_small"]
            )
            self.fonts["bold"] = ImageFont.truetype(
                config.FONTS["bold_path"],
                config.FONTS["size_medium"]
            )
            self.fonts["title"] = ImageFont.truetype(
                config.FONTS["bold_path"],
                config.FONTS["size_large"]
            )
        except (IOError, OSError):
            self.fonts["regular"] = ImageFont.load_default()
            self.fonts["small"] = ImageFont.load_default()
            self.fonts["bold"] = ImageFont.load_default()
            self.fonts["title"] = ImageFont.load_default()

    def initialize(self):
        """Initialize the display hardware."""
        if self.demo_mode and not HARDWARE_AVAILABLE:
            print("[Display1] Running in demo mode (no hardware)")
            return True

        if not HARDWARE_AVAILABLE:
            print("[Display1] ERROR: spidev/RPi.GPIO not available")
            return False

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"[Display1] Retry attempt {attempt + 1}/{max_retries}")
                    time.sleep(0.5)

                # Setup GPIO pins
                GPIO.setup(config.LARGE_DISPLAY["dc_pin"], GPIO.OUT)
                GPIO.setup(config.LARGE_DISPLAY["rst_pin"], GPIO.OUT)

                # Setup SPI
                self.spi = spidev.SpiDev()
                self.spi.open(
                    config.LARGE_DISPLAY["spi_bus"],
                    config.LARGE_DISPLAY["spi_device"]
                )
                self._restore_spi()

                # Initialize display
                self._reset()
                self._init_display()

                print(f"[Display1] Initialized: {config.LARGE_DISPLAY['width']}x{config.LARGE_DISPLAY['height']} (ILI9488 18-bit)")
                return True

            except Exception as e:
                print(f"[Display1] Initialization attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    if self.demo_mode:
                        print("[Display1] Continuing in demo mode")
                        return True
                    return False
        return False

    def _restore_spi(self):
        """Restore SPI settings (needed after touch uses same bus)."""
        if self.spi:
            self.spi.max_speed_hz = config.LARGE_DISPLAY["spi_speed_hz"]
            self.spi.mode = 0
            self.spi.no_cs = False

    def _reset(self):
        """Hardware reset the display."""
        rst_pin = config.LARGE_DISPLAY["rst_pin"]
        GPIO.output(rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        GPIO.output(rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(rst_pin, GPIO.HIGH)
        time.sleep(0.15)

    def _command(self, cmd):
        """Send command byte to display."""
        GPIO.output(config.LARGE_DISPLAY["dc_pin"], GPIO.LOW)
        self.spi.xfer([cmd])

    def _data(self, data):
        """Send data bytes to display."""
        GPIO.output(config.LARGE_DISPLAY["dc_pin"], GPIO.HIGH)
        if isinstance(data, int):
            self.spi.xfer([data])
        else:
            data = list(data) if isinstance(data, bytes) else data
            for i in range(0, len(data), 4096):
                self.spi.xfer(data[i:i + 4096])

    def _init_display(self):
        """Initialize ILI9488 display."""
        self._command(config.CMD_SWRESET)
        time.sleep(0.15)
        self._command(config.CMD_SLPOUT)
        time.sleep(0.15)
        self._command(config.CMD_COLMOD)
        self._data(0x66)  # 18-bit color
        self._command(config.CMD_MADCTL)
        self._data(0xE8)  # Landscape + BGR (flipped 180°)
        self._command(config.CMD_NORON)
        time.sleep(0.01)
        self._command(config.CMD_DISPON)
        time.sleep(0.01)

    def _set_window(self, x0, y0, x1, y1):
        """Set the drawing window."""
        self._command(config.CMD_CASET)
        self._data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._command(config.CMD_PASET)
        self._data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._command(config.CMD_RAMWR)

    def _display_image(self, img):
        """Display PIL image on the ILI9488 (18-bit color)."""
        width = config.LARGE_DISPLAY["width"]
        height = config.LARGE_DISPLAY["height"]

        if img.size != (width, height):
            img = img.resize((width, height))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        self._set_window(0, 0, width - 1, height - 1)
        pixels = img.tobytes()

        # Convert to 18-bit (mask lower 2 bits of each channel)
        data = bytearray(len(pixels))
        for i in range(len(pixels)):
            data[i] = pixels[i] & 0xFC
        self._data(bytes(data))

    # === Molty State Methods ===

    def set_molty_state(self, state):
        """
        Set Molty's current state.

        Args:
            state: MoltyState enum or string
        """
        with self.lock:
            self.molty.set_state(state)

    def get_molty_state(self):
        """Get Molty's current state."""
        return self.molty.state

    # === Activity Feed Methods ===

    def add_activity(self, type_: str, title: str, detail: str = "", status: str = "done"):
        """
        Add an activity to the feed.

        Args:
            type_: Activity type (tool, message, status, error, notification)
            title: Main title
            detail: Optional detail text
            status: Entry status (done, running, fail)
        """
        with self.lock:
            self.activity_feed.add_entry(type_, title, detail, status)

    def update_latest_activity_status(self, status: str):
        """Update the status of the most recent activity."""
        with self.lock:
            self.activity_feed.update_latest_status(status)

    def set_status_text(self, text: str):
        """Set the footer status text."""
        with self.lock:
            self._status_text = text

    def set_scroll_offset(self, offset: int):
        """Set the activity feed scroll offset.

        Args:
            offset: Number of entries to scroll back (0 = newest at top)
        """
        with self.lock:
            self._scroll_offset = max(0, offset)

    def get_scroll_offset(self) -> int:
        """Get the current scroll offset."""
        with self.lock:
            return self._scroll_offset

    # === Legacy Message Methods (for backward compatibility) ===

    def add_message(self, role, content, timestamp=None):
        """Add a message (legacy, now adds to activity feed)."""
        with self.lock:
            if timestamp is None:
                timestamp = datetime.now()
            self.messages.append({
                "role": role,
                "content": content,
                "timestamp": timestamp,
            })
            # Also add to activity feed
            type_ = "message" if role == "user" else "status"
            self.activity_feed.add_entry(type_, content[:50], role)

    def set_streaming_message(self, content: str, complete: bool = False):
        """Set streaming message (legacy support)."""
        with self.lock:
            if complete:
                if content:
                    self.activity_feed.add_entry("message", content[:50], "assistant")
                self._streaming_content = ""
                self._is_streaming = False
                self.molty.set_state(MoltyState.SUCCESS)
            else:
                self._streaming_content = content
                self._is_streaming = True
                self.molty.set_state(MoltyState.WORKING)

    def append_streaming_chunk(self, chunk: str):
        """Append streaming chunk (legacy support)."""
        with self.lock:
            self._streaming_content += chunk
            self._is_streaming = True

    def clear_streaming(self):
        """Clear streaming state."""
        with self.lock:
            self._streaming_content = ""
            self._is_streaming = False

    def clear_messages(self):
        """Clear all messages and activities."""
        with self.lock:
            self.messages = []
            self.activity_feed.clear()
            self._streaming_content = ""
            self._is_streaming = False

    # === Rendering ===

    def render(self):
        """Render the cyberpunk Mission Control display."""
        width = config.LARGE_DISPLAY["width"]
        height = config.LARGE_DISPLAY["height"]
        border = config.BEZEL_BORDER

        # Full-size black canvas (matches bezel)
        image = Image.new("RGB", (width, height), (0, 0, 0))

        # Content area inset by border
        cw = width - 2 * border
        ch = height - 2 * border
        content = Image.new("RGB", (cw, ch), COLORS["background"])
        draw = ImageDraw.Draw(content, 'RGBA')

        layout = config.CYBERPUNK_LAYOUT
        molty_panel_width = int(layout["molty_panel_width"] * cw / width)
        header_height = layout["header_height"]

        # === Header ===
        self._draw_header(draw, 0, 0, cw, header_height)

        # === Left Panel (Molty) ===
        self._draw_molty_panel(draw, content, 0, header_height, molty_panel_width, ch - header_height)

        # === Right Panel (Activity Feed) ===
        activity_x = molty_panel_width
        activity_width = cw - molty_panel_width
        activity_height = ch - header_height

        with self.lock:
            status_text = self._status_text
            scroll_offset = self._scroll_offset

        self.activity_feed.render(
            draw,
            (activity_x, header_height, activity_width, activity_height),
            status_text,
            scroll_offset=scroll_offset
        )

        # === Scanlines (apply over content) ===
        self.theme.draw_scanlines(content, spacing=3, opacity=20)

        # Paste content onto black canvas
        image.paste(content, (border, border))

        # Display the image
        if self.spi:
            with spi_lock:
                self._restore_spi()
                self._display_image(image)
        elif self.demo_mode:
            pass

        return image

    def _draw_header(self, draw, x, y, width, height):
        """Draw the header bar."""
        # Header background
        draw.rectangle([x, y, x + width, y + height], fill=COLORS["panel_bg"])

        # Title with glow
        font = self.theme.get_font("bold", "header")
        self.theme.draw_neon_text(
            draw, (x + 10, y + 6),
            "OPENCLAW",
            font,
            COLORS["neon_cyan"],
            glow_layers=1
        )

        # Timestamp (right side)
        time_str = datetime.now().strftime("%H:%M:%S")
        time_font = self.theme.get_font("mono", "medium")
        time_bbox = time_font.getbbox(time_str)
        time_width = time_bbox[2] - time_bbox[0]

        draw.text(
            (x + width - time_width - 10, y + 7),
            time_str,
            font=time_font,
            fill=COLORS["text_dim"]
        )

        # Bottom border with glow
        draw.line(
            [(x, y + height - 1), (x + width, y + height - 1)],
            fill=COLORS["neon_cyan"],
            width=1
        )

    def _draw_molty_panel(self, draw, image, x, y, width, height):
        """Draw the left panel with Molty character."""
        # Panel background
        draw.rectangle([x, y, x + width, y + height], fill=COLORS["panel_bg"])

        # Right border
        draw.line(
            [(x + width - 1, y), (x + width - 1, y + height)],
            fill=COLORS["panel_border"],
            width=1
        )

        # Molty character (centered in panel)
        molty_x = x + (width - 80) // 2
        molty_y = y + 30

        with self.lock:
            self.molty.render(image, (molty_x, molty_y))
            state_label = self.molty.get_state_label()
            state_color = self.molty.get_state_color()

        # State label below Molty
        label_font = self.theme.get_font("bold", "medium")
        label_bbox = label_font.getbbox(state_label)
        label_width = label_bbox[2] - label_bbox[0]
        label_x = x + (width - label_width) // 2
        label_y = molty_y + 90

        self.theme.draw_neon_text(
            draw, (label_x, label_y),
            state_label,
            label_font,
            state_color,
            glow_layers=1
        )

        # "MOLTY" label at bottom
        name_font = self.theme.get_font("mono", "small")
        name_bbox = name_font.getbbox("MOLTY")
        name_width = name_bbox[2] - name_bbox[0]
        name_x = x + (width - name_width) // 2
        name_y = y + height - 30

        draw.text(
            (name_x, name_y),
            "MOLTY",
            font=name_font,
            fill=COLORS["text_dim"]
        )

        # Decorative corner accents
        accent_color = COLORS["neon_cyan"]
        accent_len = 12

        # Top-left
        draw.line([(x + 5, y + 5), (x + 5 + accent_len, y + 5)], fill=accent_color, width=2)
        draw.line([(x + 5, y + 5), (x + 5, y + 5 + accent_len)], fill=accent_color, width=2)

        # Bottom-left
        draw.line([(x + 5, y + height - 5), (x + 5 + accent_len, y + height - 5)], fill=accent_color, width=2)
        draw.line([(x + 5, y + height - 5), (x + 5, y + height - 5 - accent_len)], fill=accent_color, width=2)

    # === Main Loop ===

    def run(self, get_messages_func=None, get_streaming_func=None, interval=None):
        """
        Main render loop.

        Args:
            get_messages_func: Callback to get new messages
            get_streaming_func: Callback to get current streaming message
            interval: Base render interval (auto-adjusts for streaming)
        """
        self.running = True
        print("[Display1] Starting render loop")

        normal_interval = (config.STREAMING.get("normal_refresh_interval_ms", 1000)) / 1000.0
        streaming_interval = (config.STREAMING.get("refresh_interval_ms", 100)) / 1000.0

        if interval:
            normal_interval = interval

        while self.running:
            try:
                # Get new messages if callback provided
                if get_messages_func:
                    new_messages = get_messages_func()
                    if new_messages:
                        for msg in new_messages:
                            self.add_message(
                                msg.get("role", "assistant"),
                                msg.get("content", ""),
                                msg.get("timestamp")
                            )

                # Get streaming message if callback provided
                if get_streaming_func:
                    streaming = get_streaming_func()
                    if streaming:
                        with self.lock:
                            self._streaming_content = streaming.content
                            self._is_streaming = not streaming.complete
                            if not streaming.complete:
                                self.molty.set_state(MoltyState.WORKING)
                    else:
                        with self.lock:
                            was_streaming = self._is_streaming
                            if was_streaming and self._streaming_content:
                                self.activity_feed.add_entry("message", self._streaming_content[:50], "assistant")
                            self._streaming_content = ""
                            self._is_streaming = False
                            if was_streaming:
                                self.molty.set_state(MoltyState.IDLE)

                self.render()

                # Adjust refresh rate based on streaming state
                with self.lock:
                    is_streaming = self._is_streaming

                if is_streaming:
                    time.sleep(streaming_interval)
                else:
                    time.sleep(normal_interval)

            except Exception as e:
                print(f"[Display1] Render error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

        print("[Display1] Render loop stopped")

    def stop(self):
        """Stop the render loop."""
        self.running = False

    def cleanup(self):
        """Clean up resources."""
        self.stop()
        if self.spi:
            try:
                self.spi.close()
            except:
                pass
        print("[Display1] Cleanup complete")
