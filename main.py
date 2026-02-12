#!/usr/bin/env python3
"""
OpenClaw Dual Display Command Center - Cyberpunk Edition
Main entry point - coordinates displays, touch input, and OpenClaw bridge.

Features Molty (space lobster mascot) on the large display with activity feed,
and a cyberpunk command panel on the small touchscreen display.

Uses raw spidev + RPi.GPIO instead of luma.lcd + lgpio.
"""

import argparse
import signal
import sys
import threading
import time
import random

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

from display_main import ConversationDisplay
from display_status import StatusDisplay
from touch_handler import TouchHandler
from rotary_handler import RotaryHandler
from lcd_ticker import LCDTicker
from openclaw_bridge import OpenClawBridge
from openclaw_config import OpenClawConfig
from websocket_client import ConnectionState
from ui.molty import MoltyState
import config


class DisplayCommandCenter:
    """Main application coordinator for the Cyberpunk Mission Control UI."""

    def __init__(self, demo_mode=False, openclaw_config=None):
        self.demo_mode = demo_mode
        self.running = False
        self.openclaw_config = openclaw_config or OpenClawConfig.load()

        # Components
        self.bridge = OpenClawBridge(demo_mode=demo_mode, config=self.openclaw_config)
        self.display1 = ConversationDisplay(demo_mode=demo_mode)
        self.display2 = StatusDisplay(demo_mode=demo_mode)
        self.touch = TouchHandler(demo_mode=demo_mode)
        self.rotary = RotaryHandler(demo_mode=demo_mode)
        self.lcd = LCDTicker(demo_mode=demo_mode)

        # Threads
        self.threads = []

        # Connection state tracking
        self._was_connected = False

        # State timers (for auto-returning Molty to IDLE)
        self._molty_state_timer = None
        self._active_button_id = None

        # Demo mode mock actions
        self._demo_action_index = 0

        # Display mode and scroll state
        self._display_mode = "activity"  # activity | molty | stats
        self._feed_scroll_offset = 0
        self._scroll_lock = threading.Lock()

    def _setup_bridge_callbacks(self):
        """Configure bridge event handlers."""

        def on_notification(notification):
            """Forward notifications to activity feed and update Molty state."""
            # Add to activity feed
            activity_type = "tool"
            status = "done"

            if "Starting" in notification.message or notification.title.startswith("Tool:"):
                activity_type = "tool"
                status = "running"
                self.display1.set_molty_state(MoltyState.WORKING)
            elif "Completed" in notification.message or "Success" in notification.message:
                activity_type = "status"
                status = "done"
                self._set_molty_state_with_timer(MoltyState.SUCCESS, 2.0)
            elif "Failed" in notification.message or "Error" in notification.message:
                activity_type = "error"
                status = "fail"
                self._set_molty_state_with_timer(MoltyState.ERROR, 3.0)
            elif notification.type == "info":
                activity_type = "notification"

            self.display1.add_activity(
                activity_type,
                notification.title,
                notification.message,
                status
            )

            # Update button state if there's an active button
            if self._active_button_id:
                if status == "done":
                    self.display2.set_button_state(self._active_button_id, "success")
                    self._reset_button_after_delay(self._active_button_id, 1.0)
                elif status == "fail":
                    self.display2.set_button_state(self._active_button_id, "error")
                    self._reset_button_after_delay(self._active_button_id, 1.5)

        def on_connection_change(state):
            """Handle connection state changes."""
            if state == ConnectionState.CONNECTED:
                if not self._was_connected:
                    print("[Main] Connected to OpenClaw")
                    self.display1.add_activity("status", "Connected", "OpenClaw online")
                    self.display1.set_molty_state(MoltyState.IDLE)
                    self.display1.set_status_text("Connected. Tap a command to begin.")
                self._was_connected = True
            elif state == ConnectionState.DISCONNECTED:
                if self._was_connected:
                    print("[Main] Disconnected from OpenClaw")
                    self.display1.add_activity("error", "Disconnected", "Connection lost")
                    self.display1.set_molty_state(MoltyState.ERROR)
                    self.display1.set_status_text("Disconnected. Tap to reconnect.")
                self._was_connected = False
            elif state == ConnectionState.RECONNECTING:
                print("[Main] Reconnecting to OpenClaw...")
                self.display1.add_activity("notification", "Reconnecting...", "")
                self.display1.set_molty_state(MoltyState.THINKING)

        def on_message_chunk(msg_id, chunk):
            """Handle streaming message chunks."""
            self.display1.set_molty_state(MoltyState.LISTENING)
            self.display1.set_status_text("Receiving response...")

        def on_status_update(status):
            """Handle status updates from OpenClaw."""
            if status.get("is_streaming"):
                self.display1.set_molty_state(MoltyState.WORKING)
                self.display1.set_status_text("Processing...")
            elif status.get("current_task") == "Idle":
                self.display1.set_molty_state(MoltyState.IDLE)
                self.display1.set_status_text("Waiting for commands...")

        self.bridge.set_callbacks(
            on_message_chunk=on_message_chunk,
            on_notification=on_notification,
            on_status_change=on_status_update,
            on_connection_change=on_connection_change,
        )

    def _set_molty_state_with_timer(self, state, delay_seconds):
        """Set Molty state and schedule return to IDLE after delay."""
        self.display1.set_molty_state(state)

        # Cancel existing timer
        if self._molty_state_timer:
            self._molty_state_timer.cancel()

        # Schedule return to IDLE
        def return_to_idle():
            if self.display1.get_molty_state() == state:
                self.display1.set_molty_state(MoltyState.IDLE)

        self._molty_state_timer = threading.Timer(delay_seconds, return_to_idle)
        self._molty_state_timer.daemon = True
        self._molty_state_timer.start()

    def _reset_button_after_delay(self, button_id, delay_seconds):
        """Reset button to normal state after delay."""
        def reset():
            self.display2.reset_button(button_id)
            if self._active_button_id == button_id:
                self._active_button_id = None

        timer = threading.Timer(delay_seconds, reset)
        timer.daemon = True
        timer.start()

    def _setup_touch_callbacks(self):
        """Configure touch event handlers for button panel."""

        def on_tap(x, y):
            """Handle tap events - check for button hits."""
            print(f"[Main] Tap at ({x}, {y})")

            # Find which button was tapped
            button = self.display2.find_button(x, y)

            if button:
                print(f"[Main] Button tapped: {button.id} - {button.label}")

                # Visual feedback
                self.display2.set_button_state(button.id, "pressed")

                if self.bridge.is_connected():
                    # Send command as message to OpenClaw
                    self.display2.set_button_state(button.id, "running")
                    self._active_button_id = button.id

                    # Add activity for the command
                    self.display1.add_activity(
                        "tool",
                        f"Command: {button.label}",
                        button.command,
                        "running"
                    )
                    self.display1.set_molty_state(MoltyState.WORKING)
                    self.display1.set_status_text(f"Executing {button.label}...")

                    # Send the command
                    self.bridge.send_message(button.command)

                    # Timeout: return to IDLE if no response events arrive
                    active_btn = button.id
                    def command_timeout():
                        if self._active_button_id == active_btn:
                            print(f"[Main] Command timeout for {active_btn}")
                            self.display1.set_molty_state(MoltyState.IDLE)
                            self.display1.set_status_text("No response received.")
                            self.display1.update_latest_activity_status("done")
                            self.display2.reset_button(active_btn)
                            self._active_button_id = None

                    timer = threading.Timer(15.0, command_timeout)
                    timer.daemon = True
                    timer.start()

                else:
                    # Not connected - show error
                    self.display2.set_button_state(button.id, "error")
                    self._reset_button_after_delay(button.id, 1.0)
                    self.display1.add_activity(
                        "error",
                        "Not Connected",
                        "Cannot send command",
                        "fail"
                    )
                    self.display1.set_molty_state(MoltyState.ERROR)

            else:
                # Tap outside buttons - could be status bar area
                bz_top = config.SMALL_BEZEL["top"]
                if bz_top <= y < bz_top + 35:
                    # Tapped status bar - try to reconnect if disconnected
                    if not self.bridge.is_connected():
                        print("[Main] Status bar tap - forcing reconnect")
                        self.bridge.force_reconnect()
                        self.display1.add_activity("notification", "Reconnecting...", "")
                        self.display1.set_molty_state(MoltyState.THINKING)

        def on_long_press(x, y):
            """Handle long press - force reconnect or cancel."""
            print(f"[Main] Long press at ({x}, {y})")

            bz_top = config.SMALL_BEZEL["top"]
            if bz_top <= y < bz_top + 35:
                # Long press on status bar - force reconnect
                print("[Main] Long press status bar - forcing reconnect")
                self.bridge.force_reconnect()
            else:
                # Long press on button area - cancel current operation
                if self.bridge.is_connected() and self._active_button_id:
                    print("[Main] Long press - cancelling current task")
                    self.bridge.cancel_current()
                    self.display2.reset_all_buttons()
                    self._active_button_id = None
                    self.display1.add_activity("notification", "Cancelled", "Operation cancelled")
                    self.display1.set_molty_state(MoltyState.IDLE)
                else:
                    # Toggle backlight when nothing is running
                    is_on = self.display2.toggle_backlight()
                    print(f"[Main] Backlight {'on' if is_on else 'off'}")

        # Both top and bottom now use the same handler (button detection)
        self.touch.on_tap_top = on_tap
        self.touch.on_tap_bottom = on_tap
        self.touch.on_long_press = on_long_press

    def _setup_rotary_callbacks(self):
        """Configure rotary encoder event handlers."""

        def on_rotate_cw():
            """Handle clockwise rotation - scroll up (show newer)."""
            with self._scroll_lock:
                self._feed_scroll_offset = max(0, self._feed_scroll_offset - 1)
                self.display1.set_scroll_offset(self._feed_scroll_offset)
            print(f"[Main] Rotary CW - scroll offset: {self._feed_scroll_offset}")

        def on_rotate_ccw():
            """Handle counter-clockwise rotation - scroll down (show older)."""
            with self._scroll_lock:
                self._feed_scroll_offset += 1
                self.display1.set_scroll_offset(self._feed_scroll_offset)
            print(f"[Main] Rotary CCW - scroll offset: {self._feed_scroll_offset}")

        def on_button_press():
            """Handle button press - cycle display mode."""
            modes = ["activity", "molty", "stats"]
            idx = (modes.index(self._display_mode) + 1) % len(modes)
            self._display_mode = modes[idx]
            print(f"[Main] Mode changed to: {self._display_mode}")

            # Flash mode name on LCD
            self.lcd.show_mode_briefly(self._display_mode.upper())

            # Reset scroll when changing modes
            with self._scroll_lock:
                self._feed_scroll_offset = 0
                self.display1.set_scroll_offset(0)

        self.rotary.on_rotate_cw = on_rotate_cw
        self.rotary.on_rotate_ccw = on_rotate_ccw
        self.rotary.on_button_press = on_button_press

    def _run_lcd(self):
        """Thread function for LCD state synchronization."""
        while self.running:
            try:
                # Get current Molty state and map to LCD text
                molty_state = self.display1.get_molty_state()
                state_map = {
                    MoltyState.IDLE: "IDLE",
                    MoltyState.WORKING: "WORKING",
                    MoltyState.SUCCESS: "DONE!",
                    MoltyState.ERROR: "ERROR!",
                    MoltyState.THINKING: "THINKING...",
                    MoltyState.LISTENING: "LISTENING",
                }
                state_text = state_map.get(molty_state, "UNKNOWN")
                self.lcd.set_state(state_text)

                # Get latest activity detail for scrolling line
                if hasattr(self.display1, 'activity_feed') and self.display1.activity_feed.entries:
                    latest = self.display1.activity_feed.entries[-1]
                    detail = f"{latest.title}: {latest.detail}" if latest.detail else latest.title
                    self.lcd.set_detail(detail)

            except Exception as e:
                print(f"[Main] LCD sync error: {e}")

            time.sleep(config.CHARACTER_LCD["update_interval"])

    def initialize(self):
        """Initialize all components."""
        print("=" * 50)
        print("OpenClaw Dual Display Command Center")
        print(">>> CYBERPUNK EDITION <<<")
        print(f"Mode: {'Demo' if self.demo_mode else 'Production'}")
        if not self.demo_mode:
            print(f"OpenClaw URL: {self.openclaw_config.url}")
        print("=" * 50)

        # Initialize GPIO system first (only in production mode)
        if not self.demo_mode and GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            print("[Main] GPIO initialized (BCM mode)")

        # Setup callbacks before connecting
        self._setup_bridge_callbacks()

        # Initialize bridge
        if not self.bridge.connect():
            print("[Main] WARNING: Bridge connection failed")
            self.display1.add_activity("warning", "Connection Failed", "Will retry automatically")

        # Initialize displays sequentially with delay (helps with power stability)
        print("[Main] Initializing Display 1 (large, ILI9488 - Molty + Activity)...")
        display1_ok = self.display1.initialize()
        time.sleep(1.0)

        print("[Main] Initializing Display 2 (small, ILI9341 - Command Panel)...")
        display2_ok = self.display2.initialize()
        time.sleep(0.5)

        if not display1_ok and not display2_ok and not self.demo_mode:
            print("[Main] ERROR: No displays available")
            return False

        # Initialize touch
        print("[Main] Initializing touch controller...")
        touch_ok = self.touch.initialize()
        if not touch_ok and not self.demo_mode:
            print("[Main] WARNING: Touch not available")

        # Setup touch callbacks
        self._setup_touch_callbacks()

        # Initialize rotary encoder
        print("[Main] Initializing rotary encoder...")
        rotary_ok = self.rotary.initialize()
        if not rotary_ok and not self.demo_mode:
            print("[Main] WARNING: Rotary encoder not available")

        # Setup rotary callbacks
        self._setup_rotary_callbacks()

        # Initialize LCD
        print("[Main] Initializing 16x2 LCD...")
        lcd_ok = self.lcd.initialize()
        if not lcd_ok and not self.demo_mode:
            print("[Main] WARNING: LCD not available")

        # Seed initial state
        if self.demo_mode:
            print("[Main] Seeding demo state...")
            self.display1.add_activity("status", "System Online", "Cyberpunk Mode Active")
            self.display1.add_activity("notification", "Demo Mode", "Simulated data")
            self.display1.set_molty_state(MoltyState.IDLE)
            self.display1.set_status_text("Demo mode active. Tap buttons to test.")
            self.display2.update_status(connected=True, model="demo-model", api_cost=0.0)
        else:
            self.display1.add_activity("status", "Initializing", "Connecting to OpenClaw...")
            self.display1.set_status_text("Connecting...")

        print("[Main] Initialization complete")
        return True

    def _run_display1(self):
        """Thread function for conversation display with streaming support."""
        def get_messages():
            return self.bridge.get_latest_messages()

        def get_streaming():
            return self.bridge.get_current_streaming_message()

        self.display1.run(
            get_messages_func=get_messages,
            get_streaming_func=get_streaming,
            interval=None
        )

    def _run_display2(self):
        """Thread function for status display."""
        def get_status():
            return self.bridge.get_status()

        def get_notifications():
            return self.bridge.get_notifications(max_age_seconds=10.0)

        self.display2.run(
            get_status_func=get_status,
            get_notifications_func=get_notifications,
            interval=0.5  # Faster refresh for button animations
        )

    def _run_touch(self):
        """Thread function for touch handler."""
        self.touch.run(poll_interval=0.005)

    def _demo_touch_simulation(self):
        """Simulate touch events and mock actions in demo mode."""
        print("[Main] Demo touch simulation active")
        print("[Main] Commands:")
        print("  Enter/Space = simulate button tap")
        print("  1-6 = tap specific button")
        print("  s = cycle Molty state")
        print("  a = add mock activity")
        print("  r or Right = rotary CW (scroll up)")
        print("  l or Left  = rotary CCW (scroll down)")
        print("  b = rotary button (cycle mode)")
        print("  q = quit")

        # Mock actions for demo
        mock_actions = [
            ("tool", "Checked inbox", "3 new messages - 1 urgent from IBM"),
            ("tool", "Running backup", "rsync ~/projects -> NAS"),
            ("message", "Browsing docs", "Researching GPU pricing on Modal.dev"),
            ("error", "Slack timeout", "Failed to reach after 30s"),
            ("tool", "Calendar sync", "Updated 5 events"),
            ("status", "Focus mode", "Notifications paused for 2h"),
            ("notification", "Reminder", "Meeting in 15 minutes"),
            ("tool", "Git push", "Pushed 3 commits to main"),
        ]

        molty_states = list(MoltyState)
        molty_state_index = 0

        while self.running:
            try:
                import select
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    user_input = sys.stdin.readline().strip().lower()

                    if user_input == 'q':
                        print("[Main] Quit requested")
                        self.stop()
                        break

                    elif user_input in ('', ' '):
                        # Simulate random button tap
                        buttons = self.display2.command_panel.buttons
                        button = random.choice(buttons)
                        self.touch.simulate_touch("bottom")
                        # Add mock activity
                        action = mock_actions[self._demo_action_index % len(mock_actions)]
                        self.display1.add_activity(action[0], action[1], action[2], "running")
                        self.display1.set_molty_state(MoltyState.WORKING)
                        self._demo_action_index += 1

                        # Simulate completion after delay
                        def complete_action():
                            self.display1.update_latest_activity_status("done")
                            self._set_molty_state_with_timer(MoltyState.SUCCESS, 2.0)

                        timer = threading.Timer(1.5, complete_action)
                        timer.daemon = True
                        timer.start()

                    elif user_input in '123456':
                        # Tap specific button
                        idx = int(user_input) - 1
                        buttons = self.display2.command_panel.buttons
                        if idx < len(buttons):
                            button = buttons[idx]
                            x = button.x + button.width // 2
                            y = button.y + button.height // 2
                            self.touch.on_tap_bottom(x, y)

                    elif user_input == 's':
                        # Cycle Molty state
                        molty_state_index = (molty_state_index + 1) % len(molty_states)
                        state = molty_states[molty_state_index]
                        self.display1.set_molty_state(state)
                        print(f"[Main] Molty state: {state.value}")

                    elif user_input == 'a':
                        # Add mock activity
                        action = mock_actions[self._demo_action_index % len(mock_actions)]
                        self.display1.add_activity(action[0], action[1], action[2])
                        self._demo_action_index += 1
                        print(f"[Main] Added activity: {action[1]}")

                    elif user_input in ('r', 'right', '\x1b[c'):
                        # Simulate CW rotation (scroll up / show newer)
                        self.rotary.simulate_rotation("cw")

                    elif user_input in ('l', 'left', '\x1b[d'):
                        # Simulate CCW rotation (scroll down / show older)
                        self.rotary.simulate_rotation("ccw")

                    elif user_input == 'b':
                        # Simulate button press (cycle mode)
                        self.rotary.simulate_button()

            except Exception as e:
                print(f"[Main] Demo input error: {e}")
                time.sleep(0.5)

    def run(self):
        """Start all components in threads."""
        self.running = True

        # Start display threads
        display1_thread = threading.Thread(target=self._run_display1, name="Display1")
        display1_thread.daemon = True
        display1_thread.start()
        self.threads.append(display1_thread)
        print("[Main] Display 1 thread started (Molty + Activity Feed)")

        display2_thread = threading.Thread(target=self._run_display2, name="Display2")
        display2_thread.daemon = True
        display2_thread.start()
        self.threads.append(display2_thread)
        print("[Main] Display 2 thread started (Command Panel)")

        # Start touch thread
        touch_thread = threading.Thread(target=self._run_touch, name="Touch")
        touch_thread.daemon = True
        touch_thread.start()
        self.threads.append(touch_thread)
        print("[Main] Touch handler thread started")

        # Start rotary thread
        rotary_thread = threading.Thread(target=self.rotary.run, name="Rotary")
        rotary_thread.daemon = True
        rotary_thread.start()
        self.threads.append(rotary_thread)
        print("[Main] Rotary encoder thread started")

        # Start LCD ticker thread
        lcd_thread = threading.Thread(target=self.lcd.run, name="LCD")
        lcd_thread.daemon = True
        lcd_thread.start()
        self.threads.append(lcd_thread)
        print("[Main] LCD ticker thread started")

        # Start LCD state sync thread
        lcd_sync_thread = threading.Thread(target=self._run_lcd, name="LCDSync")
        lcd_sync_thread.daemon = True
        lcd_sync_thread.start()
        self.threads.append(lcd_sync_thread)
        print("[Main] LCD sync thread started")

        print("\n[Main] System running. Press Ctrl+C to exit.\n")

        # In demo mode, run interactive simulation
        if self.demo_mode:
            self._demo_touch_simulation()
        else:
            # Keep main thread alive
            while self.running:
                time.sleep(0.5)

    def stop(self):
        """Signal all components to stop."""
        print("\n[Main] Shutting down...")
        self.running = False

        # Cancel state timer
        if self._molty_state_timer:
            self._molty_state_timer.cancel()

        self.display1.stop()
        self.display2.stop()
        self.touch.stop()
        self.rotary.stop()
        self.lcd.stop()

        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=2.0)

    def cleanup(self):
        """Clean up all resources."""
        self.display1.cleanup()
        self.display2.cleanup()
        self.touch.cleanup()
        self.rotary.cleanup()
        self.lcd.cleanup()
        self.bridge.cleanup()

        # Cleanup GPIO pins (only non-SPI pins)
        if not self.demo_mode and GPIO_AVAILABLE:
            try:
                GPIO.cleanup(config.GPIO_PINS)
                print("[Main] GPIO cleanup complete")
            except Exception as e:
                print(f"[Main] GPIO cleanup warning: {e}")

        print("[Main] Cleanup complete")


def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw Dual Display Command Center - Cyberpunk Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --demo                    Run in demo mode with simulated data
  python main.py --url ws://100.x.x.x:18789  Connect to OpenClaw via Tailscale
  python main.py --url ws://localhost:18789 --password secret  With authentication

Configuration (priority order):
  1. CLI arguments (--url, --password)
  2. .env file (in current dir or ~/.openclaw_display.env)
  3. JSON config (~/.openclaw_display.json)

.env file example:
  OPENCLAW_URL=ws://100.x.x.x:18789
  OPENCLAW_PASSWORD=your_password

Use --create-config to generate sample .env and JSON config files.

Cyberpunk UI Features:
  - Large Display: Molty (space lobster) + Activity Feed
  - Small Display: Touch command panel with 6 buttons
  - Scanline CRT effect on both displays
  - Neon color scheme (cyan, pink, purple)
"""
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode with simulated data"
    )
    parser.add_argument(
        "--url",
        type=str,
        help="OpenClaw WebSocket URL (e.g., ws://100.x.x.x:18789)"
    )
    parser.add_argument(
        "--password",
        type=str,
        help="Authentication password for OpenClaw"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config file"
    )
    parser.add_argument(
        "--create-config",
        action="store_true",
        help="Create a sample config file and exit"
    )
    args = parser.parse_args()

    # Handle --create-config
    if args.create_config:
        from openclaw_config import create_sample_config
        create_sample_config()
        sys.exit(0)

    # Load configuration
    openclaw_config = OpenClawConfig.load(
        cli_url=args.url,
        cli_password=args.password,
        config_path=args.config,
    )

    # Create application
    app = DisplayCommandCenter(
        demo_mode=args.demo,
        openclaw_config=openclaw_config
    )

    # Setup signal handlers
    def signal_handler(sig, frame):
        app.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize and run
    if not app.initialize():
        print("[Main] Initialization failed, exiting")
        sys.exit(1)

    try:
        app.run()
    finally:
        app.cleanup()

    print("[Main] Goodbye!")


if __name__ == "__main__":
    main()
