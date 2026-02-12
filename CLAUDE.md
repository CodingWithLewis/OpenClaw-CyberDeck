# Display Project

Dual display system with touchscreen control on Raspberry Pi 4.

## Hardware

### Large Display (ILI9488 480x320)
- 18-bit color mode
- SPI bus 0, CE0
- GPIO pins: DC=24, RST=25
- SPI speed: 16MHz

### Small Display (ILI9341 320x240)
- 16-bit color mode (RGB565)
- SPI bus 0, CE1
- GPIO pins: DC=22, RST=27, BL=23
- SPI speed: 16MHz

### Touch Controller (XPT2046)
- Polling mode (IRQ pin not connected)
- Manual CS via GPIO 17
- SPI speed: 1.5MHz
- Shares SPI bus 0 with large display (requires SPI settings restore)

## Touch Calibration

Calibrated values (axes are swapped, both inverted):
- X range: 572-3676 (inverted)
- Y range: 777-3476 (inverted)
- Swap X/Y before mapping
- Pressure threshold: Z > 300

## Pin Mapping

| Function | GPIO | Physical Pin |
|----------|------|--------------|
| Large DC | 24 | 18 |
| Large RST | 25 | 22 |
| Small DC | 22 | 15 |
| Small RST | 27 | 13 |
| Small BL | 23 | 16 |
| Small CS | 7 | 26 |
| Touch CS | 17 | 11 |
| Touch IRQ | 4 | 7 (not used) |

## Key Files

- `main.py` - Entry point, coordinates displays, touch, and OpenClaw bridge
- `display_main.py` - Large display renderer (conversation view)
- `display_status.py` - Small display renderer (command panel)
- `touch_handler.py` - XPT2046 touch input with calibration
- `config.py` - Hardware pin definitions and display settings

## Notes

- Touch uses polling (checks pressure Z value) since IRQ isn't wired
- Large display SPI settings must be restored after touch reads (they share bus 0)
- Tap detection uses state transition (not-touched → touched) for instant response
- Debounce: 100ms

## OpenClaw WebSocket Protocol

### Connection Parameters

```python
{
    "minProtocol": 3,
    "maxProtocol": 3,
    "client": {
        "id": "cli",
        "version": "1.0.0",
        "platform": "linux",
        "mode": "cli"
    },
    "role": "operator",
    "scopes": ["operator.read", "operator.write", "operator.admin"],
    "device": {
        "id": "<sha256-hex-of-public-key>",
        "publicKey": "<base64-ed25519-public-key>",
        "signature": "<base64-ed25519-signature>",
        "signedAt": <timestamp-ms>,
        "nonce": "<server-provided-nonce>"
    }
}
```

### Device Identity

- `device.id`: Full SHA-256 hex digest (64 chars) of the Ed25519 public key raw bytes
- `publicKey`: Base64-encoded raw Ed25519 public key (32 bytes)
- Keys stored in `~/.openclaw_display_keys.json`

### Signature Format

The signature signs a pipe-delimited auth payload:

```
v2|deviceId|clientId|clientMode|role|scopes|signedAt|token|nonce
```

Example:
```
v2|ac69e489...|cli|cli|operator|chat,sessions|1770151418248|mytoken|uuid-nonce
```

### Handshake Flow

1. Connect to WebSocket (e.g., `wss://hostname:18789`)
2. Server sends `connect.challenge` event with `nonce` and `ts`
3. Client builds auth payload, signs with Ed25519 private key
4. Client sends `connect` request with device object
5. Server validates signature and returns success or pairing request

### Key Files

- `websocket_client.py` - WebSocket client with OpenClaw protocol
- `openclaw_bridge.py` - Bridge interface for displays
- `openclaw_config.py` - Configuration loader
