"""Player selection and the lyrics sync clock.

Pure Python so it can be unit tested without GSMTC. Ported from PlayerService.qml in
omarchy-super-player.
"""

import os
from collections.abc import Callable, Sequence
from typing import Protocol

AUTO_SOURCES = {"", "auto"}

# Re-anchor the local clock only on a big jump (seek, loop, restart). Smaller
# differences are noise from the player and would make the highlight flicker at
# line boundaries.
RESYNC_THRESHOLD = 1.5


class SessionLike(Protocol):
    """The fields of ``SessionState`` this module reads."""

    app_id: str
    title: str
    artist: str
    album: str
    duration: float
    current_pos: float
    is_playing: bool
    last_update_time: float
    timeline_enabled: bool


def _matches_source(app_id: str, source: str, name_of: Callable[[str], str | None] | None) -> bool:
    wanted = source.strip().casefold()
    candidate = app_id.casefold()
    if candidate == wanted or os.path.splitext(candidate)[0] == wanted:
        return True
    if name_of is not None:
        name = name_of(app_id)
        if name and name.casefold() == wanted:
            return True
    return False


def pick_session[S: SessionLike](
    sessions: Sequence[S],
    source: str = "auto",
    system_current: str | None = None,
    name_of: Callable[[str], str | None] | None = None,
) -> S | None:
    """Choose the session to follow.

    A pinned ``source`` (an AUMID such as ``Spotify.exe``, the exe name without
    extension, or the app's display name) wins when it is running. Otherwise, as in
    the original "Auto": the player that is playing (Windows' current session first),
    then Windows' current session, then the first one available.
    """
    if not sessions:
        return None

    if source.strip().casefold() not in AUTO_SOURCES:
        for session in sessions:
            if _matches_source(session.app_id, source, name_of):
                return session

    playing = [s for s in sessions if s.is_playing]
    for session in playing:
        if session.app_id == system_current:
            return session
    if playing:
        return playing[0]
    for session in sessions:
        if session.app_id == system_current:
            return session
    return sessions[0]


def has_timeline(session: SessionLike) -> bool:
    """True when the player publishes a usable position and length."""
    return session.duration > 0 and session.last_update_time > 0


def can_seek(session: SessionLike) -> bool:
    return has_timeline(session) and session.timeline_enabled


def track_key(session: SessionLike) -> str:
    """Identifies a track for the lyrics cache. Empty while the player has no title."""
    if not session.title.strip():
        return ""
    return "␟".join((session.title.strip(), session.artist.strip(), session.album.strip()))


class SyncClock:
    """Position used to highlight the current line.

    With a timeline it follows the player, re-anchoring only on jumps larger than
    ``RESYNC_THRESHOLD``. Players that publish no timeline (some browsers) get a local
    clock that starts when the track changes and runs while it plays, which is an
    estimate: it is right for tracks that start from the beginning.
    """

    def __init__(self) -> None:
        self.position = 0.0
        self._last_tick: float | None = None

    def reset(self, position: float = 0.0) -> None:
        self.position = max(0.0, position)
        self._last_tick = None

    def seek(self, position: float) -> None:
        self.position = max(0.0, position)

    def tick(self, now: float, playing: bool, reported: float | None = None, rate: float = 1.0) -> float:
        if playing and self._last_tick is not None:
            self.position += max(0.0, now - self._last_tick) * rate
        self._last_tick = now
        if reported is not None and abs(reported - self.position) > RESYNC_THRESHOLD:
            self.position = max(0.0, reported)
        return self.position
