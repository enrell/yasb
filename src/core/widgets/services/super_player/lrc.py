"""Parser for LRC synced lyrics, the format LRCLIB returns.

Accepted input:
    [mm:ss.xx] line              also [mm:ss], [mm:ss.x], [mm:ss.xxx] and a comma separator
    [mm:ss.xx][mm:ss.yy] line    several timestamps on one line
    [ar:...] [ti:...] [offset:+-ms]  metadata; a positive offset shows every line sooner

Ported from LrcParser.js in omarchy-super-player.
"""

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.,]\d{1,3})?)\]")
META_TAG = re.compile(r"^\[(ar|ti|al|by|re|ve|length|offset):(.*)\]$", re.IGNORECASE)


@dataclass(slots=True)
class LyricLine:
    """One lyric line. ``time`` is in seconds, -1 for unsynced lyrics."""

    time: float
    text: str
    romanized: str = ""
    translated: str = ""


def parse_lrc(text: str) -> list[LyricLine]:
    """Convert LRC text into lines ordered by time."""
    lines: list[LyricLine] = []
    offset = 0.0

    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue

        meta = META_TAG.match(line)
        if meta:
            if meta.group(1).lower() == "offset":
                try:
                    offset = int(meta.group(2).strip()) / 1000
                except ValueError:
                    offset = 0.0
            continue

        times = [int(m.group(1)) * 60 + float(m.group(2).replace(",", ".")) for m in TIME_TAG.finditer(line)]
        if not times:
            continue

        content = TIME_TAG.sub("", line).strip()
        lines.extend(LyricLine(time=t, text=content) for t in times)

    # The offset applies to the whole file, wherever the tag appears.
    if offset:
        for item in lines:
            item.time = max(0.0, item.time - offset)

    # Stable sort keeps the file order for lines that share a timestamp.
    lines.sort(key=lambda item: item.time)
    return lines


def parse_plain(text: str) -> list[LyricLine]:
    """Unsynced lyrics: one line per verse, no timestamps."""
    return [LyricLine(time=-1, text=raw.strip()) for raw in str(text).splitlines()]


def index_at(lines: Sequence[LyricLine], position: float) -> int:
    """Index of the last line with ``time <= position``, or -1 before the first line.

    Binary search: the widget calls this about ten times a second.
    """
    if not lines or lines[0].time < 0:
        return -1
    return bisect_right(lines, position, key=lambda item: item.time) - 1
