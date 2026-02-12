"""
Configuration for OpenClaw Dual Display Command Center.
Pin mappings, colors, fonts, and display settings.

Uses raw spidev + RPi.GPIO instead of luma.lcd.
"""

# Large Display (ILI9488 480x320) - CE0
LARGE_DISPLAY = {
    "width": 480,
    "height": 320,
    "spi_bus": 0,
    "spi_device": 0,  # CE0
    "dc_pin": 24,
    "rst_pin": 25,
    "spi_speed_hz": 16000000,  # 16MHz
}

# Small Display (ILI9341 320x240) - CE1
SMALL_DISPLAY = {
    "width": 320,
    "height": 240,
    "spi_bus": 0,
    "spi_device": 1,  # CE1
    "dc_pin": 22,
    "rst_pin": 27,
    "bl_pin": 23,  # Backlight
    "spi_speed_hz": 16000000,  # 16MHz
}

# Touch Controller (XPT2046)
TOUCH = {
    "cs_pin": 17,  # Manual chip select via GPIO
    "spi_speed_hz": 1500000,  # 1.5MHz for touch reads
    "min_pressure": 300,  # Minimum Z value to count as touch
    # Calibrated values (axes are swapped, both inverted)
    "x_min": 572,
    "x_max": 3676,
    "y_min": 777,
    "y_max": 3476,
    "swap_xy": True,
    "invert_x": True,
    "invert_y": True,
}

# Rotary Encoder (KY-040 or similar)
ROTARY_ENCODER = {
    "clk_pin": 5,
    "dt_pin": 6,
    "sw_pin": 13,
    "bouncetime_rotation": 2,   # ms - very short for responsive rotation
    "bouncetime_button": 300,   # ms - longer for button debounce
}

# 16x2 I2C Character LCD (PCF8574 expander)
CHARACTER_LCD = {
    "i2c_address": 0x27,
    "i2c_port": 1,
    "cols": 16,
    "rows": 2,
    "scroll_delay": 0.3,       # seconds between scroll steps
    "update_interval": 2.5,    # seconds between state syncs
}

# Bezel border - inset content from screen edges (pixels)
# Large display: uniform 30px border
BEZEL_BORDER = 30
# Small display: per-side borders (left, top, right, bottom)
SMALL_BEZEL = {"left": 0, "top": 20, "right": 20, "bottom": 20}

# GPIO pins to cleanup (NO SPI pins 9, 10, 11)
GPIO_PINS = [24, 25, 22, 27, 23, 17, 5, 6, 13]

# Color Scheme (RGB tuples)
COLORS = {
    "background": (0, 0, 0),           # #000000 - Pure black
    "accent": (239, 68, 68),          # #ef4444 (red)
    "user_bubble": (59, 130, 246),    # #3b82f6 (blue)
    "assistant_bubble": (75, 85, 99), # #4b5563 (gray)
    "text_primary": (255, 255, 255),  # white
    "text_secondary": (156, 163, 175),# #9ca3af (gray)
    "success": (34, 197, 94),         # #22c55e (green)
    "error": (239, 68, 68),           # #ef4444 (red)
    "warning": (234, 179, 8),         # #eab308 (yellow)
}

# Font Configuration
FONTS = {
    "default_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "bold_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "mono_path": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "size_small": 12,
    "size_medium": 16,
    "size_large": 20,
    "size_title": 24,
}

# Conversation Display Settings
CONVERSATION = {
    "max_messages": 50,
    "bubble_padding": 8,
    "bubble_margin": 6,
    "bubble_radius": 10,
    "max_bubble_width_ratio": 0.75,  # 75% of screen width
    "timestamp_format": "%H:%M",
}

# Status Dashboard Settings
STATUS = {
    "refresh_interval": 1.0,  # seconds
    "card_padding": 8,
    "card_margin": 6,
}

# Demo Mode Settings
DEMO = {
    "message_interval": 3.0,  # seconds between new messages
    "status_change_interval": 2.0,  # seconds between status updates
}

# OpenClaw Connection Settings
OPENCLAW = {
    "default_url": "ws://localhost:18789",
    "connection_timeout": 30.0,  # seconds
    "reconnect_delay": 1.0,  # initial delay in seconds
    "max_reconnect_delay": 60.0,  # max delay between reconnects
    "auto_reconnect": True,
}

# Streaming Display Settings
STREAMING = {
    "refresh_interval_ms": 100,  # Faster refresh during streaming (milliseconds)
    "normal_refresh_interval_ms": 1000,  # Normal refresh when not streaming
    "cursor_char": "\u2588",  # Block cursor for streaming indicator
    "cursor_blink_ms": 500,  # Cursor blink interval
}

# Notification Settings
NOTIFICATIONS = {
    "default_duration": 2.0,  # seconds
    "info_duration": 2.0,
    "success_duration": 1.5,
    "warning_duration": 3.0,
    "error_duration": 5.0,
    "persistent_types": ["connection_lost"],  # These stay until dismissed
    "max_visible": 3,  # Max notifications visible at once
    "banner_height": 35,  # Height of notification banner in pixels
    "fade_duration": 0.3,  # Fade animation duration
}

# Notification Colors
NOTIFICATION_COLORS = {
    "info": (59, 130, 246),      # Blue
    "success": (34, 197, 94),    # Green
    "warning": (234, 179, 8),    # Yellow
    "error": (239, 68, 68),      # Red
}

# Cyberpunk Theme Colors (RGB tuples)
CYBERPUNK_COLORS = {
    "background": (0, 0, 0),             # #000000 - Pure black
    "panel_bg": (15, 15, 25),           # #0f0f19 - Slightly lighter panel
    "panel_border": (30, 30, 45),       # Border for panels

    # Primary neon colors
    "neon_cyan": (0, 255, 255),         # #00ffff - Primary accent
    "hot_pink": (255, 0, 102),          # #ff0066 - Secondary accent
    "electric_purple": (191, 0, 255),   # #bf00ff - Tertiary accent

    # Status colors
    "amber": (255, 170, 0),             # #ffaa00 - Warning/running
    "neon_green": (0, 255, 102),        # #00ff66 - Success
    "neon_red": (255, 0, 51),           # #ff0033 - Error

    # Text colors
    "text_primary": (238, 238, 255),    # #eeeeff - Main text
    "text_dim": (68, 119, 119),         # #447777 - Dimmed text
    "text_secondary": (100, 150, 150),  # Secondary text
}

# Sprite paths
SPRITES = {
    "molty_dir": "assets/sprites",
}

# Cyberpunk UI Layout (large display 480x320)
CYBERPUNK_LAYOUT = {
    "molty_panel_width": 160,           # Left panel for Molty
    "activity_panel_x": 160,            # Right panel starts here
    "header_height": 30,
    "footer_height": 20,
    "molty_position": (40, 50),         # Molty sprite position
    "molty_label_y": 140,               # State label Y position
}

# Display Commands (shared)
CMD_SWRESET = 0x01
CMD_SLPOUT = 0x11
CMD_NORON = 0x13
CMD_DISPON = 0x29
CMD_CASET = 0x2A
CMD_PASET = 0x2B
CMD_RAMWR = 0x2C
CMD_MADCTL = 0x36
CMD_COLMOD = 0x3A
