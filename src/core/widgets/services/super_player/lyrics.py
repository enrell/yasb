"""LRCLIB lookup, translation and a small lyrics cache.

Everything here is blocking and runs on a worker thread (see ``worker.py``), never on
the UI thread. Ported from PlayerService.qml in omarchy-super-player.

Lookup order, as in the original:
    1. exact ``GET /api/get`` (artist + track, plus album and duration when known)
    2. filtered ``GET /api/search`` (track + artist)
    3. free text ``GET /api/search?q=``
Players that report no artist go straight to the free text search, since LRCLIB
rejects an empty artist. Network failures are retried twice.
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

# A large duration gap usually means another version (live, remix) whose timings
# would not match the audio.
MAX_SYNCED_DELTA = 25.0
MAX_PLAIN_DELTA = 10.0

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


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def pick_best(results: Sequence[Any], duration: float) -> dict[str, Any] | None:
    """Pick the best search candidate: synced lyrics first, then the closest duration."""
    best_synced: dict[str, Any] | None = None
    best_synced_delta = float("inf")
    best_plain: dict[str, Any] | None = None
    best_plain_delta = float("inf")

    for result in results:
        if not isinstance(result, dict):
            continue
        candidate: dict[str, Any] = result  # pyright: ignore[reportUnknownVariableType]
        delta = abs(_number(candidate.get("duration")) - duration)
        if _text(candidate.get("syncedLyrics")):
            if delta < best_synced_delta:
                best_synced, best_synced_delta = candidate, delta
        elif _text(candidate.get("plainLyrics")):
            if delta < best_plain_delta:
                best_plain, best_plain_delta = candidate, delta

    if best_synced is not None and (duration <= 0 or best_synced_delta <= MAX_SYNCED_DELTA):
        return best_synced
    if best_plain is not None and (duration <= 0 or best_plain_delta <= MAX_PLAIN_DELTA):
        return best_plain
    return None


def result_from_api(data: Any) -> LyricsResult:
    """Turn one LRCLIB record into lines."""
    if not isinstance(data, dict):
        return LyricsResult("error")
    record: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    duration = _number(record.get("duration"))
    synced = parse_lrc(_text(record.get("syncedLyrics")))
    if synced:
        return LyricsResult("synced", synced, duration)
    plain = _text(record.get("plainLyrics"))
    if plain.strip():
        return LyricsResult("plain", parse_plain(plain), duration)
    if record.get("instrumental") is True:
        return LyricsResult("instrumental", [], duration)
    return LyricsResult("notfound", [], duration)


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


def fetch_lyrics(
    query: TrackQuery, get: Getter = bounded_get, sleep: Callable[[float], None] = time.sleep
) -> LyricsResult:
    """Look the track up on LRCLIB. Blocking; call it from a worker thread."""
    if not query.title.strip():
        return LyricsResult("notfound")

    artist = query.artist.strip()

    if artist:
        params = {"artist_name": artist, "track_name": query.title}
        if query.album:
            params["album_name"] = query.album
        if query.duration > 0:
            params["duration"] = str(round(query.duration))
        status, body = _get_with_retries(get, _url("get", **params), sleep)
        if status == 200:
            result = result_from_api(_json(body))
            if result.status != "error":
                return result
        if status == 0:
            return LyricsResult("error")  # offline: the search endpoints would fail too

        status, body = get(_url("search", track_name=query.title, artist_name=artist))
        if status == 200:
            data = _json(body)
            best = pick_best(data if isinstance(data, list) else [], query.duration)  # pyright: ignore[reportUnknownArgumentType]
            if best is not None:
                return result_from_api(best)

    status, body = _get_with_retries(get, _url("search", q=f"{query.title} {artist}".strip()), sleep)
    if status == 200:
        data = _json(body)
        best = pick_best(data if isinstance(data, list) else [], query.duration)  # pyright: ignore[reportUnknownArgumentType]
        return result_from_api(best) if best is not None else LyricsResult("notfound")
    return LyricsResult("error" if status == 0 else "notfound")


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
