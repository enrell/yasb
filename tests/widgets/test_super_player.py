# pyright: reportPrivateUsage=false

import http.server
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel

from core.validation.widgets.yasb.super_player import SuperPlayerConfig
from core.widgets.services.super_player import lyrics as lyrics_mod
from core.widgets.services.super_player.lrc import LyricLine, index_at, parse_lrc, parse_plain
from core.widgets.services.super_player.lyrics import (
    LyricsCache,
    LyricsResult,
    TrackQuery,
    bounded_get,
    fetch_lyrics,
    parse_translation,
    pick_best,
    translate_lines,
)
from core.widgets.services.super_player.player import SyncClock, can_seek, has_timeline, pick_session, track_key
from core.widgets.services.super_player.romanize import romanize_builtin, romanize_lines

# --- LRC parsing -----------------------------------------------------------------------


def test_parses_timestamps_in_every_accepted_format():
    lines = parse_lrc("[00:01.50] one\n[00:02] two\n[00:03.5] three\n[00:04.250] four\n[00:05,75] five")
    assert [(round(line.time, 3), line.text) for line in lines] == [
        (1.5, "one"),
        (2.0, "two"),
        (3.5, "three"),
        (4.25, "four"),
        (5.75, "five"),
    ]


def test_minutes_above_an_hour_and_three_digits():
    assert parse_lrc("[61:00.00] late")[0].time == 3660.0
    assert parse_lrc("[100:00.00] later")[0].time == 6000.0


def test_a_line_with_several_timestamps_repeats_and_lines_are_sorted():
    lines = parse_lrc("[00:10.00][00:30.00] chorus\n[00:20.00] verse")
    assert [(line.time, line.text) for line in lines] == [(10.0, "chorus"), (20.0, "verse"), (30.0, "chorus")]


def test_metadata_blank_and_untimed_lines_are_skipped():
    text = "[ar: Someone]\n[ti: Song]\n[length: 03:20]\n\nplain words\n[00:01.00] sung"
    assert [line.text for line in parse_lrc(text)] == ["sung"]


def test_empty_timed_lines_are_kept_as_instrumental_breaks():
    lines = parse_lrc("[00:01.00] a\n[00:05.00]\n[00:09.00] b")
    assert [line.text for line in lines] == ["a", "", "b"]


def test_positive_offset_shows_lines_sooner_wherever_the_tag_is():
    lines = parse_lrc("[00:10.00] a\n[offset:+500]\n[00:00.20] b")
    assert [(round(line.time, 3), line.text) for line in lines] == [(0.0, "b"), (9.5, "a")]
    assert parse_lrc("[offset:-1000]\n[00:01.00] a")[0].time == 2.0


def test_invalid_offset_is_ignored():
    assert parse_lrc("[offset:abc]\n[00:01.00] a")[0].time == 1.0


def test_plain_lyrics_have_no_timestamps():
    assert parse_plain("one\n two \n") == [LyricLine(-1, "one"), LyricLine(-1, "two")]


# --- line sync at a given position -----------------------------------------------------

LINES = parse_lrc("[00:05.00] a\n[00:10.00] b\n[00:15.00] c")


@pytest.mark.parametrize(
    ("position", "index"),
    [(0.0, -1), (4.99, -1), (5.0, 0), (9.99, 0), (10.0, 1), (14.0, 1), (15.0, 2), (999.0, 2)],
)
def test_index_at_position(position: float, index: int):
    assert index_at(LINES, position) == index


def test_index_at_without_lines_or_with_unsynced_lyrics():
    assert index_at([], 10.0) == -1
    assert index_at(parse_plain("a\nb"), 10.0) == -1


def test_clock_follows_the_player_and_ignores_small_noise():
    clock = SyncClock()
    clock.reset(10.0)
    assert clock.tick(100.0, playing=True, reported=10.0) == 10.0
    assert clock.tick(100.5, playing=True, reported=10.2) == pytest.approx(10.5)  # within 1.5 s: noise
    assert clock.tick(101.0, playing=True, reported=60.0) == 60.0  # a seek: re-anchor


def test_clock_stops_while_paused():
    clock = SyncClock()
    clock.reset(3.0)
    clock.tick(10.0, playing=False, reported=3.0)
    assert clock.tick(20.0, playing=False, reported=3.0) == 3.0


def test_clock_runs_locally_without_a_timeline():
    clock = SyncClock()
    clock.reset()
    clock.tick(50.0, playing=True)
    assert clock.tick(52.0, playing=True) == pytest.approx(2.0)
    assert clock.tick(54.0, playing=True, rate=0.5) == pytest.approx(3.0)
    clock.seek(30.0)
    assert clock.tick(55.0, playing=True) == pytest.approx(31.0)


# --- player selection ------------------------------------------------------------------


@dataclass
class FakeSession:
    app_id: str
    is_playing: bool = False
    title: str = "Song"
    artist: str = "Artist"
    album: str = ""
    duration: float = 0.0
    current_pos: float = 0.0
    last_update_time: float = 0.0
    timeline_enabled: bool = False
    is_current: bool = False
    playback_rate: float = 1.0
    controls_play_enabled: bool = True
    controls_prev_enabled: bool = True
    controls_next_enabled: bool = True
    thumbnail: Any = None


def _ids(session: FakeSession | None) -> str | None:
    return session.app_id if session else None


def test_no_sessions_means_no_player():
    assert pick_session([], "auto") is None


def test_auto_follows_the_playing_player():
    sessions = [FakeSession("Spotify.exe"), FakeSession("chrome", is_playing=True)]
    assert _ids(pick_session(sessions, "auto")) == "chrome"


def test_auto_prefers_windows_current_session_among_playing_ones():
    sessions = [FakeSession("a", is_playing=True), FakeSession("b", is_playing=True)]
    assert _ids(pick_session(sessions, "auto", system_current="b")) == "b"


def test_auto_without_playback_falls_back_to_windows_current_then_first():
    sessions = [FakeSession("a"), FakeSession("b")]
    assert _ids(pick_session(sessions, "Auto", system_current="b")) == "b"
    assert _ids(pick_session(sessions, "")) == "a"


@pytest.mark.parametrize("source", ["Spotify.exe", "spotify.exe", "Spotify", "Spotify Music"])
def test_pinned_source_wins_over_the_playing_player(source: str):
    sessions = [FakeSession("chrome", is_playing=True), FakeSession("Spotify.exe")]

    def name_of(app_id: str) -> str | None:
        return {"Spotify.exe": "Spotify Music"}.get(app_id)

    assert _ids(pick_session(sessions, source, name_of=name_of)) == "Spotify.exe"


def test_pinned_source_that_is_not_running_falls_back_to_auto():
    sessions = [FakeSession("Spotify.exe"), FakeSession("chrome", is_playing=True)]
    assert _ids(pick_session(sessions, "vlc")) == "chrome"


def test_timeline_and_track_key():
    no_timeline = FakeSession("chrome")
    assert not has_timeline(no_timeline) and not can_seek(no_timeline)
    with_timeline = FakeSession("s", duration=200, last_update_time=1.0, timeline_enabled=True)
    assert has_timeline(with_timeline) and can_seek(with_timeline)
    assert not can_seek(FakeSession("s", duration=200, last_update_time=1.0))
    assert track_key(FakeSession("s", title=" ")) == ""
    assert track_key(FakeSession("s", title="T", artist="A", album="B")) == "T␟A␟B"


# --- LRCLIB lookup ---------------------------------------------------------------------


def _record(synced: str = "", plain: str = "", duration: float = 200, instrumental: bool = False) -> dict[str, Any]:
    return {
        "syncedLyrics": synced or None,
        "plainLyrics": plain or None,
        "duration": duration,
        "instrumental": instrumental,
    }


def test_pick_best_prefers_synced_lyrics_close_to_the_track():
    far = _record(synced="[00:01.00] far", duration=300)
    near = _record(synced="[00:01.00] near", duration=205)
    plain = _record(plain="plain", duration=200)
    assert pick_best([plain, far, near], 200) is near


def test_pick_best_rejects_other_versions():
    assert pick_best([_record(synced="[00:01.00] live", duration=260)], 200) is None
    assert pick_best([_record(plain="x", duration=215)], 200) is None
    plain = _record(plain="x", duration=205)
    assert pick_best([plain], 200) is plain


def test_pick_best_without_a_known_duration_takes_any_match():
    record = _record(synced="[00:01.00] x", duration=999)
    assert pick_best([record, "junk", None], 0) is record


class FakeGetter:
    """Answers LRCLIB URLs by endpoint and records the calls."""

    def __init__(self, routes: dict[str, list[tuple[int, Any]]]):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[int, bytes]:
        import json

        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        endpoint = parsed.path.rsplit("/", 1)[-1]
        if endpoint == "search" and "q=" in parsed.query:
            endpoint = "q"
        answers = self.routes.get(endpoint, [(404, None)])
        status, data = answers.pop(0) if len(answers) > 1 else answers[0]
        return status, json.dumps(data).encode() if data is not None else b""


def _no_sleep(_: float) -> None:
    pass


def test_exact_lookup_sends_album_and_duration_when_known():
    get = FakeGetter({"get": [(200, _record(synced="[00:01.00] hi"))]})
    result = fetch_lyrics(TrackQuery("Song", "Artist", "Album", 199.6), get, _no_sleep)
    assert result.status == "synced" and result.lines[0].text == "hi"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(get.calls[0]).query)
    assert query == {"artist_name": ["Artist"], "track_name": ["Song"], "album_name": ["Album"], "duration": ["200"]}


def test_missing_exact_match_falls_back_to_search_then_free_text():
    get = FakeGetter({"get": [(404, None)], "search": [(200, [])], "q": [(200, [_record(plain="words", duration=0)])]})
    result = fetch_lyrics(TrackQuery("Song", "Artist"), get, _no_sleep)
    assert result.status == "plain" and result.lines[0].text == "words"
    assert [urllib.parse.urlparse(c).path for c in get.calls] == ["/api/get", "/api/search", "/api/search"]


def test_players_without_artist_go_straight_to_free_text():
    get = FakeGetter({"q": [(200, [_record(synced="[00:02.00] x")])]})
    assert fetch_lyrics(TrackQuery("Some Video"), get, _no_sleep).status == "synced"
    assert len(get.calls) == 1 and "q=Some+Video" in get.calls[0]


def test_network_failures_retry_twice_then_report_an_error():
    get = FakeGetter({"get": [(0, None)]})
    sleeps: list[float] = []
    assert fetch_lyrics(TrackQuery("Song", "Artist"), get, sleeps.append).status == "error"
    assert len(get.calls) == 3 and len(sleeps) == 2


def test_retry_recovers_from_a_dropped_connection():
    get = FakeGetter({"get": [(0, None), (200, _record(synced="[00:01.00] ok"))]})
    assert fetch_lyrics(TrackQuery("Song", "Artist"), get, _no_sleep).status == "synced"


def test_instrumental_and_not_found():
    get = FakeGetter({"get": [(200, _record(instrumental=True))]})
    assert fetch_lyrics(TrackQuery("Song", "Artist"), get, _no_sleep).status == "instrumental"
    nothing = FakeGetter({"get": [(404, None)], "search": [(200, [])], "q": [(200, [])]})
    assert fetch_lyrics(TrackQuery("Song", "Artist"), nothing, _no_sleep).status == "notfound"
    assert fetch_lyrics(TrackQuery(" "), nothing, _no_sleep).status == "notfound"


def test_garbage_replies_do_not_raise():
    get = FakeGetter({"get": [(200, "not a record")], "search": [(200, {"x": 1})], "q": [(200, None)]})
    assert fetch_lyrics(TrackQuery("Song", "Artist"), get, _no_sleep).status in ("error", "notfound")


# --- bounded requests --------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    body = b""
    declare_length = True

    def do_GET(self) -> None:
        self.send_response(200)
        if self.declare_length:
            self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[Callable[[bytes, bool], str]]:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def serve(body: bytes, declare_length: bool = True) -> str:
        _Handler.body = body
        _Handler.declare_length = declare_length
        return f"http://127.0.0.1:{httpd.server_address[1]}/"

    yield serve
    httpd.shutdown()
    httpd.server_close()


def test_bounded_get_returns_small_replies(server: Callable[[bytes, bool], str]):
    assert bounded_get(server(b"[]", True)) == (200, b"[]")


@pytest.mark.parametrize("declare_length", [True, False])
def test_bounded_get_refuses_oversized_replies(server: Callable[[bytes, bool], str], declare_length: bool):
    url = server(b"x" * 2048, declare_length)
    assert bounded_get(url, max_bytes=1024) == (0, b"")


def test_bounded_get_reports_unreachable_hosts_as_status_zero():
    assert bounded_get("http://127.0.0.1:9/", timeout=1) == (0, b"")


# --- translation, romanization and cache ------------------------------------------------


def test_parse_translation_joins_entries():
    assert parse_translation(b'[["Ola\\nmundo","en"]]') == "Ola\nmundo"
    assert parse_translation(b'[["a","en"],["b","en"]]') == "a\nb"
    assert parse_translation(b"oops") == ""


def test_translate_lines_maps_back_by_index_and_chunks_long_lyrics(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(lyrics_mod, "MAX_TRANSLATE_CHARS", 10)
    seen: list[list[str]] = []

    def get(url: str) -> tuple[int, bytes]:
        import json

        lines = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0].split("\n")
        seen.append(lines)
        return 200, json.dumps([["\n".join(line.upper() for line in lines), "en"]]).encode()

    assert translate_lines(["hello", "big", "world"], "pt-BR", get) == ["HELLO", "BIG", "WORLD"]
    assert len(seen) > 1


def test_translate_lines_fails_closed():
    assert translate_lines(["hello"], "pt-BR", lambda url: (0, b"")) is None


def test_romanize_builtin_scripts():
    assert romanize_builtin("안녕하세요") == "annyeonghaseyo"
    assert romanize_builtin("Привет, мир") == "Privet, mir"
    assert romanize_builtin("Καλημέρα") == "Kalimera"
    assert romanize_builtin("きょうはがっこう") == "kyouhagakkou"
    assert romanize_builtin("コーヒー") == "koohii"
    assert romanize_builtin("plain text") == "plain text"


def test_romanize_lines_uses_pykakasi_when_available():
    class Kakasi:
        def convert(self, text: str) -> list[dict[str, str]]:
            return [{"hepburn": "kyou"}, {"hepburn": "wa"}]

    assert romanize_lines(["今日は", "hello"], kakasi=Kakasi) == ["kyou wa", "hello"]
    assert romanize_lines(["안녕"], kakasi=lambda: None) == ["annyeong"]


def test_player_audio_lives_in_its_child_processes():
    from core.utils.win32.bindings.kernel32 import ProcessEntry
    from core.widgets.services.super_player.app_volume import process_tree

    processes = [
        ProcessEntry(4, 1, "explorer.exe"),
        ProcessEntry(10, 4, "TIDAL.exe"),
        ProcessEntry(11, 10, "TIDALPlayer.exe"),
        ProcessEntry(12, 11, "crashpad.exe"),
        ProcessEntry(20, 4, "Discord.exe"),
    ]
    assert process_tree(processes, "tidal.exe") == {10, 11, 12}
    assert process_tree(processes, "explorer.exe") == {4}  # never every app the shell started
    assert process_tree(processes, "vlc.exe") == set()


def test_cache_keeps_the_newest_entries():
    cache = LyricsCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # touching "a" makes "b" the oldest
    cache.put("c", 3)
    assert "b" not in cache and len(cache) == 2 and cache.get("a") == 1


# --- the widget --------------------------------------------------------------------------


class FakeMedia(QObject):
    media_data_changed = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[tuple[str, str]] = []
        self.seeks: list[tuple[float, str | None]] = []

    def force_update(self) -> None:
        pass

    async def session_command(self, app_id: str, command: str) -> None:
        self.commands.append((app_id, command))

    async def seek_to_position(self, position: float, app_id: str | None = None) -> None:
        self.seeks.append((position, app_id))


class FakeWorker(QObject):
    lyrics_ready = pyqtSignal(int, object)
    translation_ready = pyqtSignal(int, object)
    romanization_ready = pyqtSignal(int, object)

    def __init__(self, result: LyricsResult) -> None:
        super().__init__()
        self.result = result
        self.queries: list[TrackQuery] = []
        self._id = 0

    def next_request_id(self) -> int:
        self._id += 1
        return self._id

    def fetch_lyrics(self, request_id: int, query: TrackQuery) -> None:
        self.queries.append(query)
        self.lyrics_ready.emit(request_id, self.result)

    def translate(self, request_id: int, texts: list[str], language: str) -> None:
        self.translation_ready.emit(request_id, [f"{language}:{t}" for t in texts])

    def romanize(self, request_id: int, texts: list[str]) -> None:
        self.romanization_ready.emit(request_id, texts)


@pytest.fixture
def widget_env(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    from core.widgets.yasb import super_player as module

    media = FakeMedia()
    worker = FakeWorker(LyricsResult("synced", parse_lrc("[00:05.00] <b>first</b>\n[00:10.00] second"), 200))
    monkeypatch.setattr(module, "WindowsMedia", lambda: media)

    def no_name(app_id: str) -> str | None:
        return None

    monkeypatch.setattr(module.LyricsWorker, "instance", lambda: worker)
    monkeypatch.setattr(module, "resolve_source_app_name", no_name)
    for cache in (module._lyrics_cache, module._translation_cache, module._romanization_cache):
        cache._items.clear()
    widgets: list[Any] = []

    def make(**options: Any) -> Any:
        w = module.SuperPlayerWidget(SuperPlayerConfig.model_validate(options))
        widgets.append(w)
        return w

    yield make, media, worker
    for w in widgets:
        w.close()


def _feed(widget: Any, media: FakeMedia, **fields: Any) -> FakeSession:
    session = FakeSession(
        "Spotify.exe",
        is_playing=True,
        duration=200,
        last_update_time=1.0,
        timeline_enabled=True,
        **fields,
    )
    media.media_data_changed.emit({session.app_id: session})
    return session


def test_widget_hides_without_a_player(widget_env: Any):
    make, media, _ = widget_env
    widget = make()
    media.media_data_changed.emit({})
    assert widget.isHidden()


def test_widget_shows_the_current_line_as_plain_text(widget_env: Any):
    make, media, worker = widget_env
    widget = make()
    _feed(widget, media, current_pos=6.0)
    widget._load()  # skip the debounce
    _feed(widget, media, current_pos=6.0)
    assert not widget.isHidden()
    assert widget._label.text() == "<b>first</b>"
    assert widget._label.textFormat() == Qt.TextFormat.PlainText
    assert worker.queries[0].duration == 200
    _feed(widget, media, current_pos=11.0)
    assert widget._label.text() == "second"


def test_widget_falls_back_to_the_title_between_tracks_and_before_the_first_line(widget_env: Any):
    make, media, _ = widget_env
    widget = make()
    _feed(widget, media, current_pos=1.0, title="My Song")
    assert widget._label.text() == "My Song"


def test_track_mode_and_hide_when_no_lyrics(widget_env: Any):
    make, media, _ = widget_env
    widget = make(bar_label="track")
    _feed(widget, media, current_pos=6.0, title="My Song")
    widget._load()
    assert widget._label.text() == "My Song"

    hiding = make(hide_when_no_lyrics=True)
    _feed(hiding, media, current_pos=1.0)
    assert hiding.isHidden()


def test_translation_is_preferred_in_the_bar(widget_env: Any):
    make, media, _ = widget_env
    widget = make(translate="pt-BR")
    _feed(widget, media, current_pos=6.0)
    widget._load()
    _feed(widget, media, current_pos=6.0)
    assert widget._label.text() == "pt-BR:<b>first</b>"


def test_popup_lines_seek_and_use_plain_text(widget_env: Any):
    make, media, _ = widget_env
    widget = make()
    widget._loop = None  # commands are not awaited in the test
    session = _feed(widget, media, current_pos=6.0)
    widget._load()
    widget._show_popup()
    _feed(widget, media, current_pos=6.0)
    labels = widget._popup.findChildren(QLabel)
    assert labels and all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)
    lines = widget._line_widgets
    assert [line.text_label.text() for line in lines] == ["<b>first</b>", "second"]
    assert "current" in lines[0].property("class") and lines[1].seekable
    widget._seek_line(1)
    assert widget._position == 10.0 and widget._index == 1
    assert session.app_id == "Spotify.exe"
    widget._popup.hide()


def test_players_without_a_timeline_are_not_seekable(widget_env: Any):
    make, media, _ = widget_env
    widget = make()
    session = FakeSession("chrome", is_playing=True)
    media.media_data_changed.emit({"chrome": session})
    widget._load()
    widget.seek_to(10.0)
    assert media.seeks == [] and widget._status == "synced"
