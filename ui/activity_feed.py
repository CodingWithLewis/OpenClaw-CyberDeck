"""
Activity Feed for the large display.
Shows recent activities with colored type indicators.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from PIL import Image, ImageDraw

from .cyberpunk_theme import COLORS, CyberpunkTheme


@dataclass
class ActivityEntry:
    """Single activity entry in the feed."""
    timestamp: datetime
    type: str       # tool, message, status, error, notification
    title: str
    detail: str = ""
    status: str = "done"  # done, running, fail

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


# Type to color mapping
TYPE_COLORS = {
    "tool": COLORS["type_tool"],           # Cyan
    "message": COLORS["type_message"],     # Hot pink
    "status": COLORS["type_status"],       # Electric purple
    "error": COLORS["type_error"],         # Neon red
    "notification": COLORS["type_notification"],  # Amber
}

# Status to color mapping (for status indicator)
STATUS_COLORS = {
    "done": COLORS["neon_green"],
    "running": COLORS["amber"],
    "fail": COLORS["neon_red"],
}


class ActivityFeed:
    """
    Activity feed renderer for the large display.
    Shows recent activities with type-coded color bars.
    """

    MAX_VISIBLE = 5
    ENTRY_HEIGHT = 54

    def __init__(self, theme: CyberpunkTheme = None):
        """
        Initialize the activity feed.

        Args:
            theme: CyberpunkTheme instance (creates one if not provided)
        """
        self.theme = theme or CyberpunkTheme()
        self.entries: List[ActivityEntry] = []
        self._max_entries = 20  # Keep more in memory for scrolling

    def add_entry(self, type_: str, title: str, detail: str = "", status: str = "done"):
        """
        Add a new activity entry.

        Args:
            type_: Entry type (tool, message, status, error, notification)
            title: Main title text
            detail: Optional detail text
            status: Entry status (done, running, fail)
        """
        entry = ActivityEntry(
            timestamp=datetime.now(),
            type=type_,
            title=title,
            detail=detail,
            status=status,
        )
        self.entries.append(entry)

        # Trim old entries
        if len(self.entries) > self._max_entries:
            self.entries = self.entries[-self._max_entries:]

    def update_latest_status(self, status: str):
        """Update the status of the most recent entry."""
        if self.entries:
            self.entries[-1].status = status

    def clear(self):
        """Clear all entries."""
        self.entries = []

    def render(self, draw: ImageDraw.Draw, rect: tuple, status_text: str = "Waiting for commands...", scroll_offset: int = 0):
        """
        Render the activity feed.

        Args:
            draw: ImageDraw object
            rect: (x, y, width, height) rectangle to render in
            status_text: Footer status text
            scroll_offset: Number of entries to scroll back (0 = newest at top)
        """
        x, y, width, height = rect

        # Background panel
        draw.rectangle(
            [x, y, x + width, y + height],
            fill=COLORS["panel_bg"]
        )

        # Header
        header_height = 30
        self._draw_header(draw, x, y, width, header_height)

        # Entries area
        entries_y = y + header_height
        entries_height = height - header_height - 20  # Leave room for footer

        # Calculate visible entries with scroll offset
        total_entries = len(self.entries)
        if total_entries > 0:
            # Clamp scroll_offset to valid range
            max_scroll = max(0, total_entries - self.MAX_VISIBLE)
            scroll_offset = max(0, min(scroll_offset, max_scroll))

            # Calculate start index for visible window
            # scroll_offset=0 shows newest, higher values show older entries
            end_idx = total_entries - scroll_offset
            start_idx = max(0, end_idx - self.MAX_VISIBLE)

            visible_entries = list(reversed(self.entries[start_idx:end_idx]))
        else:
            visible_entries = []

        entry_y = entries_y + 2

        for i, entry in enumerate(visible_entries):
            if entry_y + self.ENTRY_HEIGHT > entries_y + entries_height:
                break
            self._draw_entry(draw, entry, x + 4, entry_y, width - 8, self.ENTRY_HEIGHT - 4)
            entry_y += self.ENTRY_HEIGHT

        # Footer status bar
        footer_y = y + height - 20
        self._draw_footer(draw, x, footer_y, width, 20, status_text)

    def _draw_header(self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int):
        """Draw the activity feed header."""
        # Header background
        draw.rectangle(
            [x, y, x + width, y + height],
            fill=COLORS["panel_bg"]
        )

        # Title
        font = self.theme.get_font("bold", "header")
        draw.text(
            (x + 10, y + 6),
            "ACTIVITY",
            font=font,
            fill=COLORS["neon_cyan"]
        )

        # Timestamp (right side)
        time_str = datetime.now().strftime("%H:%M:%S")
        time_font = self.theme.get_font("mono", "small")
        time_bbox = time_font.getbbox(time_str)
        time_width = time_bbox[2] - time_bbox[0]
        draw.text(
            (x + width - time_width - 10, y + 8),
            time_str,
            font=time_font,
            fill=COLORS["text_dim"]
        )

        # Separator line
        draw.line(
            [(x, y + height - 1), (x + width, y + height - 1)],
            fill=COLORS["neon_cyan"],
            width=1
        )

    def _draw_entry(self, draw: ImageDraw.Draw, entry: ActivityEntry,
                    x: int, y: int, width: int, height: int):
        """Draw a single activity entry."""
        # Entry background
        draw.rectangle(
            [x, y, x + width, y + height],
            fill=(20, 20, 28)
        )

        # Color bar on left (4px wide)
        bar_width = 4
        bar_color = TYPE_COLORS.get(entry.type, COLORS["neon_cyan"])
        draw.rectangle(
            [x, y, x + bar_width, y + height],
            fill=bar_color
        )

        # Status dot (right side)
        status_color = STATUS_COLORS.get(entry.status, COLORS["text_dim"])
        dot_x = x + width - 12
        dot_y = y + height // 2
        dot_size = 6

        # Glow effect for running status
        if entry.status == "running":
            draw.ellipse(
                [dot_x - dot_size - 2, dot_y - dot_size - 2,
                 dot_x + dot_size + 2, dot_y + dot_size + 2],
                fill=(*status_color[:3], 60)
            )

        draw.ellipse(
            [dot_x - dot_size//2, dot_y - dot_size//2,
             dot_x + dot_size//2, dot_y + dot_size//2],
            fill=status_color
        )

        # Text area (after bar, before status dot)
        text_x = x + bar_width + 8
        text_width = width - bar_width - 30  # Leave room for dot

        # Title
        title_font = self.theme.get_font("bold", "small")
        title = self._truncate_text(entry.title, title_font, text_width)
        draw.text(
            (text_x, y + 6),
            title,
            font=title_font,
            fill=COLORS["text_primary"]
        )

        # Detail (dimmed, smaller)
        if entry.detail:
            detail_font = self.theme.get_font("regular", "small")
            detail = self._truncate_text(entry.detail, detail_font, text_width)
            draw.text(
                (text_x, y + 22),
                detail,
                font=detail_font,
                fill=COLORS["text_dim"]
            )

        # Timestamp (bottom right, very small)
        time_str = entry.timestamp.strftime("%H:%M")
        time_font = self.theme.get_font("mono", "small")
        draw.text(
            (text_x, y + height - 14),
            time_str,
            font=time_font,
            fill=COLORS["text_dim"]
        )

    def _draw_footer(self, draw: ImageDraw.Draw, x: int, y: int,
                     width: int, height: int, status_text: str):
        """Draw the footer status bar."""
        # Footer background
        draw.rectangle(
            [x, y, x + width, y + height],
            fill=COLORS["panel_bg"]
        )

        # Separator line
        draw.line(
            [(x, y), (x + width, y)],
            fill=COLORS["panel_border"],
            width=1
        )

        # Status text with blinking cursor indicator
        font = self.theme.get_font("mono", "small")

        # Cursor block
        draw.rectangle(
            [x + 8, y + 4, x + 12, y + height - 4],
            fill=COLORS["neon_cyan"]
        )

        draw.text(
            (x + 18, y + 3),
            status_text,
            font=font,
            fill=COLORS["text_secondary"]
        )

    def _truncate_text(self, text: str, font, max_width: int) -> str:
        """Truncate text to fit within max_width."""
        if not text:
            return ""

        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            return text

        # Binary search for truncation point
        ellipsis = "..."
        for i in range(len(text), 0, -1):
            truncated = text[:i] + ellipsis
            bbox = font.getbbox(truncated)
            if bbox[2] - bbox[0] <= max_width:
                return truncated

        return ellipsis
