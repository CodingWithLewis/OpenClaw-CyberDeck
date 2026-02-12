"""
OpenClaw Configuration Loader.
Loads connection settings from .env file, environment, config file, or CLI args.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load from .env in current directory or home directory
    env_paths = [
        Path.cwd() / ".env",
        Path.home() / ".openclaw_display.env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"[Config] Loaded .env from {env_path}")
            break
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


@dataclass
class OpenClawConfig:
    """OpenClaw connection configuration."""

    # Connection settings
    url: str = "ws://localhost:18789"
    password: Optional[str] = None

    # Tailscale settings
    use_tailscale: bool = False
    tailscale_hostname: Optional[str] = None

    # Connection behavior
    auto_reconnect: bool = True
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    connection_timeout: float = 30.0

    # Display behavior
    streaming_refresh_ms: int = 100  # Faster refresh during streaming
    normal_refresh_ms: int = 1000    # Normal refresh rate
    notification_duration: float = 2.0

    @classmethod
    def load(
        cls,
        cli_url: Optional[str] = None,
        cli_password: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> "OpenClawConfig":
        """
        Load configuration with priority:
        1. CLI arguments (highest)
        2. Environment variables (including .env file)
        3. Config file (~/.openclaw_display.json)
        4. Defaults (lowest)

        .env file locations (first found is used):
        - ./.env (current directory)
        - ~/.openclaw_display.env
        """
        config = cls()

        # Load from config file first (lowest priority)
        config._load_from_file(config_path)

        # Load from environment (medium priority)
        config._load_from_env()

        # Apply CLI arguments (highest priority)
        if cli_url:
            config.url = cli_url
        if cli_password:
            config.password = cli_password

        return config

    def _load_from_file(self, config_path: Optional[str] = None):
        """Load settings from config file."""
        paths_to_try = []

        if config_path:
            paths_to_try.append(Path(config_path))

        # Default config locations
        paths_to_try.extend([
            Path.home() / ".openclaw_display.json",
            Path.home() / ".config" / "openclaw_display" / "config.json",
            Path("/etc/openclaw_display/config.json"),
        ])

        for path in paths_to_try:
            if path.exists():
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                        self._apply_dict(data)
                        print(f"[Config] Loaded from {path}")
                        return
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[Config] Failed to load {path}: {e}")

    def _load_from_env(self):
        """Load settings from environment variables."""
        env_mappings = {
            "OPENCLAW_URL": "url",
            "OPENCLAW_PASSWORD": "password",
            "OPENCLAW_TAILSCALE_HOST": "tailscale_hostname",
            "OPENCLAW_AUTO_RECONNECT": "auto_reconnect",
            "OPENCLAW_RECONNECT_DELAY": "reconnect_delay",
            "OPENCLAW_TIMEOUT": "connection_timeout",
        }

        for env_var, attr in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                # Type conversion
                current = getattr(self, attr)
                if isinstance(current, bool):
                    value = value.lower() in ("true", "1", "yes")
                elif isinstance(current, float):
                    value = float(value)
                elif isinstance(current, int):
                    value = int(value)

                setattr(self, attr, value)

        # Handle USE_TAILSCALE specially
        if os.environ.get("OPENCLAW_USE_TAILSCALE", "").lower() in ("true", "1", "yes"):
            self.use_tailscale = True

    def _apply_dict(self, data: dict):
        """Apply dictionary values to config."""
        mappings = {
            "url": "url",
            "password": "password",
            "use_tailscale": "use_tailscale",
            "tailscale_hostname": "tailscale_hostname",
            "auto_reconnect": "auto_reconnect",
            "reconnect_delay": "reconnect_delay",
            "max_reconnect_delay": "max_reconnect_delay",
            "connection_timeout": "connection_timeout",
            "streaming_refresh_ms": "streaming_refresh_ms",
            "normal_refresh_ms": "normal_refresh_ms",
            "notification_duration": "notification_duration",
        }

        for key, attr in mappings.items():
            if key in data:
                setattr(self, attr, data[key])

    def save(self, path: Optional[str] = None):
        """Save configuration to file."""
        if path is None:
            path = Path.home() / ".openclaw_display.json"
        else:
            path = Path(path)

        data = {
            "url": self.url,
            "use_tailscale": self.use_tailscale,
            "tailscale_hostname": self.tailscale_hostname,
            "auto_reconnect": self.auto_reconnect,
            "reconnect_delay": self.reconnect_delay,
            "max_reconnect_delay": self.max_reconnect_delay,
            "connection_timeout": self.connection_timeout,
            "streaming_refresh_ms": self.streaming_refresh_ms,
            "normal_refresh_ms": self.normal_refresh_ms,
            "notification_duration": self.notification_duration,
        }

        # Don't save password to file for security
        # (use environment variable instead)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"[Config] Saved to {path}")
        except IOError as e:
            print(f"[Config] Failed to save: {e}")

    def get_effective_url(self) -> str:
        """Get the effective WebSocket URL."""
        if self.use_tailscale and self.tailscale_hostname:
            # Could add Tailscale IP resolution here
            # For now, user should provide the full URL
            pass
        return self.url

    def __str__(self) -> str:
        return (
            f"OpenClawConfig(\n"
            f"  url={self.url}\n"
            f"  password={'***' if self.password else None}\n"
            f"  use_tailscale={self.use_tailscale}\n"
            f"  tailscale_hostname={self.tailscale_hostname}\n"
            f"  auto_reconnect={self.auto_reconnect}\n"
            f")"
        )


def create_sample_config(path: Optional[str] = None, create_env: bool = True):
    """Create sample configuration files (.env and .json)."""
    # Create .env file
    if create_env:
        env_path = Path.cwd() / ".env"
        env_content = """# OpenClaw Display Configuration
# Copy this file to your project directory or ~/.openclaw_display.env

# Required: WebSocket URL to your OpenClaw instance
# Use Tailscale IP for remote access (e.g., ws://100.x.x.x:18789)
OPENCLAW_URL=ws://localhost:18789

# Optional: Authentication password
OPENCLAW_PASSWORD=

# Optional: Tailscale settings
OPENCLAW_USE_TAILSCALE=false
OPENCLAW_TAILSCALE_HOST=

# Optional: Connection behavior
OPENCLAW_AUTO_RECONNECT=true
OPENCLAW_RECONNECT_DELAY=1.0
OPENCLAW_TIMEOUT=30.0
"""
        try:
            with open(env_path, "w") as f:
                f.write(env_content)
            print(f"[Config] Sample .env created at {env_path}")
        except IOError as e:
            print(f"[Config] Failed to create .env: {e}")

    # Create JSON config file
    if path is None:
        path = Path.home() / ".openclaw_display.json"
    else:
        path = Path(path)

    sample = {
        "url": "ws://100.x.x.x:18789",
        "use_tailscale": True,
        "tailscale_hostname": "your-openclaw-server",
        "auto_reconnect": True,
        "reconnect_delay": 1.0,
        "max_reconnect_delay": 60.0,
        "connection_timeout": 30.0,
        "streaming_refresh_ms": 100,
        "normal_refresh_ms": 1000,
        "notification_duration": 2.0,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(sample, f, indent=2)
        print(f"[Config] Sample JSON config created at {path}")
    except IOError as e:
        print(f"[Config] Failed to create JSON config: {e}")

    print("\n[Config] Configuration priority (highest to lowest):")
    print("  1. CLI arguments (--url, --password)")
    print("  2. Environment variables / .env file")
    print("  3. JSON config file (~/.openclaw_display.json)")
    print("\n[Config] Edit .env and set your OpenClaw server URL and password")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--create-sample":
        create_sample_config()
    else:
        # Test loading
        config = OpenClawConfig.load()
        print(config)
