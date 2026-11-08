"""LRCLIB lookup, translation and a small lyrics cache.

Everything here is blocking and runs on a worker thread (see ``worker.py``), never on
the UI thread. Based on PlayerService.qml in omarchy-super-player.

The original took the first match of: exact ``GET /api/get``, filtered
``GET /api/search``, free text ``GET /api/search?q=``. LRCLIB is crowd-sourced, so the
first match can be a user-submitted translation; here every endpoint adds candidates
and ``candidates.rank_candidates`` picks the order (synced, original script, not a
translation, duration). When nothing in a non-Latin script turns up for an artist
whose catalogue mostly is (a localized or English title), the artist's catalogue is
searched for a track of the same length. Players that report no artist go straight to
the free text search. Network failures are retried twice.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from core.widgets.services.super_player.candidates import (
    CLOSE_DELTA,
    Candidate,
    artist_script,
    candidate_from,
    rank_candidates,
)
from core.widgets.services.super_player.lrc import LyricLine, parse_lrc, parse_plain

logger = logging.getLogger("super_player")

LRCLIB_URL = "https://lrclib.net/api"
TRANSLATE_URL = "https://clients5.google.com/translate_a/t"
USER_AGENT = "yasb-super-player/1.0 (+https://github.com/enrell/omarchy-super-player)"

# Every request is bounded: abandoned after REQUEST_TIMEOUT seconds, and a reply larger
# than MAX_RESPONSE_BYTES is refused before it is parsed or cached. Real LRCLIB replies
# are ~6 KiB for an exact lookup and ~150 KiB for a 20 result search.
REQUEST_TIMEOUT = 8.0
MAX_RESPONSE_BYTES = 512 * 1024
NETWORK_RETRIES = 2
RETRY_DELAY = 1.5

# Translation requests carry the lyrics in the URL; long lyrics are sent in chunks.
MAX_TRANSLATE_CHARS = 1500

type Status = Literal["synced", "plain", "notfound", "instrumental", "error"]
type Getter = Callable[[str], tuple[int, bytes]]


@dataclass(frozen=True, slots=True)
class TrackQuery:
    title: str
    artist: str = ""
    album: str = ""
    duration: float = 0.0


@dataclass(slots=True)
class LyricsResult:
    status: Status
    lines: list[LyricLine] = field(default_factory=lambda: list[LyricLine]())
    # Duration LRCLIB reports for the match; used for progress when the player has none.
    duration: float = 0.0
    # Every acceptable LRCLIB candidate, best first; ``choice`` is the one in ``lines``.
    candidates: list[Candidate] = field(default_factory=lambda: list[Candidate]())
    choice: int = 0


def bounded_get(url: str, timeout: float = REQUEST_TIMEOUT, max_bytes: int = MAX_RESPONSE_BYTES) -> tuple[int, bytes]:
    """GET with a total deadline and a size cap.

    Returns ``(status, body)``. Every failure (timeout, network error, oversized reply)
    is reported as status 0 with an empty body, so callers have one failure path.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None and declared.isdigit() and int(declared) > max_bytes:
                logger.debug("Refused an oversized reply from %s", url)
                return 0, b""
            chunks: list[bytes] = []
            size = 0
            while chunk := response.read(16384):
                size += len(chunk)
                if size > max_bytes:
                    logger.debug("Refused an oversized reply from %s", url)
                    return 0, b""
                if time.monotonic() > deadline:
                    logger.debug("Timed out reading %s", url)
                    return 0, b""
                chunks.append(chunk)
            return int(response.status), b"".join(chunks)
    except urllib.error.HTTPError as e:
        return int(e.code), b""
    except Exception as e:
        logger.debug("Request to %s failed: %s", url, e)
        return 0, b""


def _json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError, UnicodeDecodeError:
        return None


def result_for(candidates: list[Candidate], choice: int = 0) -> LyricsResult:
    """Lines of one ranked candidate, keeping the whole list for the popup's switcher."""
    if not candidates:
        return LyricsResult("notfound")
    choice = max(0, min(choice, len(candidates) - 1))
    picked = candidates[choice]
    synced = parse_lrc(picked.synced)
    if synced:
        return LyricsResult("synced", synced, picked.duration, candidates, choice)
    if picked.plain.strip():
        return LyricsResult("plain", parse_plain(picked.plain), picked.duration, candidates, choice)
    return LyricsResult("notfound", [], picked.duration, candidates, choice)


def pick_best(results: Sequence[Any], duration: float) -> Candidate | None:
    """The best LRCLIB record of a list, or None when none fits the track."""
    ranked = rank_candidates((c for r in results if (c := candidate_from(r)) is not None), duration)
    return ranked[0] if ranked else None


def _url(path: str, **params: str) -> str:
    return f"{LRCLIB_URL}/{path}?{urllib.parse.urlencode(params)}"


def _get_with_retries(get: Getter, url: str, sleep: Callable[[float], None]) -> tuple[int, bytes]:
    status, body = get(url)
    attempts = 0
    while status == 0 and attempts < NETWORK_RETRIES:
        attempts += 1
        sleep(RETRY_DELAY)
        status, body = get(url)
    return status, body


def _records(status: int, body: bytes) -> list[Any]:
    if status != 200:
        return []
    data = _json(body)
    if isinstance(data, list):
        return list(data)  # pyright: ignore[reportUnknownArgumentType]
    return [data] if isinstance(data, dict) else []


def fetch_lyrics(
    query: TrackQuery, get: Getter = bounded_get, sleep: Callable[[float], None] = time.sleep
) -> LyricsResult:
    """Look the track up on LRCLIB and rank every candidate. Blocking; call it from a worker thread."""
    if not query.title.strip():
        return LyricsResult("notfound")

    artist = query.artist.strip()
    found: list[Candidate] = []
    instrumental = False
    answered = False

    def add(records: list[Any], source: str) -> None:
        nonlocal instrumental
        for record in records:
            candidate = candidate_from(record, source)
            if candidate is None:
                continue
            instrumental = instrumental or (candidate.instrumental and not candidate.has_lyrics)
            found.append(candidate)

    if artist:
        params = {"artist_name": artist, "track_name": query.title}
        if query.album:
            params["album_name"] = query.album
        if query.duration > 0:
            params["duration"] = str(round(query.duration))
        status, body = _get_with_retries(get, _url("get", **params), sleep)
        if status == 0:
            return LyricsResult("error")  # offline: the search endpoints would fail too
        answered = True
        add(_records(status, body), "get")

        status, body = get(_url("search", track_name=query.title, artist_name=artist))
        answered = answered or status != 0
        add(_records(status, body), "search")

    status, body = _get_with_retries(get, _url("search", q=f"{query.title} {artist}".strip()), sleep)
    answered = answered or status != 0
    add(_records(status, body), "search")

    hint: str | None = None
    close = [c for c in found if query.duration > 0 and abs(c.duration - query.duration) <= CLOSE_DELTA]
    if artist and not any(c.script != "latin" for c in close or found):
        # Only Latin lyrics under this title: the player may show a localized or English
        # title. Look at the artist's catalogue for its script and a track of this length.
        status, body = get(_url("search", q=artist))
        records = _records(status, body)
        hint = artist_script(records)
        if hint is not None and query.duration > 0:
            add([r for r in records if _close_duration(r, query.duration)], "artist")

    ranked = rank_candidates(found, query.duration, hint)
    if ranked:
        return result_for(ranked)
    if instrumental:
        return LyricsResult("instrumental")
    return LyricsResult("notfound" if answered else "error")


def _close_duration(record: Any, duration: float) -> bool:
    candidate = candidate_from(record)
    return candidate is not None and abs(candidate.duration - duration) <= CLOSE_DELTA


def parse_translation(body: bytes) -> str:
    """Reply shape: ``[["translated text", "source language"], ...]``."""
    data = _json(body)
    if not isinstance(data, list):
        return ""
    parts: list[str] = []
    for entry in data:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(entry, list) and entry and isinstance(entry[0], str):
            parts.append(entry[0])
        elif isinstance(entry, str):
            parts.append(entry)
    return "\n".join(parts)


def _chunks(texts: Sequence[str], limit: int) -> list[list[str]]:
    chunks: list[list[str]] = [[]]
    size = 0
    for text in texts:
        if chunks[-1] and size + len(text) + 1 > limit:
            chunks.append([])
            size = 0
        chunks[-1].append(text)
        size += len(text) + 1
    return chunks


def translate_lines(texts: Sequence[str], language: str, get: Getter = bounded_get) -> list[str] | None:
    """Translate every line to ``language``. Returns None when the request fails.

    Uses the same undocumented Google endpoint as the original plugin; it keeps the line
    breaks of a multi line query, so lines map back by index.
    """
    out: list[str] = []
    for chunk in _chunks(texts, MAX_TRANSLATE_CHARS):
        query = urllib.parse.urlencode(
            {"client": "dict-chrome-ex", "sl": "auto", "tl": language, "q": "\n".join(chunk)}
        )
        status, body = get(f"{TRANSLATE_URL}?{query}")
        translated = parse_translation(body) if status == 200 else ""
        if not translated and any(line.strip() for line in chunk):
            return None
        pieces = translated.split("\n")
        out.extend(pieces[i].strip() if i < len(pieces) else "" for i in range(len(chunk)))
    return out


class LyricsCache:
    """Newest-first cache of lookups, bounded because YASB outlives thousands of tracks."""

    def __init__(self, max_items: int = 50):
        self._max_items = max_items
        self._items: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str) -> Any | None:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key: str, value: Any) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)

    def pop(self, key: str) -> None:
        self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items
