"""
LCD Ticker for 16x2 I2C Character LCD.
Displays status and scrolling detail text.

Uses RPLCD library with PCF8574 I2C expander.
"""

import threading
import time

try:
    from RPLCD.i2c import CharLCD
    LCD_AVAILABLE = True
except ImportError:
    LCD_AVAILABLE = False

import config


class LCDTicker:
    """Handles 16x2 I2C character LCD display with scrolling text."""

    def __init__(self, demo_mode=False):
        self.demo_mode = demo_mode
        self.lcd = None
        self.running = False
        self.lock = threading.Lock()

        # Get LCD configuration
        lcd_config = config.CHARACTER_LCD
        self.i2c_address = lcd_config["i2c_address"]
        self.i2c_port = lcd_config["i2c_port"]
        self.cols = lcd_config["cols"]
        self.rows = lcd_config["rows"]
        self.scroll_delay = lcd_config["scroll_delay"]

        # Display content
        self._state_text = "IDLE"
        self._detail_text = ""
        self._scroll_position = 0

        # Mode flash state
        self._flash_mode = None
        self._flash_until = 0

        self._initialized = False

    def initialize(self):
        """Initialize the I2C LCD."""
        if self.demo_mode:
            print("[LCD] Running in demo mode")
            self._initialized = True
            return True

        if not LCD_AVAILABLE:
            print("[LCD] ERROR: RPLCD not available (pip install RPLCD smbus2)")
            return False

        try:
            self.lcd = CharLCD(
                i2c_expander='PCF8574',
                address=self.i2c_address,
                port=self.i2c_port,
                cols=self.cols,
                rows=self.rows,
                dotsize=8,
                charmap='A02',
                auto_linebreaks=True,
                backlight_enabled=True
            )

            # Clear and show initial state
            self.lcd.clear()
            self._update_display()

            self._initialized = True
            print(f"[LCD] Initialized (address=0x{self.i2c_address:02X}, port={self.i2c_port})")
            return True

        except Exception as e:
            print(f"[LCD] Initialization failed: {e}")
            return False

    def show(self, line1, line2=""):
        """Display two lines of text.

        Args:
            line1: First line text (truncated to 16 chars)
            line2: Second line text (truncated to 16 chars)
        """
        with self.lock:
            self._state_text = line1[:self.cols]
            self._detail_text = line2[:self.cols] if len(line2) <= self.cols else line2
            self._scroll_position = 0

        if self._initialized and not self.demo_mode:
            self._update_display()

    def set_state(self, state_text):
        """Update line 1 with current state.

        Args:
            state_text: State text to display
        """
        with self.lock:
            self._state_text = state_text[:self.cols]

    def set_detail(self, detail_text):
        """Set scrolling text for line 2.

        Args:
            detail_text: Detail text (will scroll if > 16 chars)
        """
        with self.lock:
            self._detail_text = detail_text
            self._scroll_position = 0

    def show_mode_briefly(self, mode_name, duration=1.5):
        """Flash a mode name on the display.

        Args:
            mode_name: Mode name to display
            duration: How long to show it (seconds)
        """
        with self.lock:
            self._flash_mode = mode_name[:self.cols]
            self._flash_until = time.time() + duration

    def _update_display(self):
        """Update the physical LCD display."""
        if not self._initialized or self.demo_mode or not self.lcd:
            return

        try:
            with self.lock:
                # Check if we're flashing a mode
                if self._flash_mode and time.time() < self._flash_until:
                    line1 = self._flash_mode.center(self.cols)
                    line2 = "MODE CHANGED".center(self.cols)
                else:
                    self._flash_mode = None
                    line1 = self._state_text.ljust(self.cols)

                    # Handle scrolling for line 2
                    if len(self._detail_text) <= self.cols:
                        line2 = self._detail_text.ljust(self.cols)
                    else:
                        # Scroll the text
                        scroll_text = self._detail_text + "   "  # Add padding
                        start = self._scroll_position % len(scroll_text)
                        line2 = (scroll_text[start:] + scroll_text[:start])[:self.cols]

            # Write to LCD
            self.lcd.cursor_pos = (0, 0)
            self.lcd.write_string(line1)
            self.lcd.cursor_pos = (1, 0)
            self.lcd.write_string(line2)

        except Exception as e:
            print(f"[LCD] Update error: {e}")

    def _demo_print(self):
        """Print LCD state to console in demo mode."""
        with self.lock:
            if self._flash_mode and time.time() < self._flash_until:
                line1 = self._flash_mode.center(self.cols)
                line2 = "MODE CHANGED".center(self.cols)
            else:
                line1 = self._state_text.ljust(self.cols)
                if len(self._detail_text) <= self.cols:
                    line2 = self._detail_text.ljust(self.cols)
                else:
                    scroll_text = self._detail_text + "   "
                    start = self._scroll_position % len(scroll_text)
                    line2 = (scroll_text[start:] + scroll_text[:start])[:self.cols]

        print(f"[LCD] +{'-' * self.cols}+")
        print(f"[LCD] |{line1}|")
        print(f"[LCD] |{line2}|")
        print(f"[LCD] +{'-' * self.cols}+")

    def run(self):
        """Main loop for scrolling animation."""
        self.running = True
        print("[LCD] Starting LCD ticker")

        last_scroll_time = time.time()
        last_demo_print = 0

        while self.running:
            current_time = time.time()

            # Update scroll position
            if current_time - last_scroll_time >= self.scroll_delay:
                with self.lock:
                    if len(self._detail_text) > self.cols:
                        self._scroll_position += 1

                last_scroll_time = current_time

                # Update display
                if self._initialized:
                    if self.demo_mode:
                        # In demo mode, only print occasionally
                        if current_time - last_demo_print >= 2.0:
                            self._demo_print()
                            last_demo_print = current_time
                    else:
                        self._update_display()

            time.sleep(0.05)  # Small sleep to prevent busy-waiting

        print("[LCD] LCD ticker stopped")

    def stop(self):
        """Stop the LCD ticker."""
        self.running = False

    def cleanup(self):
        """Clean up resources."""
        self.stop()

        if self.lcd and not self.demo_mode:
            try:
                self.lcd.clear()
                self.lcd.backlight_enabled = False
                self.lcd.close()
            except Exception as e:
                print(f"[LCD] Cleanup warning: {e}")

        self._initialized = False
        print("[LCD] Cleanup complete")
