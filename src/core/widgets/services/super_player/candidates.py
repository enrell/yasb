"""Choosing among LRCLIB candidates for one track.

LRCLIB is crowd-sourced: a search returns the original lyrics next to user-submitted
translations, live versions and partial uploads. A track whose player reports an
English title (TIDAL's "A Double Suicide" for Sheena Ringo's 心中) often matches an
English translation first. The ranking here prefers, in order:

1. synced lyrics;
2. the lyrics' original script: when any candidate of the right length, or most of
   the artist's other lyrics, are in a non-Latin script (CJK, kana, Hangul, Cyrillic,
   Greek...), a candidate in that script beats a Latin-only one;
3. not a translation: a Latin candidate whose line timestamps line up with a
   non-Latin candidate's is treated as its translation;
4. a duration within 2 s, then the smallest duration gap;
5. the exact lookup over search results.

Pure Python, unit tested without the network.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.widgets.services.super_player.lrc import parse_lrc

# A large duration gap usually means another version (live, remix) whose timings
# would not match the audio.
MAX_SYNCED_DELTA = 25.0
MAX_PLAIN_DELTA = 10.0
CLOSE_DELTA = 2.0

# Share of letters in a non-Latin script that makes lyrics "non-Latin".
NON_LATIN_SHARE = 0.2
# A Latin candidate is a translation when this share of its lines start within
# TIMING_TOLERANCE seconds of a line of the non-Latin candidate.
TRANSLATION_ALIGNMENT = 0.6
TIMING_TOLERANCE = 0.75

SOURCE_PRIORITY = {"get": 0, "search": 1, "artist": 2}

_SCRIPT_PREFIXES = (
    ("CJK", "cjk"),
    ("HIRAGANA", "cjk"),
    ("KATAKANA", "cjk"),
    ("HANGUL", "hangul"),
    ("CYRILLIC", "cyrillic"),
    ("GREEK", "greek"),
    ("ARABIC", "arabic"),
    ("HEBREW", "hebrew"),
    ("THAI", "thai"),
    ("DEVANAGARI", "devanagari"),
)
_TIMESTAMP = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.,]\d{1,3})?\]")


def _letter_script(char: str) -> str | None:
    if not char.isalpha():
        return None
    try:
        name = unicodedata.name(char)
    except ValueError:
        return None
    for prefix, script in _SCRIPT_PREFIXES:
        if name.startswith(prefix):
            return script
    return "latin" if name.startswith("LATIN") else "other"


def script_of(text: str) -> str:
    """Dominant script of some lyrics: ``latin``, ``cjk``, ``hangul``, ``cyrillic``, ...

    Text counts as non-Latin when at least NON_LATIN_SHARE of its letters are; a
    Japanese song with an English chorus is still ``cjk``. Empty text is ``latin``.
    """
    counts = Counter(s for c in _TIMESTAMP.sub("", text) if (s := _letter_script(c)) is not None)
    letters = sum(counts.values())
    non_latin = {s: n for s, n in counts.items() if s not in ("latin", "other")}
    if letters and non_latin and sum(non_latin.values()) / letters >= NON_LATIN_SHARE:
        return max(non_latin, key=lambda s: non_latin[s])
    return "latin"


def has_non_latin(text: str) -> bool:
    """True when there is anything a romanizer could convert."""
    return any(_letter_script(c) not in (None, "latin", "other") for c in text)


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@dataclass(slots=True)
class Candidate:
    """One LRCLIB record, reduced to what the ranking and the popup need."""

    id: int
    track: str
    artist: str
    album: str
    duration: float
    synced: str
    plain: str
    instrumental: bool = False
    source: str = "search"
    script: str = field(default="latin")

    @property
    def has_lyrics(self) -> bool:
        return bool(self.synced.strip() or self.plain.strip())

    @property
    def lyrics(self) -> str:
        return self.synced or self.plain


def candidate_from(record: Any, source: str = "search") -> Candidate | None:
    if not isinstance(record, dict):
        return None
    data: dict[str, Any] = record  # pyright: ignore[reportUnknownVariableType]
    raw_id = data.get("id")
    candidate = Candidate(
        id=raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else 0,
        track=_text(data.get("trackName")),
        artist=_text(data.get("artistName")),
        album=_text(data.get("albumName")),
        duration=_number(data.get("duration")),
        synced=_text(data.get("syncedLyrics")),
        plain=_text(data.get("plainLyrics")),
        instrumental=data.get("instrumental") is True,
        source=source,
    )
    candidate.script = script_of(candidate.lyrics)
    return candidate


def _acceptable(candidate: Candidate, duration: float) -> bool:
    if not candidate.has_lyrics:
        return False
    if duration <= 0:
        return True
    limit = MAX_SYNCED_DELTA if candidate.synced.strip() else MAX_PLAIN_DELTA
    return abs(candidate.duration - duration) <= limit


def looks_like_translation(latin: Candidate, original: Candidate) -> bool:
    """A Latin candidate timed line for line like a non-Latin one is its translation."""
    if latin.script != "latin" or original.script == "latin" or not latin.synced or not original.synced:
        return False
    ours = [line.time for line in parse_lrc(latin.synced) if line.text]
    theirs = sorted(line.time for line in parse_lrc(original.synced) if line.text)
    if len(ours) < 3 or not theirs:
        return False
    if not 0.6 <= len(ours) / len(theirs) <= 1.6:
        return False
    aligned = sum(1 for t in ours if any(abs(t - u) <= TIMING_TOLERANCE for u in theirs))
    return aligned / len(ours) >= TRANSLATION_ALIGNMENT


def preferred_script(candidates: Sequence[Candidate], duration: float, artist_hint: str | None = None) -> str | None:
    """The non-Latin script to favour, if the evidence points to one."""
    close = [c for c in candidates if duration > 0 and abs(c.duration - duration) <= CLOSE_DELTA]
    pool = close or list(candidates)
    scripts = Counter(c.script for c in pool if c.script != "latin")
    if scripts:
        return scripts.most_common(1)[0][0]
    if artist_hint and artist_hint != "latin":
        return artist_hint
    return None


def artist_script(records: Iterable[Any]) -> str | None:
    """Script most of an artist's lyrics on LRCLIB are written in, or None if unclear."""
    scripts = Counter(c.script for r in records if (c := candidate_from(r)) is not None and c.has_lyrics)
    total = sum(scripts.values())
    if total < 3:
        return None
    script, count = scripts.most_common(1)[0]
    return script if count / total >= 0.5 else None


def _lyrics_signature(candidate: Candidate) -> str:
    """Same lyrics uploaded twice (different album tag, rounding) collapse to one choice."""
    words = re.sub(r"\s+", " ", _TIMESTAMP.sub("", candidate.lyrics)).strip().casefold()
    return f"{bool(candidate.synced)}|{words[:400]}"


def rank_candidates(
    candidates: Iterable[Candidate], duration: float, artist_hint: str | None = None
) -> list[Candidate]:
    """Acceptable candidates, best first, without duplicate lyrics."""
    pool = [c for c in candidates if _acceptable(c, duration)]
    wanted = preferred_script(pool, duration, artist_hint)
    originals = [c for c in pool if c.script != "latin"]

    def score(c: Candidate) -> tuple[int, int, int, int, float, int]:
        delta = abs(c.duration - duration) if duration > 0 else 0.0
        translation = c.script == "latin" and any(looks_like_translation(c, o) for o in originals)
        return (
            0 if c.synced.strip() else 1,
            0 if wanted is None or c.script == wanted else 1,
            1 if translation else 0,
            0 if delta <= CLOSE_DELTA else 1,
            delta,
            SOURCE_PRIORITY.get(c.source, 3),
        )

    ranked: list[Candidate] = []
    seen: set[str] = set()
    for candidate in sorted(pool, key=score):
        signature = _lyrics_signature(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        ranked.append(candidate)
    return ranked
