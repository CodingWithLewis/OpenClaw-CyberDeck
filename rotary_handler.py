"""
Rotary Encoder Handler for KY-040 or similar rotary encoders.
Handles rotation and button press input for navigation.

Uses RPi.GPIO with polling mode for compatibility.
"""

import threading
import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

import config


class RotaryHandler:
    """Handles rotary encoder input using GPIO polling."""

    def __init__(self, demo_mode=False):
        self.demo_mode = demo_mode
        self.running = False
        self.lock = threading.Lock()

        # Get pin configuration
        encoder_config = config.ROTARY_ENCODER
        self.clk_pin = encoder_config["clk_pin"]
        self.dt_pin = encoder_config["dt_pin"]
        self.sw_pin = encoder_config["sw_pin"]

        # Callbacks
        self.on_rotate_cw = None   # Clockwise rotation
        self.on_rotate_ccw = None  # Counter-clockwise rotation
        self.on_button_press = None  # Button press

        # State tracking
        self._last_clk_state = None
        self._last_button_state = None
        self._initialized = False

    def initialize(self):
        """Initialize GPIO pins for the rotary encoder."""
        if self.demo_mode:
            print("[Rotary] Running in demo mode")
            self._initialized = True
            return True

        if not GPIO_AVAILABLE:
            print("[Rotary] ERROR: RPi.GPIO not available")
            return False

        try:
            # Setup encoder pins with internal pull-ups
            GPIO.setup(self.clk_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.dt_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.sw_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            # Read initial states
            self._last_clk_state = GPIO.input(self.clk_pin)
            self._last_button_state = GPIO.input(self.sw_pin)

            self._initialized = True
            print(f"[Rotary] Initialized (CLK={self.clk_pin}, DT={self.dt_pin}, SW={self.sw_pin})")
            return True

        except Exception as e:
            print(f"[Rotary] Initialization failed: {e}")
            return False

    def _poll_encoder(self):
        """Poll the encoder and trigger callbacks on state changes."""
        if not self._initialized or self.demo_mode:
            return

        try:
            # Read current states
            clk_state = GPIO.input(self.clk_pin)
            dt_state = GPIO.input(self.dt_pin)
            button_state = GPIO.input(self.sw_pin)

            # Check for rotation (CLK changed)
            if clk_state != self._last_clk_state:
                if clk_state == 0:  # Falling edge
                    if dt_state == 1:
                        # Clockwise rotation
                        if self.on_rotate_cw:
                            self.on_rotate_cw()
                    else:
                        # Counter-clockwise rotation
                        if self.on_rotate_ccw:
                            self.on_rotate_ccw()
                self._last_clk_state = clk_state

            # Check for button press (falling edge)
            if button_state == 0 and self._last_button_state == 1:
                if self.on_button_press:
                    self.on_button_press()
            self._last_button_state = button_state

        except Exception as e:
            print(f"[Rotary] Poll error: {e}")

    def simulate_rotation(self, direction="cw"):
        """Simulate a rotation event (for demo mode).

        Args:
            direction: "cw" for clockwise, "ccw" for counter-clockwise
        """
        if direction == "cw":
            print("[Rotary] Simulated CW rotation")
            if self.on_rotate_cw:
                self.on_rotate_cw()
        elif direction == "ccw":
            print("[Rotary] Simulated CCW rotation")
            if self.on_rotate_ccw:
                self.on_rotate_ccw()

    def simulate_button(self):
        """Simulate a button press (for demo mode)."""
        print("[Rotary] Simulated button press")
        if self.on_button_press:
            self.on_button_press()

    def run(self):
        """Main polling loop."""
        self.running = True
        print("[Rotary] Starting rotary handler (polling mode)")

        while self.running:
            if self.demo_mode:
                time.sleep(0.1)
            else:
                self._poll_encoder()
                time.sleep(0.001)  # 1ms polling interval

        print("[Rotary] Rotary handler stopped")

    def stop(self):
        """Stop the rotary handler."""
        self.running = False

    def cleanup(self):
        """Clean up resources."""
        self.stop()
        self._initialized = False
        print("[Rotary] Cleanup complete")
