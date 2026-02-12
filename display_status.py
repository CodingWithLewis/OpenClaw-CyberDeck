"""
Display 2: 2.8" ILI9341 - Cyberpunk Command Panel
Touch-enabled button panel for sending commands to OpenClaw.

Uses raw spidev + RPi.GPIO instead of luma.lcd.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass
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
from ui.command_panel import CommandPanel, CommandButton


@dataclass
class DisplayNotification:
    """Notification to show on the display."""
    type: str  # info, success, warning, error
    title: str
    message: str = ""
    timestamp: datetime = None
    duration: float = 2.0  # seconds
    expires_at: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.expires_at is None:
            self.expires_at = self.timestamp + timedelta(seconds=self.duration)

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at


class StatusDisplay:
    """
    Manages the 2.8" display (ILI9341) with cyberpunk command panel.

    Layout (320x240):
    ┌────────────────────────────────────┐
    │ ● model-name            $0.0012    │  Status bar 35px
    ├─────────────┬──────────────────────┤
    │   INBOX     │       BRIEF          │
    ├─────────────┼──────────────────────┤
    │   QUEUE     │       FOCUS          │
    ├─────────────┼──────────────────────┤
    │   STATUS    │       RANDOM         │
    └─────────────┴──────────────────────┘
    """

    def __init__(self, demo_mode=False):
        self.demo_mode = demo_mode
        self.spi = None
        self.status_data = {
            "connected": False,
            "task_summary": "Idle",
            "queue_count": 0,
            "api_cost": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "model": "unknown",
            "is_streaming": False,
            "uptime_start": datetime.now(),
            "last_activity": datetime.now(),
        }
        self.lock = threading.Lock()
        self.running = False
        self.fonts = {}
        self._load_fonts()

        # Cyberpunk UI components
        self.theme = CyberpunkTheme()
        self.command_panel = CommandPanel(theme=self.theme)

        # Notification system (kept for compatibility)
        self._notifications: List[DisplayNotification] = []
        self._notification_lock = threading.Lock()
        self._max_notifications = config.NOTIFICATIONS.get("max_visible", 3)

        # Status view cycling (kept for compatibility, but not used in new UI)
        self._current_view = 0
        self._view_count = 3

        # Backlight state
        self._backlight_on = True

    def _load_fonts(self):
        """Load fonts for rendering."""
        try:
            self.fonts["regular"] = ImageFont.truetype(
                config.FONTS["default_path"],
                config.FONTS["size_small"]
            )
            self.fonts["medium"] = ImageFont.truetype(
                config.FONTS["default_path"],
                config.FONTS["size_medium"]
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
            self.fonts["medium"] = ImageFont.load_default()
            self.fonts["bold"] = ImageFont.load_default()
            self.fonts["title"] = ImageFont.load_default()

    def initialize(self):
        """Initialize the display hardware."""
        if self.demo_mode and not HARDWARE_AVAILABLE:
            print("[Display2] Running in demo mode (no hardware)")
            return True

        if not HARDWARE_AVAILABLE:
            print("[Display2] ERROR: spidev/RPi.GPIO not available")
            return False

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"[Display2] Retry attempt {attempt + 1}/{max_retries}")
                    time.sleep(0.5)

                # Setup GPIO pins
                GPIO.setup(config.SMALL_DISPLAY["dc_pin"], GPIO.OUT)
                GPIO.setup(config.SMALL_DISPLAY["rst_pin"], GPIO.OUT)
                GPIO.setup(config.SMALL_DISPLAY["bl_pin"], GPIO.OUT)
                GPIO.output(config.SMALL_DISPLAY["bl_pin"], GPIO.LOW)  # Backlight OFF initially

                # Setup SPI
                self.spi = spidev.SpiDev()
                self.spi.open(
                    config.SMALL_DISPLAY["spi_bus"],
                    config.SMALL_DISPLAY["spi_device"]
                )
                self.spi.max_speed_hz = config.SMALL_DISPLAY["spi_speed_hz"]
                self.spi.mode = 0

                # Initialize display
                self._reset()
                self._init_display()

                # Turn on backlight AFTER display is initialized
                GPIO.output(config.SMALL_DISPLAY["bl_pin"], GPIO.HIGH)
                self._backlight_on = True

                print(f"[Display2] Initialized: {config.SMALL_DISPLAY['width']}x{config.SMALL_DISPLAY['height']} (ILI9341 RGB565)")
                return True

            except Exception as e:
                print(f"[Display2] Initialization attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    if self.demo_mode:
                        print("[Display2] Continuing in demo mode")
                        return True
                    return False
        return False

    def _reset(self):
        """Hardware reset the display."""
        rst_pin = config.SMALL_DISPLAY["rst_pin"]
        GPIO.output(rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        GPIO.output(rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(rst_pin, GPIO.HIGH)
        time.sleep(0.15)

    def _command(self, cmd):
        """Send command byte to display."""
        GPIO.output(config.SMALL_DISPLAY["dc_pin"], GPIO.LOW)
        self.spi.xfer([cmd])

    def _data(self, data):
        """Send data bytes to display."""
        GPIO.output(config.SMALL_DISPLAY["dc_pin"], GPIO.HIGH)
        if isinstance(data, int):
            self.spi.xfer([data])
        else:
            data = list(data) if isinstance(data, bytes) else data
            for i in range(0, len(data), 4096):
                self.spi.xfer(data[i:i + 4096])

    def _init_display(self):
        """Initialize ILI9341 display with full power control sequence."""
        self._command(config.CMD_SWRESET)
        time.sleep(0.15)
        self._command(config.CMD_SLPOUT)
        time.sleep(0.5)

        # Power control
        self._command(0xCB); self._data([0x39, 0x2C, 0x00, 0x34, 0x02])
        self._command(0xCF); self._data([0x00, 0xC1, 0x30])
        self._command(0xE8); self._data([0x85, 0x00, 0x78])
        self._command(0xEA); self._data([0x00, 0x00])
        self._command(0xED); self._data([0x64, 0x03, 0x12, 0x81])
        self._command(0xF7); self._data(0x20)
        self._command(0xC0); self._data(0x23)  # Power control VRH
        self._command(0xC1); self._data(0x10)  # Power control SAP
        self._command(0xC5); self._data([0x3E, 0x28])  # VCOM control
        self._command(0xC7); self._data(0x86)  # VCOM control 2

        self._command(config.CMD_MADCTL)
        self._data(0x40)  # MX=1, RGB
        self._command(config.CMD_COLMOD)
        self._data(0x55)  # 16-bit color (RGB565)

        self._command(0xB1); self._data([0x00, 0x18])  # Frame rate control
        self._command(0xB6); self._data([0x08, 0x82, 0x27])  # Display function control
        self._command(0xF2); self._data(0x00)  # 3Gamma function disable
        self._command(0x26); self._data(0x01)  # Gamma curve selected

        # Gamma correction
        self._command(0xE0)
        self._data([0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08, 0x4E, 0xF1,
                    0x37, 0x07, 0x10, 0x03, 0x0E, 0x09, 0x00])
        self._command(0xE1)
        self._data([0x00, 0x0E, 0x14, 0x03, 0x11, 0x07, 0x31, 0xC1,
                    0x48, 0x08, 0x0F, 0x0C, 0x31, 0x36, 0x0F])

        self._command(config.CMD_NORON)
        time.sleep(0.01)
        self._command(config.CMD_DISPON)
        time.sleep(0.1)

    def _set_window(self, x0, y0, x1, y1):
        """Set the drawing window."""
        self._command(config.CMD_CASET)
        self._data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._command(config.CMD_PASET)
        self._data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._command(config.CMD_RAMWR)

    def _display_image(self, img):
        """Display PIL image on the ILI9341 (RGB565 16-bit color)."""
        width = config.SMALL_DISPLAY["width"]
        height = config.SMALL_DISPLAY["height"]

        if img.size != (width, height):
            img = img.resize((width, height))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        self._set_window(0, 0, width - 1, height - 1)
        pixels = img.tobytes()

        # Convert to RGB565
        data = bytearray(width * height * 2)
        j = 0
        for i in range(0, len(pixels), 3):
            r, g, b = pixels[i], pixels[i+1], pixels[i+2]
            pixel = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            data[j] = pixel >> 8
            data[j+1] = pixel & 0xFF
            j += 2
        self._data(bytes(data))

    # === Status Update Methods ===

    def update_status(self, **kwargs):
        """Update status data."""
        with self.lock:
            for key, value in kwargs.items():
                if key in self.status_data:
                    self.status_data[key] = value

    # === Command Panel Methods ===

    def find_button(self, x: int, y: int) -> Optional[CommandButton]:
        """
        Find which button was tapped.

        Args:
            x: Touch X coordinate (screen space)
            y: Touch Y coordinate (screen space)

        Returns:
            CommandButton if found, None otherwise
        """
        # Transform screen coordinates to content coordinates (account for bezel border)
        bz = config.SMALL_BEZEL
        return self.command_panel.find_button(x - bz["left"], y - bz["top"])

    def set_button_state(self, button_id: str, state: str):
        """
        Set a button's visual state.

        Args:
            button_id: Button identifier
            state: New state (normal, pressed, running, success, error)
        """
        self.command_panel.set_button_state(button_id, state)

    def reset_button(self, button_id: str):
        """Reset a button to normal state."""
        self.command_panel.set_button_state(button_id, "normal")

    def reset_all_buttons(self):
        """Reset all buttons to normal state."""
        self.command_panel.reset_all_buttons()

    def get_button_command(self, button_id: str) -> Optional[str]:
        """Get the command string for a button."""
        for button in self.command_panel.buttons:
            if button.id == button_id:
                return button.command
        return None

    # === Notification Methods (kept for compatibility) ===

    def add_notification(self, type_: str, title: str, message: str = "", duration: float = None):
        """Add a notification (shown briefly, then auto-dismissed)."""
        if duration is None:
            duration = config.NOTIFICATIONS.get(f"{type_}_duration",
                       config.NOTIFICATIONS.get("default_duration", 2.0))

        notification = DisplayNotification(
            type=type_,
            title=title,
            message=message,
            duration=duration,
        )

        with self._notification_lock:
            self._notifications.append(notification)
            if len(self._notifications) > self._max_notifications * 2:
                self._notifications = self._notifications[-self._max_notifications * 2:]

    def clear_notifications(self):
        """Clear all notifications."""
        with self._notification_lock:
            self._notifications = []

    def _get_active_notifications(self) -> List[DisplayNotification]:
        """Get non-expired notifications."""
        with self._notification_lock:
            active = [n for n in self._notifications if not n.is_expired]
            self._notifications = active
            return active[:self._max_notifications]

    # === View Cycling (kept for compatibility) ===

    def cycle_view(self):
        """Cycle to next status view (not used in new UI, but kept for compatibility)."""
        self._current_view = (self._current_view + 1) % self._view_count
        print(f"[Display2] Switched to view {self._current_view}")

    # === Rendering ===

    def render(self):
        """Render the cyberpunk command panel."""
        width = config.SMALL_DISPLAY["width"]
        height = config.SMALL_DISPLAY["height"]
        bz = config.SMALL_BEZEL

        # Full-size black canvas (matches bezel)
        image = Image.new("RGB", (width, height), (0, 0, 0))

        # Content area inset by per-side borders
        cw = width - bz["left"] - bz["right"]
        ch = height - bz["top"] - bz["bottom"]
        content = Image.new("RGB", (cw, ch), COLORS["background"])

        # Get current status
        with self.lock:
            connected = self.status_data["connected"]
            model = self.status_data.get("model", "")
            cost = self.status_data.get("api_cost", 0.0)

        # Render command panel into content area
        self.command_panel.render(content, connected, model, cost)

        # Apply scanlines
        self.command_panel.apply_scanlines(content, spacing=2, opacity=15)

        # Paste content onto black canvas
        image.paste(content, (bz["left"], bz["top"]))

        # Display (use lock to prevent SPI bus contention)
        if self.spi:
            with spi_lock:
                self._display_image(image)

        return image

    # === Main Loop ===

    def run(self, get_status_func=None, get_notifications_func=None, interval=1.0):
        """Main render loop."""
        self.running = True
        print("[Display2] Starting render loop")

        while self.running:
            try:
                # Get updated status if callback provided
                if get_status_func:
                    status = get_status_func()
                    if status:
                        self.update_status(**status)

                # Get notifications if callback provided (kept for compatibility)
                if get_notifications_func:
                    notifications = get_notifications_func()
                    for notif in notifications:
                        existing_times = [n.timestamp for n in self._notifications]
                        if notif.timestamp not in existing_times:
                            self.add_notification(
                                notif.type,
                                notif.title,
                                notif.message,
                                notif.duration
                            )

                self.render()
                time.sleep(interval)

            except Exception as e:
                print(f"[Display2] Render error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

        print("[Display2] Render loop stopped")

    def stop(self):
        """Stop the render loop."""
        self.running = False

    def set_backlight(self, on: bool):
        """Control backlight."""
        self._backlight_on = on
        if HARDWARE_AVAILABLE:
            GPIO.output(config.SMALL_DISPLAY["bl_pin"], GPIO.HIGH if on else GPIO.LOW)

    def toggle_backlight(self):
        """Toggle backlight state."""
        self.set_backlight(not self._backlight_on)
        return self._backlight_on

    def cleanup(self):
        """Clean up resources."""
        self.stop()
        if self.spi:
            try:
                self.spi.close()
            except:
                pass
        print("[Display2] Cleanup complete")
