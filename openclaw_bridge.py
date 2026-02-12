"""
OpenClaw Bridge - Interface between displays and OpenClaw.
Supports both demo mode (simulated data) and live WebSocket connection.
"""

import random
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any

from websocket_client import (
    OpenClawWebSocketClient,
    ConnectionState,
    StreamingMessage,
    Notification,
)
from openclaw_config import OpenClawConfig


class OpenClawBridge:
    """
    Interface for OpenClaw data.
    Supports demo mode with simulated data and live WebSocket connection.
    """

    # Demo conversation samples
    DEMO_CONVERSATIONS = [
        {"role": "user", "content": "Can you help me set up a Python project?"},
        {"role": "assistant", "content": "Of course! I'd be happy to help you set up a Python project. What type of project are you building?"},
        {"role": "user", "content": "I'm building a web scraper to collect data from news sites."},
        {"role": "assistant", "content": "Great choice! For web scraping, I recommend using requests for HTTP calls and BeautifulSoup for parsing HTML. Should I set up a basic project structure for you?"},
        {"role": "user", "content": "Yes please, and also add error handling for rate limiting."},
        {"role": "assistant", "content": "I'll create a project with proper rate limiting, retry logic, and respect for robots.txt. Let me set that up now."},
        {"role": "user", "content": "How's the display project coming along?"},
        {"role": "assistant", "content": "The dual display setup is working well! The 4-inch screen shows our conversation and the 2.8-inch shows system status."},
        {"role": "user", "content": "Can you add touch support to cycle through different views?"},
        {"role": "assistant", "content": "Already implemented! Tap the top half to cycle status views, bottom half for quick commands, and long press to toggle the backlight."},
        {"role": "user", "content": "What's the current API usage looking like?"},
        {"role": "assistant", "content": "We're at $0.0234 for this session. The conversation display uses about 2KB per message render."},
        {"role": "user", "content": "Perfect. Let's add a feature to export conversation history."},
        {"role": "assistant", "content": "I can add JSON and markdown export options. The export will include timestamps and token counts. Want me to proceed?"},
    ]

    DEMO_TASKS = [
        "Idle",
        "Processing request...",
        "Analyzing code structure",
        "Writing display_main.py",
        "Running tests",
        "Generating response",
        "Waiting for input",
        "Compiling assets",
        "Optimizing render loop",
    ]

    def __init__(self, demo_mode=False, config: Optional[OpenClawConfig] = None):
        self.demo_mode = demo_mode
        self.config = config or OpenClawConfig.load()
        self.lock = threading.Lock()

        # Callbacks for display updates
        self._on_message_chunk: Optional[Callable[[str, str], None]] = None
        self._on_message_complete: Optional[Callable[[Dict], None]] = None
        self._on_notification: Optional[Callable[[Notification], None]] = None
        self._on_status_change: Optional[Callable[[Dict], None]] = None
        self._on_connection_change: Optional[Callable[[ConnectionState], None]] = None

        # WebSocket client (only in non-demo mode)
        self._ws_client: Optional[OpenClawWebSocketClient] = None

        # Internal state
        self._messages: List[Dict] = []
        self._message_index = 0
        self._ws_messages_cursor = 0  # Track how many ws messages have been returned
        self._current_streaming: Optional[StreamingMessage] = None
        self._notifications: List[Notification] = []
        self._max_notifications = 10

        self._status = {
            "connected": False,
            "connection_state": ConnectionState.DISCONNECTED,
            "task_summary": "Initializing...",
            "queue_count": 0,
            "api_cost": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "model": "unknown",
            "is_streaming": False,
            "uptime_start": datetime.now(),
            "last_activity": datetime.now(),
        }

        # Demo mode timers
        self._last_message_time = time.time()
        self._last_status_change = time.time()
        self._demo_streaming_text = ""
        self._demo_streaming_index = 0

    def set_callbacks(
        self,
        on_message_chunk: Optional[Callable[[str, str], None]] = None,
        on_message_complete: Optional[Callable[[Dict], None]] = None,
        on_notification: Optional[Callable[[Notification], None]] = None,
        on_status_change: Optional[Callable[[Dict], None]] = None,
        on_connection_change: Optional[Callable[[ConnectionState], None]] = None,
    ):
        """Set callbacks for events."""
        self._on_message_chunk = on_message_chunk
        self._on_message_complete = on_message_complete
        self._on_notification = on_notification
        self._on_status_change = on_status_change
        self._on_connection_change = on_connection_change

    def connect(self) -> bool:
        """
        Connect to OpenClaw.
        In demo mode, simulates a successful connection.
        """
        if self.demo_mode:
            print("[Bridge] Demo mode - simulating connection")
            with self.lock:
                self._status["connected"] = True
                self._status["connection_state"] = ConnectionState.CONNECTED
                self._status["task_summary"] = "Demo mode active"
                self._status["model"] = "claude-3-opus (demo)"
            return True

        # Create and start WebSocket client
        try:
            self._ws_client = OpenClawWebSocketClient(
                url=self.config.get_effective_url(),
                password=self.config.password,
                on_message_chunk=self._handle_ws_message_chunk,
                on_message_complete=self._handle_ws_message_complete,
                on_notification=self._handle_ws_notification,
                on_status_change=self._handle_ws_status_change,
                on_connection_change=self._handle_ws_connection_change,
            )
            self._ws_client.start()
            print(f"[Bridge] Connecting to {self.config.url}")
            return True

        except Exception as e:
            print(f"[Bridge] Failed to create WebSocket client: {e}")
            return False

    def _handle_ws_message_chunk(self, msg_id: str, chunk: str):
        """Handle streaming message chunk from WebSocket."""
        with self.lock:
            self._status["is_streaming"] = True
            self._status["last_activity"] = datetime.now()

        if self._on_message_chunk:
            self._on_message_chunk(msg_id, chunk)

    def _handle_ws_message_complete(self, message: Dict):
        """Handle completed message from WebSocket."""
        with self.lock:
            self._messages.append(message)
            self._status["is_streaming"] = False
            self._status["last_activity"] = datetime.now()

        if self._on_message_complete:
            self._on_message_complete(message)

    def _handle_ws_notification(self, notification: Notification):
        """Handle notification from WebSocket."""
        with self.lock:
            self._notifications.append(notification)
            if len(self._notifications) > self._max_notifications:
                self._notifications = self._notifications[-self._max_notifications:]

        if self._on_notification:
            self._on_notification(notification)

    def _handle_ws_status_change(self, status: Dict):
        """Handle status update from WebSocket."""
        with self.lock:
            for key, value in status.items():
                if key in self._status:
                    self._status[key] = value

        if self._on_status_change:
            self._on_status_change(self.get_status())

    def _handle_ws_connection_change(self, state: ConnectionState):
        """Handle connection state change from WebSocket."""
        with self.lock:
            self._status["connection_state"] = state
            self._status["connected"] = (state == ConnectionState.CONNECTED)

        if self._on_connection_change:
            self._on_connection_change(state)

    def disconnect(self):
        """Disconnect from OpenClaw."""
        if self._ws_client:
            self._ws_client.stop()
            self._ws_client = None

        with self.lock:
            self._status["connected"] = False
            self._status["connection_state"] = ConnectionState.DISCONNECTED

        print("[Bridge] Disconnected")

    def get_latest_messages(self, n=10) -> List[Dict]:
        """
        Get only NEW messages since the last call.
        Returns list of dicts with 'role', 'content', 'timestamp'.
        """
        if self.demo_mode:
            return self._get_demo_messages(n)

        # Return only messages we haven't returned before
        if self._ws_client:
            all_msgs = self._ws_client.messages
            new_msgs = all_msgs[self._ws_messages_cursor:]
            self._ws_messages_cursor = len(all_msgs)
            return new_msgs

        return []

    def _get_demo_messages(self, n) -> List[Dict]:
        """Generate demo messages with realistic timing."""
        current_time = time.time()
        new_messages = []

        # Add a new message every few seconds
        if current_time - self._last_message_time > 3.0:
            if self._message_index < len(self.DEMO_CONVERSATIONS):
                msg = self.DEMO_CONVERSATIONS[self._message_index].copy()
                msg["timestamp"] = datetime.now()

                with self.lock:
                    self._messages.append(msg)
                    self._status["last_activity"] = datetime.now()
                    self._status["api_cost"] += random.uniform(0.001, 0.005)
                    self._status["tokens_in"] += random.randint(10, 50)
                    self._status["tokens_out"] += random.randint(20, 100)

                self._message_index += 1
                self._last_message_time = current_time
                new_messages.append(msg)
            else:
                # Loop back to start
                self._message_index = 0
                self._messages = []

        return new_messages

    def get_all_messages(self) -> List[Dict]:
        """Get all messages in the current conversation."""
        if self._ws_client:
            return self._ws_client.messages

        with self.lock:
            return list(self._messages)

    def get_current_streaming_message(self) -> Optional[StreamingMessage]:
        """Get the current streaming message if any."""
        if self.demo_mode:
            return self._get_demo_streaming()

        if self._ws_client:
            return self._ws_client.current_streaming_message

        return None

    def _get_demo_streaming(self) -> Optional[StreamingMessage]:
        """Simulate streaming for demo mode."""
        # Occasionally start a demo streaming message
        if random.random() > 0.995 and not self._current_streaming:
            demo_response = random.choice([
                "I'm analyzing the codebase structure to find the best approach...",
                "Let me check the configuration files for any issues...",
                "Processing your request and generating a detailed response...",
                "Looking through the project files to understand the architecture...",
            ])
            self._demo_streaming_text = demo_response
            self._demo_streaming_index = 0
            self._current_streaming = StreamingMessage(
                id="demo",
                role="assistant",
            )
            with self.lock:
                self._status["is_streaming"] = True

        # Progress streaming
        if self._current_streaming and self._demo_streaming_index < len(self._demo_streaming_text):
            chunk_size = random.randint(1, 3)
            chunk = self._demo_streaming_text[self._demo_streaming_index:self._demo_streaming_index + chunk_size]
            self._current_streaming.append_chunk(chunk)
            self._demo_streaming_index += chunk_size

            if self._demo_streaming_index >= len(self._demo_streaming_text):
                # Complete the streaming
                self._current_streaming.complete = True
                completed = self._current_streaming
                self._current_streaming = None
                self._demo_streaming_text = ""
                self._demo_streaming_index = 0
                with self.lock:
                    self._status["is_streaming"] = False
                return None  # Return None to indicate completion

        return self._current_streaming

    def get_status(self) -> Dict[str, Any]:
        """
        Get current status information.
        Returns dict with connection state, task info, queue count, etc.
        """
        if self.demo_mode:
            self._update_demo_status()

        with self.lock:
            return dict(self._status)

    def _update_demo_status(self):
        """Update demo status with simulated changes."""
        current_time = time.time()

        if current_time - self._last_status_change > 2.0:
            with self.lock:
                # Randomly change task
                self._status["task_summary"] = random.choice(self.DEMO_TASKS)

                # Fluctuate queue count
                if random.random() > 0.7:
                    self._status["queue_count"] = random.randint(0, 5)

                # Connection occasionally flickers in demo
                if random.random() > 0.95:
                    self._status["connected"] = not self._status["connected"]
                else:
                    self._status["connected"] = True

            self._last_status_change = current_time

    def get_notifications(self, max_age_seconds: float = 10.0) -> List[Notification]:
        """Get recent notifications."""
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        with self.lock:
            return [n for n in self._notifications if n.timestamp > cutoff]

    def add_notification(self, type_: str, title: str, message: str = "", duration: float = 2.0):
        """Add a notification."""
        notification = Notification(
            type=type_,
            title=title,
            message=message,
            duration=duration,
        )
        with self.lock:
            self._notifications.append(notification)
            if len(self._notifications) > self._max_notifications:
                self._notifications = self._notifications[-self._max_notifications:]

        if self._on_notification:
            self._on_notification(notification)

    def send_command(self, text: str) -> bool:
        """
        Send a command to OpenClaw.
        In demo mode, prints to console.
        """
        print(f"[Bridge] Command sent: {text}")

        if self.demo_mode:
            # Simulate command acknowledgment
            with self.lock:
                self._status["last_activity"] = datetime.now()
                self._status["queue_count"] += 1
            return True

        # Send via WebSocket
        if self._ws_client:
            return self._ws_client.send_command(text)

        return False

    def send_message(self, text: str) -> bool:
        """Send a user message to OpenClaw."""
        print(f"[Bridge] Message sent: {text}")

        if self.demo_mode:
            # Add to local messages
            with self.lock:
                self._messages.append({
                    "role": "user",
                    "content": text,
                    "timestamp": datetime.now(),
                })
                self._status["last_activity"] = datetime.now()
            return True

        if self._ws_client:
            return self._ws_client.send_message(text)

        return False

    def cancel_current(self) -> bool:
        """Cancel the current operation."""
        print("[Bridge] Cancel requested")

        if self.demo_mode:
            with self.lock:
                self._current_streaming = None
                self._status["is_streaming"] = False
                self._status["task_summary"] = "Cancelled"
            self.add_notification("warning", "Cancelled")
            return True

        if self._ws_client:
            return self._ws_client.cancel_current()

        return False

    def force_reconnect(self) -> bool:
        """Force a reconnection."""
        print("[Bridge] Force reconnect requested")

        if self.demo_mode:
            with self.lock:
                self._status["connected"] = False
            time.sleep(0.5)
            with self.lock:
                self._status["connected"] = True
            self.add_notification("success", "Reconnected")
            return True

        if self._ws_client:
            self._ws_client.force_reconnect()
            return True

        return False

    def trigger_action(self, action_name: str) -> bool:
        """
        Trigger a predefined action.
        Actions: 'refresh', 'clear', 'pause', 'resume'
        """
        print(f"[Bridge] Action triggered: {action_name}")

        with self.lock:
            self._status["last_activity"] = datetime.now()

        if action_name == "clear":
            with self.lock:
                self._messages = []
                self._message_index = 0

        return True

    def get_metrics(self) -> Dict[str, Any]:
        """Get detailed metrics (API cost breakdown, token counts, etc.)."""
        if self.demo_mode:
            with self.lock:
                return {
                    "total_tokens": self._status["tokens_in"] + self._status["tokens_out"],
                    "input_tokens": self._status["tokens_in"],
                    "output_tokens": self._status["tokens_out"],
                    "api_calls": random.randint(10, 50),
                    "session_cost": self._status["api_cost"],
                }

        if self._ws_client:
            status = self._ws_client.status
            return {
                "total_tokens": status.get("tokens_in", 0) + status.get("tokens_out", 0),
                "input_tokens": status.get("tokens_in", 0),
                "output_tokens": status.get("tokens_out", 0),
                "session_cost": status.get("cost", 0.0),
            }

        return {}

    def is_connected(self) -> bool:
        """Check if connected to OpenClaw."""
        if self._ws_client:
            return self._ws_client.is_connected

        with self.lock:
            return self._status.get("connected", False)

    def is_streaming(self) -> bool:
        """Check if currently streaming a response."""
        if self._ws_client:
            return self._ws_client.current_streaming_message is not None

        with self.lock:
            return self._status.get("is_streaming", False)

    def cleanup(self):
        """Clean up resources."""
        self.disconnect()
        print("[Bridge] Cleanup complete")
