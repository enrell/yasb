"""Romanize lyrics to Latin script, one output line per input line.

Tools, best first:
    1. pykakasi, when it is importable: Japanese readings, words split into tokens.
       It is not a YASB dependency and nothing is installed or downloaded here.
    2. Built-in tables: kana (Hepburn), Hangul (Revised Romanization, syllable by
       syllable), Cyrillic and Greek. Without pykakasi kanji are left as they are,
       like the original did with ICU only.

The original plugin used pykakasi, kakasi or ICU ``uconv``; on Windows the last two
are rarely available, so the tables stand in for ICU.
"""

import re
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any

JAPANESE = re.compile(r"[぀-ヿ一-鿿々〆]")
HANGUL = re.compile(r"[가-힣]")

# Revised Romanization of Korean, per jamo (initial, medial, final).
_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MEDIALS = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo",
    "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
]  # fmt: skip
_FINALS = [
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l",
    "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t",
]  # fmt: skip

_CYRILLIC = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґў",
        [
            "a",
            "b",
            "v",
            "g",
            "d",
            "e",
            "yo",
            "zh",
            "z",
            "i",
            "y",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "u",
            "f",
            "kh",
            "ts",
            "ch",
            "sh",
            "shch",
            "",
            "y",
            "",
            "e",
            "yu",
            "ya",
            "i",
            "yi",
            "ye",
            "g",
            "w",
        ],  # fmt: skip
        strict=True,
    )
)

_GREEK = dict(
    zip(
        "αάβγδεέζηήθιίϊΐκλμνξοόπρσςτυύϋΰφχψωώ",
        [
            "a",
            "a",
            "v",
            "g",
            "d",
            "e",
            "e",
            "z",
            "i",
            "i",
            "th",
            "i",
            "i",
            "i",
            "i",
            "k",
            "l",
            "m",
            "n",
            "x",
            "o",
            "o",
            "p",
            "r",
            "s",
            "s",
            "t",
            "y",
            "y",
            "y",
            "y",
            "f",
            "ch",
            "ps",
            "o",
            "o",
        ],  # fmt: skip
        strict=True,
    )
)


_KANA_ROWS = {
    "あいうえお": ["a", "i", "u", "e", "o"],
    "かきくけこ": ["ka", "ki", "ku", "ke", "ko"],
    "がぎぐげご": ["ga", "gi", "gu", "ge", "go"],
    "さしすせそ": ["sa", "shi", "su", "se", "so"],
    "ざじずぜぞ": ["za", "ji", "zu", "ze", "zo"],
    "たちつてと": ["ta", "chi", "tsu", "te", "to"],
    "だぢづでど": ["da", "ji", "zu", "de", "do"],
    "なにぬねの": ["na", "ni", "nu", "ne", "no"],
    "はひふへほ": ["ha", "hi", "fu", "he", "ho"],
    "ばびぶべぼ": ["ba", "bi", "bu", "be", "bo"],
    "ぱぴぷぺぽ": ["pa", "pi", "pu", "pe", "po"],
    "まみむめも": ["ma", "mi", "mu", "me", "mo"],
    "やゆよ": ["ya", "yu", "yo"],
    "らりるれろ": ["ra", "ri", "ru", "re", "ro"],
    "わをんゔ": ["wa", "o", "n", "vu"],
    "ぁぃぅぇぉ": ["a", "i", "u", "e", "o"],
}
_KANA = {kana: roman for row, romans in _KANA_ROWS.items() for kana, roman in zip(row, romans, strict=True)}
_SMALL_Y = {"ゃ": "a", "ゅ": "u", "ょ": "o"}


def _hiragana(char: str) -> str:
    """Fold katakana onto hiragana so one table covers both."""
    code = ord(char)
    return chr(code - 0x60) if 0x30A1 <= code <= 0x30F6 else char


def _romanize_kana(text: str) -> str:
    out: list[str] = []
    chars = [_hiragana(c) for c in text]
    i = 0
    while i < len(chars):
        char = chars[i]
        following = chars[i + 1] if i + 1 < len(chars) else ""
        if char in ("っ", "ッ"):
            nxt = _KANA.get(following, "")
            out.append(nxt[0] if nxt and nxt[0] not in "aeiou" else "")
        elif char == "ー" and out:
            vowels = [c for c in out[-1] if c in "aeiou"]
            out.append(vowels[-1] if vowels else "")
        elif char in _KANA and following in _SMALL_Y and _KANA[char].endswith("i") and len(_KANA[char]) > 1:
            base = _KANA[char][:-1]
            out.append(base + _SMALL_Y[following] if base in ("sh", "ch", "j") else base + "y" + _SMALL_Y[following])
            i += 1
        elif char in _KANA:
            out.append(_KANA[char])
        elif char in _SMALL_Y:
            out.append("y" + _SMALL_Y[char])
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _hangul_syllable(char: str) -> str:
    index = ord(char) - 0xAC00
    initial, rest = divmod(index, 21 * 28)
    medial, final = divmod(rest, 28)
    return _INITIALS[initial] + _MEDIALS[medial] + _FINALS[final]


def _from_table(char: str, table: dict[str, str]) -> str | None:
    lower = char.lower()
    if lower not in table:
        return None
    out = table[lower]
    return out.capitalize() if char != lower and out else out


def romanize_builtin(line: str) -> str:
    """Kana, Hangul, Cyrillic and Greek through the tables; everything else is kept.

    Hangul syllables of one word are joined; the spaces between words are already
    in the text.
    """
    out: list[str] = []
    for char in _romanize_kana(line):
        if HANGUL.match(char):
            out.append(_hangul_syllable(char))
            continue
        mapped = _from_table(char, _CYRILLIC)
        if mapped is None:
            mapped = _from_table(char, _GREEK)
        out.append(char if mapped is None else mapped)
    return "".join(out)


@cache
def _pykakasi() -> Any | None:
    try:
        import pykakasi  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None
    try:
        return pykakasi.kakasi()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    except Exception:
        return None


def available_tool() -> str:
    """Which romanizer will be used for Japanese: ``pykakasi`` or ``builtin``."""
    return "pykakasi" if _pykakasi() is not None else "builtin"


def romanize_lines(lines: Sequence[str], kakasi: Callable[[], Any | None] = _pykakasi) -> list[str]:
    """Romanize each line. Lines with nothing to convert come back unchanged."""
    converter = kakasi()
    out: list[str] = []
    for line in lines:
        if converter is not None and JAPANESE.search(line):
            try:
                tokens = converter.convert(line)
                out.append(" ".join(str(token["hepburn"]) for token in tokens if token["hepburn"]).strip())
                continue
            except Exception:
                pass
        out.append(romanize_builtin(line))
    return out
