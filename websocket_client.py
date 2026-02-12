"""
WebSocket Client for OpenClaw Gateway.
Implements the OpenClaw Gateway protocol with proper connect handshake.

Protocol:
- Server sends connect.challenge event with nonce
- Client responds with connect request including signed challenge
- Requests: {type:"req", id, method, params}
- Responses: {type:"res", id, ok, payload|error}
- Events: {type:"event", event, payload, seq?, stateVersion?}
"""

import asyncio
import base64
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

# Try to import cryptography for device signing
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("[WebSocket] WARNING: cryptography library not installed")
    print("[WebSocket] Install with: pip install cryptography")


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class MessageType(Enum):
    """OpenClaw message types."""
    # Conversation messages
    USER_MESSAGE = "user_message"
    ASSISTANT_CHUNK = "assistant_chunk"
    ASSISTANT_COMPLETE = "assistant_complete"

    # Tool events
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # Status events
    STATUS_UPDATE = "status_update"
    TASK_UPDATE = "task_update"

    # Control
    CONNECTED = "connected"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class StreamingMessage:
    """Represents a message being streamed."""
    id: str
    role: str
    content: str = ""
    complete: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    def append_chunk(self, chunk: str):
        """Append a chunk to the message content."""
        self.content += chunk


@dataclass
class Notification:
    """Represents a notification event."""
    type: str  # info, success, warning, error
    title: str
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 2.0  # seconds to display


class OpenClawWebSocketClient:
    """
    Async WebSocket client for OpenClaw Gateway.
    Implements the OpenClaw Gateway protocol.
    Runs in a background thread with an asyncio event loop.
    """

    def __init__(
        self,
        url: str = "ws://localhost:18789",
        password: Optional[str] = None,
        on_message_chunk: Optional[Callable[[str, str], None]] = None,
        on_message_complete: Optional[Callable[[Dict], None]] = None,
        on_notification: Optional[Callable[[Notification], None]] = None,
        on_status_change: Optional[Callable[[Dict], None]] = None,
        on_connection_change: Optional[Callable[[ConnectionState], None]] = None,
    ):
        self.url = url
        self.password = password

        # Callbacks (thread-safe via queue)
        self._on_message_chunk = on_message_chunk
        self._on_message_complete = on_message_complete
        self._on_notification = on_notification
        self._on_status_change = on_status_change
        self._on_connection_change = on_connection_change

        # State
        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._websocket = None
        self._running = False

        # Request tracking
        self._request_id = 0
        self._pending_requests: Dict[str, asyncio.Future] = {}

        # Reconnection settings
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._reconnect_attempts = 0

        # Current streaming message
        self._current_streaming: Optional[StreamingMessage] = None

        # Message history (thread-safe access)
        self._messages: List[Dict] = []
        self._max_messages = 100

        # Status data
        self._status: Dict[str, Any] = {
            "model": "unknown",
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "current_task": "Idle",
            "is_streaming": False,
        }

        # Session tracking
        self._session_id: Optional[str] = None
        self._session_key: Optional[str] = None
        self._subscribed_sessions: set = set()

        # Device keys for authentication
        self._private_key = None
        self._public_key = None
        self._device_id = None
        self._load_or_generate_keys()

    def _next_request_id(self) -> str:
        """Generate next request ID."""
        self._request_id += 1
        return str(self._request_id)

    def _get_keys_path(self) -> Path:
        """Get path for storing device keys."""
        return Path.home() / ".openclaw_display_keys.json"

    def _load_or_generate_keys(self):
        """Load existing keys or generate new ones."""
        if not CRYPTO_AVAILABLE:
            print("[WebSocket] Cryptography not available, using simple device ID")
            self._device_id = str(uuid.getnode())
            return

        keys_path = self._get_keys_path()

        if keys_path.exists():
            try:
                with open(keys_path, "r") as f:
                    data = json.load(f)

                # Load private key
                private_bytes = base64.b64decode(data["private_key"])
                self._private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
                self._public_key = self._private_key.public_key()
                # Device ID must be derived from public key fingerprint (full SHA-256)
                public_bytes = self._public_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw
                )
                self._device_id = hashlib.sha256(public_bytes).hexdigest()
                print(f"[WebSocket] Loaded device keys (ID: {self._device_id[:8]}...)")
                return
            except Exception as e:
                print(f"[WebSocket] Failed to load keys: {e}")

        # Generate new keys
        print("[WebSocket] Generating new device keys...")
        self._private_key = ed25519.Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()
        # Device ID must be derived from public key fingerprint (full SHA-256)
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        self._device_id = hashlib.sha256(public_bytes).hexdigest()

        # Save keys
        try:
            private_bytes = self._private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption()
            )
            data = {
                "device_id": self._device_id,
                "private_key": base64.b64encode(private_bytes).decode(),
            }
            with open(keys_path, "w") as f:
                json.dump(data, f)
            os.chmod(keys_path, 0o600)  # Secure permissions
            print(f"[WebSocket] Saved new device keys (ID: {self._device_id[:8]}...)")
        except Exception as e:
            print(f"[WebSocket] Failed to save keys: {e}")

    def _get_public_key_base64(self) -> str:
        """Get public key as base64 string."""
        if not self._public_key:
            return ""
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return base64.b64encode(public_bytes).decode()

    def _build_auth_payload(self, nonce: str, signed_at: int, client_id: str,
                              client_mode: str, role: str, scopes: list, token: str = "") -> str:
        """Build the pipe-delimited auth payload for signing."""
        # Format: version|deviceId|clientId|clientMode|role|scopes|signedAt|token|nonce
        parts = [
            "v2",  # version (v2 when nonce exists)
            self._device_id,
            client_id,
            client_mode,
            role,
            ",".join(scopes),
            str(signed_at),
            token,
            nonce,
        ]
        return "|".join(parts)

    def _sign_challenge(self, payload: str) -> str:
        """Sign the auth payload with device private key."""
        if not self._private_key:
            return ""
        message = payload.encode()
        signature = self._private_key.sign(message)
        return base64.b64encode(signature).decode()

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        with self._lock:
            return self._state

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.state == ConnectionState.CONNECTED

    @property
    def current_streaming_message(self) -> Optional[StreamingMessage]:
        """Get the current streaming message if any."""
        with self._lock:
            return self._current_streaming

    @property
    def status(self) -> Dict[str, Any]:
        """Get current status data."""
        with self._lock:
            return dict(self._status)

    @property
    def messages(self) -> List[Dict]:
        """Get message history."""
        with self._lock:
            return list(self._messages)

    def _set_state(self, state: ConnectionState):
        """Update connection state and notify callback."""
        with self._lock:
            self._state = state
        if self._on_connection_change:
            try:
                self._on_connection_change(state)
            except Exception as e:
                print(f"[WebSocket] Connection callback error: {e}")

    def _emit_notification(self, type_: str, title: str, message: str = "", duration: float = 2.0):
        """Emit a notification event."""
        if self._on_notification:
            try:
                notification = Notification(
                    type=type_,
                    title=title,
                    message=message,
                    duration=duration
                )
                self._on_notification(notification)
            except Exception as e:
                print(f"[WebSocket] Notification callback error: {e}")

    def start(self):
        """Start the WebSocket client in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="WebSocketClient", daemon=True)
        self._thread.start()
        print("[WebSocket] Client thread started")

    def stop(self):
        """Stop the WebSocket client."""
        self._running = False

        if self._loop:
            # Schedule shutdown in the event loop
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        print("[WebSocket] Client stopped")

    def _run_loop(self):
        """Run the asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._connect_loop())
        except Exception as e:
            print(f"[WebSocket] Event loop error: {e}")
        finally:
            self._loop.close()

    async def _shutdown(self):
        """Graceful shutdown."""
        if self._websocket:
            await self._websocket.close()

    async def _connect_loop(self):
        """Main connection loop with auto-reconnect."""
        try:
            import websockets
        except ImportError:
            print("[WebSocket] ERROR: websockets library not installed")
            print("[WebSocket] Install with: pip install websockets")
            self._set_state(ConnectionState.FAILED)
            return

        while self._running:
            try:
                self._set_state(ConnectionState.CONNECTING)
                print(f"[WebSocket] Connecting to {self.url}")

                async with websockets.connect(
                    self.url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._websocket = ws

                    # Send connect request (MUST be first frame)
                    connected = await self._send_connect(ws)
                    if not connected:
                        print("[WebSocket] Connect handshake failed")
                        continue

                    self._set_state(ConnectionState.CONNECTED)
                    self._reconnect_delay = 1.0
                    self._reconnect_attempts = 0

                    print("[WebSocket] Connected successfully")
                    self._emit_notification("success", "Connected", f"Connected to OpenClaw")

                    # Discover and subscribe to sessions
                    await self._post_connect_setup(ws)

                    # Message receive loop
                    await self._receive_loop(ws)

            except Exception as e:
                error_msg = str(e)
                print(f"[WebSocket] Connection error: {error_msg}")

                if self._running:
                    self._set_state(ConnectionState.RECONNECTING)
                    self._reconnect_attempts += 1

                    # Exponential backoff
                    delay = min(self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
                               self._max_reconnect_delay)

                    self._emit_notification(
                        "warning",
                        "Reconnecting",
                        f"Attempt {self._reconnect_attempts} in {delay:.0f}s",
                        duration=delay
                    )

                    await asyncio.sleep(delay)

        self._set_state(ConnectionState.DISCONNECTED)

    async def _send_connect(self, ws) -> bool:
        """Handle OpenClaw connect handshake with challenge-response."""

        # Wait for challenge event first
        try:
            challenge_response = await asyncio.wait_for(ws.recv(), timeout=10.0)
            challenge_data = json.loads(challenge_response)
            print(f"[WebSocket] Received: {json.dumps(challenge_data)[:200]}")

            if challenge_data.get("type") != "event" or challenge_data.get("event") != "connect.challenge":
                print(f"[WebSocket] Expected connect.challenge, got: {challenge_data.get('event', challenge_data.get('type'))}")
                return False

            challenge_payload = challenge_data.get("payload", {})
            nonce = challenge_payload.get("nonce", "")
            server_ts = challenge_payload.get("ts", int(time.time() * 1000))

        except asyncio.TimeoutError:
            print("[WebSocket] Timeout waiting for challenge")
            return False

        # Build connect params with signed challenge
        signed_at = int(time.time() * 1000)
        client_id = "cli"
        client_mode = "cli"
        role = "operator"
        scopes = ["operator.read", "operator.write", "operator.admin"]
        token = self.password or ""

        connect_params = {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": client_id,
                "version": "1.0.0",
                "platform": "linux",
                "mode": client_mode,
            },
            "role": role,
            "scopes": scopes,
        }

        # Add device with signature if crypto is available
        if CRYPTO_AVAILABLE and self._private_key:
            # Build auth payload: v2|deviceId|clientId|clientMode|role|scopes|signedAt|token|nonce
            auth_payload = self._build_auth_payload(
                nonce=nonce,
                signed_at=signed_at,
                client_id=client_id,
                client_mode=client_mode,
                role=role,
                scopes=scopes,
                token=token,
            )
            print(f"[WebSocket] Auth payload: {auth_payload}")
            signature = self._sign_challenge(auth_payload)
            connect_params["device"] = {
                "id": self._device_id,
                "publicKey": self._get_public_key_base64(),
                "signature": signature,
                "signedAt": signed_at,
                "nonce": nonce,
            }
        else:
            # Fallback - might not work without crypto
            connect_params["device"] = {
                "id": self._device_id or str(uuid.getnode()),
                "publicKey": "",
                "signature": "",
                "signedAt": signed_at,
                "nonce": nonce,
            }

        # Add auth token if provided
        if self.password:
            connect_params["auth"] = {"token": self.password}

        connect_msg = {
            "type": "req",
            "id": self._next_request_id(),
            "method": "connect",
            "params": connect_params,
        }

        await ws.send(json.dumps(connect_msg))
        print(f"[WebSocket] Sent connect request: {json.dumps(connect_params, indent=2)}")

        # Wait for connect response
        try:
            while True:
                response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                data = json.loads(response)
                print(f"[WebSocket] Received: {json.dumps(data)[:200]}")

                msg_type = data.get("type")

                if msg_type == "res":
                    # This is the response to our connect request
                    if data.get("ok"):
                        payload = data.get("payload", {})
                        print(f"[WebSocket] Authenticated. Full payload: {json.dumps(payload, default=str)[:1000]}")
                        # Store session info if provided
                        if "sessionId" in payload:
                            self._session_id = payload["sessionId"]
                        if "deviceToken" in payload:
                            print("[WebSocket] Received device token")
                        return True
                    else:
                        error = data.get("error", {})
                        error_msg = error.get('message', 'Unknown error')
                        print(f"[WebSocket] Connect failed: {error_msg}")

                        # Check for pairing required
                        if "pairing" in error_msg.lower() or "approval" in error_msg.lower():
                            print("[WebSocket] Device needs to be paired/approved on the server")

                        return False

                elif msg_type == "event":
                    # Server sent an event during connect
                    event_name = data.get("event", "")
                    print(f"[WebSocket] Got event during connect: {event_name}")

                    if event_name in ("connected", "welcome", "ready"):
                        print("[WebSocket] Connected via event")
                        return True

                    # For pairing events
                    if event_name == "device.pairing.required":
                        print("[WebSocket] Device pairing required - please approve on the server")
                        # Continue waiting for approval
                        continue

                    if event_name == "device.paired":
                        print("[WebSocket] Device paired successfully!")
                        continue

                    continue

                else:
                    print(f"[WebSocket] Unknown message type: {msg_type}")
                    continue

        except asyncio.TimeoutError:
            print("[WebSocket] Connect response timeout")
            return False

    async def _post_connect_setup(self, ws):
        """Discover sessions after connecting."""
        print("[WebSocket] Discovering sessions...")

        req_id = self._next_request_id()
        request = {
            "type": "req",
            "id": req_id,
            "method": "sessions.list",
            "params": {},
        }
        await ws.send(json.dumps(request))

        try:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(raw)

                if data.get("type") == "res" and data.get("id") == req_id:
                    if data.get("ok"):
                        payload = data.get("payload", {})
                        sessions = payload.get("sessions", [])
                        print(f"[WebSocket] Found {len(sessions)} session(s)")

                        # Pick a direct/non-heartbeat session first, fall back to first
                        target = None
                        for s in sessions:
                            kind = s.get("kind", "")
                            name = s.get("displayName", "")
                            key = s.get("key", "")
                            print(f"[WebSocket]   Session: key={key} kind={kind} name={name}")
                            # Prefer non-heartbeat direct sessions, then any direct
                            if kind == "direct" and "heartbeat" not in name:
                                target = s
                                break
                        if not target:
                            # Fall back to first session
                            for s in sessions:
                                if s.get("kind") == "direct":
                                    target = s
                                    break
                        if not target and sessions:
                            target = sessions[0]

                        if target:
                            self._session_key = target.get("key", "")
                            self._session_id = target.get("sessionId", "")
                            model = target.get("model", "unknown")
                            print(f"[WebSocket] Using session: key={self._session_key} model={model}")

                            with self._lock:
                                self._status["model"] = model
                        else:
                            print("[WebSocket] No sessions available")
                    else:
                        error = data.get("error", {})
                        print(f"[WebSocket] sessions.list failed: {error.get('message', error)}")
                    break
                else:
                    await self._handle_message(data)

        except asyncio.TimeoutError:
            print("[WebSocket] sessions.list timed out")

        if not self._session_key:
            print("[WebSocket] WARNING: No session found - commands may not work")
            return

        # Load recent chat history for the session
        await self._load_chat_history(ws)

    async def _load_chat_history(self, ws):
        """Load recent chat history for the active session."""
        req_id = self._next_request_id()
        request = {
            "type": "req",
            "id": req_id,
            "method": "chat.history",
            "params": {"sessionKey": self._session_key},
        }
        await ws.send(json.dumps(request))

        try:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(raw)

                if data.get("type") == "res" and data.get("id") == req_id:
                    if data.get("ok"):
                        payload = data.get("payload", {})
                        messages = payload.get("messages", payload.get("history", []))
                        if isinstance(payload, list):
                            messages = payload

                        loaded = 0
                        for msg in messages[-10:]:  # Last 10 messages
                            role = msg.get("role", "")
                            content = msg.get("content", "")
                            # Handle content block arrays
                            if isinstance(content, list):
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                content = "\n".join(text_parts)
                            if role and content:
                                with self._lock:
                                    self._messages.append({
                                        "role": role,
                                        "content": content,
                                        "timestamp": datetime.now(),
                                    })
                                    loaded += 1

                        if loaded:
                            print(f"[WebSocket] Loaded {loaded} messages from history")
                    else:
                        error = data.get("error", {})
                        print(f"[WebSocket] chat.history: {error.get('message', 'unavailable')}")
                    break
                else:
                    await self._handle_message(data)

        except asyncio.TimeoutError:
            print("[WebSocket] chat.history timed out")

    async def _receive_loop(self, ws):
        """Receive and process messages."""
        async for message in ws:
            if not self._running:
                break

            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError as e:
                print(f"[WebSocket] Invalid JSON: {e}")
            except Exception as e:
                print(f"[WebSocket] Message handling error: {e}")

    async def _handle_message(self, data: Dict):
        """Handle incoming message based on OpenClaw protocol."""
        msg_type = data.get("type", "")

        if msg_type == "res":
            # Response to a request we sent
            req_id = data.get("id")
            ok = data.get("ok", False)
            payload = data.get("payload", {})

            # Log important responses
            if ok and isinstance(payload, dict) and "runId" in payload:
                print(f"[WebSocket] Run started: {payload.get('runId', '?')[:12]} status={payload.get('status', '?')}")
            elif not ok:
                error = data.get("error", {})
                print(f"[WebSocket] Request {req_id} failed: {error.get('message', error)}")

            if req_id in self._pending_requests:
                future = self._pending_requests.pop(req_id)
                if not future.done():
                    future.set_result(data)

        elif msg_type == "event":
            # Server-initiated event
            event_name = data.get("event", "")
            payload = data.get("payload", {})
            await self._handle_event(event_name, payload)

        elif msg_type == "req":
            # Server is requesting something from us (rare for display client)
            method = data.get("method", "")
            print(f"[WebSocket] Received request: {method}")

    async def _handle_event(self, event_name: str, payload: Dict):
        """Handle OpenClaw events."""

        if event_name == "agent":
            # Agent events carry stream type and data
            stream = payload.get("stream", "")
            data = payload.get("data", {})
            run_id = payload.get("runId", "unknown")

            if stream == "lifecycle":
                phase = data.get("phase", "")
                if phase == "start":
                    print(f"[WebSocket] Agent run started: {run_id[:12]}")
                    with self._lock:
                        self._status["is_streaming"] = True
                        self._status["current_task"] = "Processing..."
                    if self._on_status_change:
                        try:
                            self._on_status_change(self.status)
                        except Exception as e:
                            print(f"[WebSocket] Status callback error: {e}")

                elif phase == "end":
                    print(f"[WebSocket] Agent run ended: {run_id[:12]}")
                    with self._lock:
                        if self._current_streaming:
                            self._current_streaming.complete = True
                            self._current_streaming = None
                        self._status["is_streaming"] = False
                        self._status["current_task"] = "Idle"
                    if self._on_status_change:
                        try:
                            self._on_status_change(self.status)
                        except Exception as e:
                            print(f"[WebSocket] Status callback error: {e}")

                elif phase == "error":
                    error_msg = data.get("error", data.get("message", "Agent error"))
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get("message", str(error_msg))
                    print(f"[WebSocket] Agent run error: {run_id[:12]} - {error_msg}")
                    with self._lock:
                        self._current_streaming = None
                        self._status["is_streaming"] = False
                        self._status["current_task"] = "Error"
                    self._emit_notification("error", "Agent Error", str(error_msg)[:80], duration=5.0)
                    if self._on_status_change:
                        try:
                            self._on_status_change(self.status)
                        except Exception as e:
                            print(f"[WebSocket] Status callback error: {e}")

            elif stream == "assistant":
                # Streaming text delta from assistant
                delta = data.get("delta", "")
                if delta:
                    with self._lock:
                        if self._current_streaming is None:
                            self._current_streaming = StreamingMessage(
                                id=run_id,
                                role="assistant",
                            )
                            self._status["is_streaming"] = True
                        self._current_streaming.append_chunk(delta)

                    if self._on_message_chunk:
                        try:
                            self._on_message_chunk(run_id, delta)
                        except Exception as e:
                            print(f"[WebSocket] Chunk callback error: {e}")

            elif stream == "tool":
                # Tool use events
                tool_name = data.get("tool", data.get("name", "tool"))
                tool_status = data.get("status", "")
                if tool_status == "start" or "start" in str(data.get("phase", "")):
                    self._emit_notification("info", f"Tool: {tool_name}", "Running...", duration=10.0)
                    with self._lock:
                        self._status["current_task"] = f"Running: {tool_name}"
                elif tool_status in ("end", "done", "complete"):
                    self._emit_notification("success", f"Tool: {tool_name}", "Done", duration=1.0)

            # Other agent streams (thinking, etc.) - silently ignore

        elif event_name == "chat":
            # Chat events carry message state
            state = payload.get("state", "")
            message = payload.get("message", {})
            run_id = payload.get("runId", "unknown")

            if state == "final":
                # Message complete
                role = message.get("role", "assistant")
                content_blocks = message.get("content", [])
                # Extract text from all content blocks
                text_parts = []
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                text = "\n".join(text_parts)

                completed = {
                    "role": role,
                    "content": text,
                    "timestamp": datetime.now(),
                }

                with self._lock:
                    self._current_streaming = None
                    self._status["is_streaming"] = False
                    self._messages.append(completed)
                    if len(self._messages) > self._max_messages:
                        self._messages = self._messages[-self._max_messages:]

                print(f"[WebSocket] Message complete ({len(text)} chars)")

                if self._on_message_complete:
                    try:
                        self._on_message_complete(completed)
                    except Exception as e:
                        print(f"[WebSocket] Complete callback error: {e}")

            # state == "delta" is redundant with agent assistant stream, skip it

        elif event_name == "tick":
            # Periodic heartbeat (just timestamp)
            pass

        elif event_name == "health":
            # Health check - silently ignore
            pass

        elif event_name in ("error",):
            error = payload.get("message", payload.get("error", "Unknown error"))
            self._emit_notification("error", "Error", str(error)[:50], duration=5.0)

        elif event_name in ("cancelled", "cancel"):
            self._emit_notification("warning", "Cancelled", "", duration=2.0)
            with self._lock:
                self._current_streaming = None
                self._status["is_streaming"] = False

        elif event_name == "shutdown":
            reason = payload.get("reason", "unknown")
            restart_ms = payload.get("restartExpectedMs")
            msg = f"Shutdown: {reason}"
            if restart_ms:
                msg += f" (restart in {restart_ms // 1000}s)"
            print(f"[WebSocket] {msg}")
            self._emit_notification("warning", "Gateway Shutdown", msg, duration=10.0)

        elif event_name == "presence":
            # Presence updates about connected devices - silently ignore
            pass

        elif event_name == "exec.approval.requested":
            # Tool execution needs approval
            tool = payload.get("tool", payload.get("name", "unknown"))
            self._emit_notification("warning", f"Approval: {tool}", "Needs approval", duration=10.0)

        else:
            # Truly unknown event - log it
            print(f"[WebSocket] Unknown event: {event_name}")

    async def _send_request(self, method: str, params: Dict = None) -> Optional[Dict]:
        """Send a request and wait for response."""
        if not self._websocket or not self.is_connected:
            return None

        req_id = self._next_request_id()
        request = {
            "type": "req",
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Create future for response
        future = asyncio.Future()
        self._pending_requests[req_id] = future

        try:
            await self._websocket.send(json.dumps(request))

            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=30.0)
            ok = response.get("ok", False)
            if ok:
                payload = response.get("payload", {})
                # Log chat.send responses to confirm agent started
                if method == "chat.send":
                    run_id = payload.get("runId", "?")
                    status = payload.get("status", "?")
                    print(f"[WebSocket] chat.send accepted: runId={run_id[:12]} status={status}")
            else:
                print(f"[WebSocket] Request {method} failed: {json.dumps(response.get('error', {}), default=str)[:200]}")
            return response

        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            print(f"[WebSocket] Request timeout: {method}")
            return None
        except Exception as e:
            self._pending_requests.pop(req_id, None)
            print(f"[WebSocket] Request error: {e}")
            return None

    def _build_chat_send_params(self, content: str) -> Dict:
        """Build params for chat.send with required fields."""
        params = {
            "message": content,
            "idempotencyKey": str(uuid.uuid4()),
        }
        if self._session_key:
            params["sessionKey"] = self._session_key
        return params

    async def _send_fire_and_forget(self, method: str, params: Dict):
        """Send a request without blocking the event loop for the response."""
        if not self._websocket or not self.is_connected:
            return

        req_id = self._next_request_id()
        request = {
            "type": "req",
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Register pending request so _handle_message logs the response
        future = asyncio.Future()
        self._pending_requests[req_id] = future

        try:
            await self._websocket.send(json.dumps(request))
        except Exception as e:
            self._pending_requests.pop(req_id, None)
            print(f"[WebSocket] Send error: {e}")

    def send_command(self, command: str) -> bool:
        """Send a command to OpenClaw (thread-safe)."""
        if self._loop and self.is_connected:
            params = self._build_chat_send_params(command)
            print(f"[WebSocket] Sending chat.send: {command[:80]} (session={self._session_key})")
            asyncio.run_coroutine_threadsafe(
                self._send_fire_and_forget("chat.send", params),
                self._loop
            )
            return True
        return False

    def send_message(self, message: str) -> bool:
        """Send a user message to OpenClaw (thread-safe)."""
        if self._loop and self.is_connected:
            params = self._build_chat_send_params(message)
            print(f"[WebSocket] Sending chat.send: {message[:80]} (session={self._session_key})")
            asyncio.run_coroutine_threadsafe(
                self._send_fire_and_forget("chat.send", params),
                self._loop
            )
            return True
        return False

    def cancel_current(self) -> bool:
        """Cancel the current operation (thread-safe)."""
        if self._loop and self.is_connected:
            params = {}
            if self._session_key:
                params["sessionKey"] = self._session_key
            asyncio.run_coroutine_threadsafe(
                self._send_request("chat.abort", params),
                self._loop
            )
            self._emit_notification("warning", "Cancelling...", "", duration=1.0)
            return True
        return False

    def force_reconnect(self):
        """Force a reconnection (thread-safe)."""
        if self._loop and self._websocket:
            asyncio.run_coroutine_threadsafe(
                self._websocket.close(),
                self._loop
            )
            self._emit_notification("info", "Reconnecting...", "", duration=2.0)
