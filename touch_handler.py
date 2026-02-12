"""
Touch Handler for XPT2046 Touch Controller
Handles touch input on the 2.8" status display.

Uses RPi.GPIO for CS control (not lgpio) to avoid SPI corruption.
Uses polling mode since IRQ pin may not be connected.
"""

import threading
import time

try:
    import spidev
    import RPi.GPIO as GPIO
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

import config
from spi_lock import spi_lock


class TouchHandler:
    """Handles XPT2046 touch controller input using polling mode."""

    # XPT2046 commands
    CMD_X_POSITION = 0xD0  # X position command
    CMD_Y_POSITION = 0x90  # Y position command
    CMD_Z_POSITION = 0xB0  # Z (pressure) command

    def __init__(self, demo_mode=False):
        self.demo_mode = demo_mode
        self.spi = None
        self.running = False
        self.lock = threading.Lock()

        # Callbacks
        self.on_tap_top = None      # Tap on top half
        self.on_tap_bottom = None   # Tap on bottom half
        self.on_long_press = None   # Long press anywhere

        # Touch state
        self.touch_start_time = None
        self.long_press_threshold = 1.0  # seconds
        self.debounce_ms = 100  # Debounce time in milliseconds
        self.last_touch_time = 0

    def initialize(self):
        """Initialize SPI and GPIO for touch controller."""
        if self.demo_mode:
            print("[Touch] Running in demo mode")
            return True

        if not HARDWARE_AVAILABLE:
            print("[Touch] ERROR: spidev/RPi.GPIO not available")
            return False

        try:
            # Setup CS pin via RPi.GPIO (manual chip select)
            GPIO.setup(config.TOUCH["cs_pin"], GPIO.OUT)
            GPIO.output(config.TOUCH["cs_pin"], GPIO.HIGH)  # Deselected

            # Use spidev with no_cs mode - we control CS manually via GPIO 17
            self.spi = spidev.SpiDev()
            self.spi.open(0, 0)  # Use CE0 bus but we'll ignore its CS
            self.spi.max_speed_hz = config.TOUCH["spi_speed_hz"]
            self.spi.mode = 0
            self.spi.no_cs = True  # We control CS manually

            print("[Touch] Initialized (polling mode with manual CS via GPIO 17)")
            return True

        except Exception as e:
            print(f"[Touch] Initialization failed: {e}")
            return False

    def _read_touch(self):
        """Read touch coordinates using pressure-based polling.

        Returns (x, y, z, touched) where touched is True if pressure exceeds threshold.
        """
        if not self.spi:
            return 0, 0, 0, False

        try:
            with spi_lock:
                # Select touch controller
                GPIO.output(config.TOUCH["cs_pin"], GPIO.LOW)

                # Read X, Y, Z with separate commands for reliability
                x_result = self.spi.xfer2([self.CMD_X_POSITION, 0x00, 0x00])
                y_result = self.spi.xfer2([self.CMD_Y_POSITION, 0x00, 0x00])
                z_result = self.spi.xfer2([self.CMD_Z_POSITION, 0x00, 0x00])

                # Deselect touch controller
                GPIO.output(config.TOUCH["cs_pin"], GPIO.HIGH)

            # Parse 12-bit values
            x_raw = ((x_result[1] << 8) | x_result[2]) >> 3
            y_raw = ((y_result[1] << 8) | y_result[2]) >> 3
            z_raw = ((z_result[1] << 8) | z_result[2]) >> 3

            # Check if this is a valid touch (pressure above threshold, values in range)
            touched = (z_raw > config.TOUCH["min_pressure"] and
                       100 < x_raw < 4000 and
                       100 < y_raw < 4000)

            if not touched:
                return 0, 0, 0, False

            # Apply calibration
            if config.TOUCH["swap_xy"]:
                x_raw, y_raw = y_raw, x_raw

            # Map to screen coordinates
            x_min = config.TOUCH["x_min"]
            x_max = config.TOUCH["x_max"]
            y_min = config.TOUCH["y_min"]
            y_max = config.TOUCH["y_max"]
            width = config.SMALL_DISPLAY["width"]
            height = config.SMALL_DISPLAY["height"]

            if config.TOUCH["invert_x"]:
                x = int((x_max - x_raw) / (x_max - x_min) * width)
            else:
                x = int((x_raw - x_min) / (x_max - x_min) * width)

            if config.TOUCH["invert_y"]:
                y = int((y_max - y_raw) / (y_max - y_min) * height)
            else:
                y = int((y_raw - y_min) / (y_max - y_min) * height)

            # Clamp to screen bounds
            x = max(0, min(width - 1, x))
            y = max(0, min(height - 1, y))

            return x, y, z_raw, True

        except Exception as e:
            print(f"[Touch] Read error: {e}")
            return 0, 0, 0, False

    def _handle_touch(self, x, y, duration):
        """Process a touch event based on location and duration."""
        screen_height = config.SMALL_DISPLAY["height"]

        if duration >= self.long_press_threshold:
            # Long press
            print(f"[Touch] Long press detected at ({x}, {y})")
            if self.on_long_press:
                self.on_long_press(x, y)
        elif y < screen_height // 2:
            # Top half tap
            print(f"[Touch] Top tap at ({x}, {y})")
            if self.on_tap_top:
                self.on_tap_top(x, y)
        else:
            # Bottom half tap
            print(f"[Touch] Bottom tap at ({x}, {y})")
            if self.on_tap_bottom:
                self.on_tap_bottom(x, y)

    def simulate_touch(self, region):
        """Simulate a touch event (for demo mode)."""
        if region == "top":
            print("[Touch] Simulated top tap")
            if self.on_tap_top:
                self.on_tap_top(160, 60)
        elif region == "bottom":
            print("[Touch] Simulated bottom tap")
            if self.on_tap_bottom:
                self.on_tap_bottom(160, 180)
        elif region == "long":
            print("[Touch] Simulated long press")
            if self.on_long_press:
                self.on_long_press(160, 120)

    def run(self, poll_interval=0.005):
        """Main touch polling loop.

        Uses state transition detection (not-touched -> touched) for instant response.
        """
        self.running = True
        print("[Touch] Starting touch handler (polling mode)")

        was_touched = False
        touch_x, touch_y = None, None

        while self.running:
            try:
                if self.demo_mode:
                    # In demo mode, just sleep (touches are simulated externally)
                    time.sleep(0.1)
                    continue

                current_time = time.time() * 1000  # milliseconds

                # Poll touch controller
                x, y, z, is_touching = self._read_touch()

                # Detect tap (transition from not-touched to touched)
                tap_detected = is_touching and not was_touched

                if tap_detected and (current_time - self.last_touch_time) > self.debounce_ms:
                    # Touch started
                    self.touch_start_time = time.time()
                    touch_x, touch_y = x, y
                    self.last_touch_time = current_time

                elif not is_touching and was_touched:
                    # Touch ended - process the event
                    if self.touch_start_time and touch_x is not None:
                        duration = time.time() - self.touch_start_time
                        self._handle_touch(touch_x, touch_y, duration)
                    self.touch_start_time = None
                    touch_x, touch_y = None, None

                was_touched = is_touching
                time.sleep(poll_interval)

            except Exception as e:
                print(f"[Touch] Error: {e}")
                time.sleep(0.1)

        print("[Touch] Touch handler stopped")

    def stop(self):
        """Stop the touch handler."""
        self.running = False

    def cleanup(self):
        """Clean up resources."""
        self.stop()

        if self.spi:
            try:
                self.spi.close()
            except:
                pass

        print("[Touch] Cleanup complete")
