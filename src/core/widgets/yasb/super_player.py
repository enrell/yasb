"""Super Player: the lyric line being sung right now in the bar, plus a popup with media
controls and the full synced lyrics.

A YASB port of omarchy-super-player by enrell
(https://github.com/enrell/omarchy-super-player). The source player comes from GSMTC
through YASB's media service; lyrics come from LRCLIB (https://lrclib.net).

Every string that comes from the player or from the network (titles, artists, lyrics,
translations) is rendered as plain text, never as rich text.
"""

import asyncio
import html
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any, Literal, override

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QColor,
    QEnterEvent,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.utils.qobject import is_valid_qobject
from core.utils.tooltip import set_tooltip, show_tooltip_now
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.super_player import SuperPlayerConfig
from core.widgets.base import BaseWidget
from core.widgets.services.media.media import SessionState, WindowsMedia
from core.widgets.services.media.source_apps import resolve_source_app_name
from core.widgets.services.super_player.app_volume import AppVolume
from core.widgets.services.super_player.lrc import LyricLine, index_at
from core.widgets.services.super_player.lyrics import LyricsCache, LyricsResult, TrackQuery
from core.widgets.services.super_player.player import SyncClock, can_seek, has_timeline, pick_session, track_key
from core.widgets.services.super_player.worker import LyricsWorker

logger = logging.getLogger("super_player")

type LyricsStatus = Literal["noplayer", "loading", "synced", "plain", "notfound", "instrumental", "error"]

# Let the player finish publishing the new track's metadata before looking it up.
LOOKUP_DEBOUNCE_MS = 250
VOLUME_TOOLTIP_MS = 1400
VOLUME_HIDE_MS = 260
MAX_TIMELINE = 604800  # a week: longer "durations" are live streams

# Shared by every Super Player widget: the same track on two bars is looked up once.
_lyrics_cache = LyricsCache(50)
_translation_cache = LyricsCache(50)
_romanization_cache = LyricsCache(50)

EMPTY_MESSAGES: dict[str, str] = {
    "noplayer": "No player running.\nStart something and press play.",
    "loading": "Fetching lyrics…",
    "notfound": "No lyrics found on LRCLIB.",
    "instrumental": "Instrumental.",
    "error": "Could not fetch the lyrics.\nCheck your connection.",
}

STATUS_LABELS: dict[str, str] = {
    "loading": "fetching lyrics…",
    "plain": "unsynced lyrics",
    "notfound": "no lyrics found",
    "instrumental": "instrumental",
    "error": "network error",
}


def plain_label(text: str = "", class_name: str = "", parent: QWidget | None = None) -> QLabel:
    """A QLabel that never interprets its text as HTML."""
    label = QLabel(parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    if class_name:
        label.setProperty("class", class_name)
    return label


def display_text(line: LyricLine, romanize: str, translate: str) -> str:
    """The most readable version of a line for the bar: translation, romanization, original."""
    if translate != "off" and line.translated and line.translated != line.text:
        return line.translated
    if romanize != "off" and line.romanized and line.romanized != line.text:
        return line.romanized
    return line.text


class MarqueeLabel(QLabel):
    """Plain text label with a maximum width in pixels; longer text scrolls through it."""

    GAP = 48
    STEP_MS = 25
    START_DELAY_MS = 1200

    def __init__(self, max_width: int, scroll: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._max_width = max_width
        self._scroll = scroll
        self._offset = 0
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(self.STEP_MS)
        self._timer.timeout.connect(self._advance)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self._sync_timer)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def _text_width(self) -> int:
        return QFontMetrics(self.font()).horizontalAdvance(self.text())

    def _overflows(self) -> bool:
        return self._text_width() > self.contentsRect().width()

    @override
    def setText(self, a0: str | None) -> None:
        if (a0 or "") == self.text():
            return
        super().setText(a0)
        self._offset = 0
        self._timer.stop()
        self.updateGeometry()
        self.update()
        self._delay.start(self.START_DELAY_MS)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._sync_timer()

    def _sync_timer(self) -> None:
        running = self._scroll and not self._paused and self.isVisible() and self._overflows()
        if running and not self._timer.isActive():
            self._timer.start()
        elif not running:
            self._timer.stop()
            if not self._overflows() or not self._scroll:
                self._offset = 0
                self.update()

    def _advance(self) -> None:
        self._offset = (self._offset + 1) % (self._text_width() + self.GAP)
        self.update()

    @override
    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        width = self._text_width() + margins.left() + margins.right() + 1
        height = QFontMetrics(self.font()).height() + margins.top() + margins.bottom()
        return QSize(min(self._max_width, width), height)

    @override
    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.sizeHint().height())

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        painter.setClipRect(rect)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())
        metrics = QFontMetrics(self.font())
        y = rect.top() + (rect.height() + metrics.ascent() - metrics.descent()) // 2
        text = self.text()
        if not self._overflows():
            painter.drawText(rect.left(), y, text)
        elif not self._scroll:
            painter.drawText(rect.left(), y, metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
        else:
            x = rect.left() - self._offset
            painter.drawText(x, y, text)
            painter.drawText(x + self._text_width() + self.GAP, y, text)
        painter.end()

    @override
    def showEvent(self, a0: Any) -> None:
        super().showEvent(a0)
        self._sync_timer()

    @override
    def hideEvent(self, a0: Any) -> None:
        self._timer.stop()
        super().hideEvent(a0)

    @override
    def resizeEvent(self, a0: Any) -> None:
        super().resizeEvent(a0)
        self._sync_timer()


class ClickLabel(QLabel):
    """Plain text label that runs a callback on left click unless it has class ``disabled``."""

    def __init__(self, text: str, class_name: str, on_click: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(text)
        self.setProperty("class", class_name)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click

    @override
    def mousePressEvent(self, ev: QMouseEvent | None) -> None:
        if ev is not None:
            ev.accept()

    @override
    def mouseReleaseEvent(self, ev: QMouseEvent | None) -> None:
        if ev is None:
            return
        ev.accept()
        if "disabled" in str(self.property("class") or "").split():
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(ev.position().toPoint()):
            self._on_click()


class CoverLabel(ClickLabel):
    """Cover art; hovering shows the play/pause glyph and a click toggles playback."""

    def __init__(self, size: int, on_click: Callable[[], None], parent: QWidget | None = None):
        super().__init__("", "cover", on_click, parent)
        self.setFixedSize(size, size)
        self._pixmap: QPixmap | None = None
        self._fallback = ""
        self._overlay = ""
        self._hovered = False

    def set_cover(self, pixmap: QPixmap | None, fallback: str, overlay: str) -> None:
        self._pixmap = pixmap
        self._fallback = fallback
        self._overlay = overlay
        self.update()

    @override
    def enterEvent(self, event: QEnterEvent | None) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    @override
    def leaveEvent(self, a0: QEvent | None) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(a0)

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)  # background and border from CSS
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.contentsRect())
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.setClipPath(path)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.left() + (rect.width() - scaled.width()) / 2
            y = rect.top() + (rect.height() - scaled.height()) / 2
            painter.drawPixmap(int(x), int(y), scaled)
        elif not self._hovered:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._fallback)
        if self._hovered:
            painter.fillRect(rect, QColor(0, 0, 0, 128))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._overlay)
        painter.end()


class AbsoluteSlider(QSlider):
    """Knobless-friendly slider: click anywhere to jump there, press and drag to scrub.

    ``moved`` fires while the mouse moves with the button down, ``committed`` on release.
    """

    moved = pyqtSignal(float)
    committed = pyqtSignal(float)

    def __init__(self, class_name: str, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setProperty("class", class_name)
        self.setRange(0, 1000)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dragging = False

    def ratio(self) -> float:
        return self.value() / 1000

    def set_ratio(self, ratio: float) -> None:
        if not self.dragging:
            self.blockSignals(True)
            self.setValue(round(max(0.0, min(1.0, ratio)) * 1000))
            self.blockSignals(False)

    def _ratio_at(self, event: QMouseEvent) -> float:
        return max(0.0, min(1.0, event.position().x() / max(1, self.width())))

    @override
    def mousePressEvent(self, ev: QMouseEvent | None) -> None:
        if ev is None or ev.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        self.dragging = True
        self.setValue(round(self._ratio_at(ev) * 1000))
        self.moved.emit(self.ratio())
        ev.accept()

    @override
    def mouseMoveEvent(self, ev: QMouseEvent | None) -> None:
        if ev is None or not self.dragging:
            return
        self.setValue(round(self._ratio_at(ev) * 1000))
        self.moved.emit(self.ratio())
        ev.accept()

    @override
    def mouseReleaseEvent(self, ev: QMouseEvent | None) -> None:
        if ev is None or not self.dragging:
            return
        self.dragging = False
        self.committed.emit(self.ratio())
        ev.accept()


class LyricLineWidget(QFrame):
    """One line in the popup: original text, optional romanization and translation."""

    def __init__(self, index: int, line: LyricLine, romanize: str, translate: str, on_click: Callable[[int], None]):
        super().__init__()
        self.index = index
        self.line = line
        self._on_click = on_click
        self._state = ""
        self.seekable = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        romanized = line.romanized if line.romanized and line.romanized != line.text else ""
        translated = line.translated if line.translated and line.translated != line.text else ""
        main = romanized if romanize == "replace" and romanized else (line.text or "♪")

        self.text_label = self._label(main, "text")
        layout.addWidget(self.text_label)
        self.romanized_label: QLabel | None = None
        self.translated_label: QLabel | None = None
        if romanize == "below" and romanized:
            self.romanized_label = self._label(romanized, "romanized")
            layout.addWidget(self.romanized_label)
        if translate != "off" and translated:
            self.translated_label = self._label(translated, "translated")
            layout.addWidget(self.translated_label)

    def _label(self, text: str, class_name: str) -> QLabel:
        label = plain_label(text, class_name, self)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return label

    def labels(self) -> list[QLabel]:
        return [lbl for lbl in (self.text_label, self.romanized_label, self.translated_label) if lbl is not None]

    def set_state(self, state: str, seekable: bool) -> None:
        if state == self._state and seekable == self.seekable:
            return
        self._state = state
        self.seekable = seekable
        self.setProperty("class", f"line {state}{' seekable' if seekable else ''}")
        self.setCursor(Qt.CursorShape.PointingHandCursor if seekable else Qt.CursorShape.ArrowCursor)
        refresh_widget_style(self, *self.labels())

    @override
    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton and self.seekable:
            self._on_click(self.index)
        super().mouseReleaseEvent(a0)


class SuperPlayerWidget(BaseWidget):
    validation_schema = SuperPlayerConfig

    def __init__(self, config: SuperPlayerConfig):
        super().__init__(class_name=f"super-player-widget {config.class_name}".strip())
        self.config = config
        self._loop: asyncio.AbstractEventLoop | None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        self.media = WindowsMedia()
        self._worker = LyricsWorker.instance()
        self._volume = AppVolume()

        # Player and track
        self._session: SessionState | None = None
        self._identity = ""
        self._key = ""
        self._clock = SyncClock()
        self._position = 0.0
        self._playing = False

        # Lyrics
        self._lines: list[LyricLine] = []
        self._status: LyricsStatus = "noplayer"
        self._lrclib_duration = 0.0
        self._index = -1
        self._lyrics_rid = 0
        self._translate_rid = 0
        self._romanize_rid = 0
        self._translate_status: Literal["", "loading", "ok", "error"] = ""

        # Popup state
        self._popup: PopupWidget | None = None
        self._popup_generation = 0
        self._line_widgets: list[LyricLineWidget] = []
        self._cover_key = ""
        self._cover_pixmap: QPixmap | None = None

        self._build_bar()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(LOOKUP_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._load)

        self._tooltip_reset = QTimer(self)
        self._tooltip_reset.setSingleShot(True)
        self._tooltip_reset.setInterval(VOLUME_TOOLTIP_MS)
        self._tooltip_reset.timeout.connect(self._update_tooltip)

        self.register_callback("toggle_popup", self._toggle_popup)
        self.register_callback("toggle_play_pause", self._toggle_play_pause)
        self.register_callback("next_track", self._next_track)
        self.register_callback("prev_track", self._prev_track)
        self.register_callback("toggle_mute", self._toggle_mute)
        self.register_callback("reload_lyrics", self._reload)
        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right

        self._worker.lyrics_ready.connect(self._on_lyrics_ready)
        self._worker.translation_ready.connect(self._on_translation_ready)
        self._worker.romanization_ready.connect(self._on_romanization_ready)
        self.media.media_data_changed.connect(self._on_media_data_changed)

        self.hide()
        QTimer.singleShot(0, self.media.force_update)

    # ------------------------------------------------------------------ bar
    def _build_bar(self) -> None:
        self._init_container()
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._icon = plain_label(self.config.icons.music, "icon")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setVisible(self.config.show_icon)
        row.addWidget(self._icon)
        self._label = MarqueeLabel(self.config.max_label_width, self.config.scroll_label)
        self._label.setProperty("class", "label")
        row.addWidget(self._label)
        grid.addLayout(row, 0, 0)

        # The widget doubles as a progress bar: a hairline along its bottom edge.
        self._progress = QProgressBar()
        self._progress.setProperty("class", "progress")
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        self._progress.setMaximumHeight(2)
        self._progress.setMinimumWidth(0)
        self._progress.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._progress.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._progress.setVisible(False)
        grid.addWidget(self._progress, 0, 0, Qt.AlignmentFlag.AlignBottom)

        self._widget_container_layout.addWidget(content)

    def _bar_text(self) -> str:
        if self.config.bar_label == "icon":
            return ""
        title = self._session.title if self._session else ""
        if self.config.bar_label == "track":
            return title
        line = self._current_line()
        text = display_text(line, self.config.romanize, self.config.translate) if line else ""
        return text or title

    def _current_line(self) -> LyricLine | None:
        if self._status == "synced" and 0 <= self._index < len(self._lines):
            return self._lines[self._index]
        return None

    def _refresh_bar(self) -> None:
        has_player = self._session is not None
        current = self._current_line()
        shown = has_player and not (self.config.hide_when_no_lyrics and not (current and current.text))
        if shown == self.isHidden():
            self.setVisible(shown)
        if not shown:
            return
        text = self._bar_text()
        self._label.setText(text)
        self._label.setVisible(bool(text))
        self._set_class(self._icon, f"icon {'playing' if self._playing else 'paused'}")
        self._refresh_progress()

    def _duration(self) -> float:
        session = self._session
        if session is not None and has_timeline(session) and session.duration < MAX_TIMELINE:
            return session.duration
        return self._lrclib_duration

    def _refresh_progress(self) -> None:
        duration = self._duration()
        visible = self.config.show_progress and duration > 0
        if visible != (not self._progress.isHidden()):
            self._progress.setVisible(visible)
        if visible:
            value = int(min(1.0, self._position / duration) * 1000)
            if value != self._progress.value():
                self._progress.setValue(value)

    @staticmethod
    def _set_class(widget: QWidget | None, class_name: str) -> None:
        if widget is None or not is_valid_qobject(widget) or widget.property("class") == class_name:
            return
        widget.setProperty("class", class_name)
        refresh_widget_style(widget)

    def _update_tooltip(self) -> None:
        if not self.config.tooltip or self._session is None:
            return
        session = self._session
        text = session.title + (f" — {session.artist}" if session.artist else "")
        # The tooltip label may render rich text; remote strings are escaped.
        set_tooltip(self, html.escape(text or "Unknown track"))

    # --------------------------------------------------------------- player
    @pyqtSlot(dict)
    def _on_media_data_changed(self, trackers: dict[str, SessionState]) -> None:
        sessions = list(trackers.values())
        system_current = next((s.app_id for s in sessions if s.is_current), None)
        session = pick_session(sessions, self.config.source, system_current, resolve_source_app_name)

        identity = f"{session.app_id}␟{track_key(session)}" if session else ""
        player_changed = (session.app_id if session else "") != (self._session.app_id if self._session else "")
        self._session = session
        if identity != self._identity or player_changed:
            self._identity = identity
            self._on_track_changed()

        if session is None:
            self._refresh_bar()
            self._refresh_popup()
            return

        self._playing = session.is_playing
        reported = session.current_pos if has_timeline(session) else None
        self._position = self._clock.tick(time.monotonic(), self._playing, reported, session.playback_rate)
        self._update_index()
        self._refresh_bar()
        self._refresh_popup()

    def _on_track_changed(self) -> None:
        session = self._session
        self._key = track_key(session) if session else ""
        start = session.current_pos if session and has_timeline(session) and session.current_pos > 0 else 0.0
        self._clock.reset(start)
        self._position = start
        self._index = -1
        self._lines = []
        self._lrclib_duration = 0.0
        self._lyrics_rid = self._translate_rid = self._romanize_rid = 0
        self._translate_status = ""
        self._debounce.stop()
        if session is None:
            self._status = "noplayer"
        elif not self._key:
            self._status = "notfound"
        else:
            self._status = "loading"
            self._debounce.start()
        self._update_tooltip()
        self._rebuild_popup_lyrics()

    # --------------------------------------------------------------- lyrics
    def _load(self, force: bool = False) -> None:
        session = self._session
        if session is None or not self._key:
            return
        cached = None if force else _lyrics_cache.get(self._key)
        if isinstance(cached, LyricsResult):
            self._apply_lyrics(cached)
            return
        self._status = "loading"
        self._rebuild_popup_lyrics()
        self._lyrics_rid = self._worker.next_request_id()
        duration = session.duration if has_timeline(session) and session.duration < MAX_TIMELINE else 0.0
        query = TrackQuery(session.title, session.artist, session.album, duration)
        self._worker.fetch_lyrics(self._lyrics_rid, query)

    def _reload(self) -> None:
        if self._key:
            _lyrics_cache.pop(self._key)
        self._load(force=True)

    @pyqtSlot(int, object)
    def _on_lyrics_ready(self, request_id: int, result: object) -> None:
        if request_id != self._lyrics_rid:
            return  # a reply for a previous track, or for another widget
        self._lyrics_rid = 0
        if not isinstance(result, LyricsResult):
            result = LyricsResult("error")
        if result.status != "error":
            _lyrics_cache.put(self._key, result)
        self._apply_lyrics(result)

    def _apply_lyrics(self, result: LyricsResult) -> None:
        # Copies, so romanization and translation never leak into the shared cache.
        self._lines = [replace(line) for line in result.lines]
        self._status = result.status
        self._lrclib_duration = result.duration
        self._index = -1
        self._update_index()
        self._schedule_romanize()
        self._schedule_translate()
        self._rebuild_popup_lyrics()
        self._refresh_bar()

    def _texts(self) -> list[str]:
        return [line.text for line in self._lines]

    def _schedule_romanize(self) -> None:
        if self.config.romanize == "off" or not self._lines:
            return
        cached = _romanization_cache.get(self._key)
        if isinstance(cached, list):
            self._merge("romanized", cached)  # pyright: ignore[reportUnknownArgumentType]
            return
        self._romanize_rid = self._worker.next_request_id()
        self._worker.romanize(self._romanize_rid, self._texts())

    @pyqtSlot(int, object)
    def _on_romanization_ready(self, request_id: int, result: object) -> None:
        if request_id != self._romanize_rid or not isinstance(result, list):
            return
        _romanization_cache.put(self._key, result)
        self._merge("romanized", result)  # pyright: ignore[reportUnknownArgumentType]
        self._rebuild_popup_lyrics()

    def _schedule_translate(self) -> None:
        language = self.config.translate.strip()
        if language.lower() == "off" or not language or not self._lines:
            return
        cache_key = f"{self._key}|{language}"
        cached = _translation_cache.get(cache_key)
        if isinstance(cached, list):
            self._translate_status = "ok"
            self._merge("translated", cached)  # pyright: ignore[reportUnknownArgumentType]
            return
        self._translate_status = "loading"
        self._translate_rid = self._worker.next_request_id()
        self._worker.translate(self._translate_rid, self._texts(), language)

    @pyqtSlot(int, object)
    def _on_translation_ready(self, request_id: int, result: object) -> None:
        if request_id != self._translate_rid:
            return
        if not isinstance(result, list):
            self._translate_status = "error"  # keep the original lyrics
            self._refresh_popup()
            return
        _translation_cache.put(f"{self._key}|{self.config.translate.strip()}", result)
        self._translate_status = "ok"
        self._merge("translated", result)  # pyright: ignore[reportUnknownArgumentType]
        self._rebuild_popup_lyrics()

    def _merge(self, field: Literal["romanized", "translated"], values: list[Any]) -> None:
        for line, value in zip(self._lines, values, strict=False):
            setattr(line, field, str(value).strip())
        self._refresh_bar()

    def _update_index(self) -> None:
        index = index_at(self._lines, self._position) if self._status == "synced" else -1
        if index != self._index:
            self._index = index
            self._refresh_line_states(scroll=True)

    # ------------------------------------------------------------- controls
    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        if self._loop is None or self._loop.is_closed():
            coroutine.close()
            return
        self._loop.create_task(coroutine)

    def _toggle_play_pause(self) -> None:
        if self._session is not None and self._session.controls_play_enabled:
            self._spawn(self.media.session_command(self._session.app_id, "play_pause"))

    def _next_track(self) -> None:
        if self._session is not None and self._session.controls_next_enabled:
            self._spawn(self.media.session_command(self._session.app_id, "next"))

    def _prev_track(self) -> None:
        if self._session is not None and self._session.controls_prev_enabled:
            self._spawn(self.media.session_command(self._session.app_id, "prev"))

    def seek_to(self, position: float) -> None:
        session = self._session
        if session is None or position < 0 or not can_seek(session):
            return
        self._spawn(self.media.seek_to_position(position, session.app_id))
        self._clock.seek(position)
        self._position = position
        self._update_index()
        self._refresh_bar()

    def _seek_line(self, index: int) -> None:
        if 0 <= index < len(self._lines) and self._lines[index].time >= 0:
            self.seek_to(self._lines[index].time)

    def _bind_volume(self) -> bool:
        return self._session is not None and self._volume.bind(self._session.app_id)

    def _toggle_mute(self) -> None:
        if self._bind_volume():
            self._volume.set_muted(not self._volume.muted())
            self._refresh_volume()

    def _set_volume(self, value: float) -> None:
        if self._bind_volume():
            self._volume.set_volume(value)
            self._refresh_volume()

    @override
    def wheelEvent(self, a0: QWheelEvent | None) -> None:
        if a0 is None or not self._bind_volume():
            return
        current = self._volume.volume()
        if current is None:
            return
        step = self.config.volume_step / 100
        new = current + (step if a0.angleDelta().y() > 0 else -step)
        self._set_volume(new)
        if self.config.tooltip:
            set_tooltip(self, f"Volume {round(max(0.0, min(1.0, new)) * 100)}%")
            show_tooltip_now(self)
            self._tooltip_reset.start()
        a0.accept()

    # ---------------------------------------------------------------- popup
    def _popup_open(self) -> bool:
        """True from the moment the popup is built until it is destroyed."""
        return is_valid_qobject(self._popup)

    def _toggle_popup(self) -> None:
        if self._popup is not None and is_valid_qobject(self._popup) and self._popup.isVisible():
            self._popup.hide_animated()
            return
        self._show_popup()

    def _show_popup(self) -> None:
        cfg = self.config.popup
        popup = PopupWidget(self, cfg.blur, cfg.round_corners, cfg.round_corners_type, cfg.border_color)
        popup.setProperty("class", "super-player-popup")
        popup.setFixedWidth(cfg.width)
        self._popup = popup
        self._popup_generation += 1
        generation = self._popup_generation
        popup.destroyed.connect(lambda *_: self._on_popup_destroyed(generation))

        layout = QVBoxLayout(popup)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        # Header: cover, title, artist, transport and volume
        header = QFrame()
        header.setProperty("class", "header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        self._cover: CoverLabel | None = None
        if cfg.show_cover:
            self._cover = CoverLabel(cfg.cover_size, self._toggle_play_pause)
            header_layout.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(0)
        self._title_label = plain_label("", "title")
        self._artist_label = plain_label("", "artist")
        for label in (self._title_label, self._artist_label):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            info.addWidget(label)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(2)
        icons = self.config.icons
        self._prev_btn = ClickLabel(icons.prev_track, "btn prev", self._prev_track)
        self._play_btn = ClickLabel(icons.play, "btn play", self._toggle_play_pause)
        self._next_btn = ClickLabel(icons.next_track, "btn next", self._next_track)
        self._mute_btn = ClickLabel(icons.volume, "btn mute", self._toggle_mute)
        for button in (self._prev_btn, self._play_btn, self._next_btn, self._mute_btn):
            controls.addWidget(button)
        self._volume_slider = AbsoluteSlider("volume-slider")
        self._volume_slider.setFixedWidth(110)
        self._volume_slider.moved.connect(self._set_volume)
        self._volume_slider.setVisible(False)
        controls.addWidget(self._volume_slider)
        self._status_label = plain_label("", "status")
        controls.addWidget(self._status_label, 1)
        info.addLayout(controls)
        header_layout.addLayout(info, 1)
        layout.addWidget(header)

        # The volume bar is revealed while the mute button or the bar itself is hovered.
        self._volume_hide = QTimer(popup)
        self._volume_hide.setSingleShot(True)
        self._volume_hide.setInterval(VOLUME_HIDE_MS)
        self._volume_hide.timeout.connect(lambda: self._volume_slider.setVisible(False))
        self._mute_btn.installEventFilter(self)
        self._volume_slider.installEventFilter(self)

        # Lyrics
        self._scroll = QScrollArea()
        self._scroll.setProperty("class", "lyrics")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setFixedHeight(cfg.lyrics_height)
        self._scroll.viewport().setAutoFillBackground(False)  # pyright: ignore[reportOptionalMemberAccess]
        self._lyrics_body = QWidget()
        self._lyrics_body.setProperty("class", "lyrics-body")
        self._lyrics_body.setAutoFillBackground(False)
        self._lyrics_layout = QVBoxLayout(self._lyrics_body)
        self._lyrics_layout.setContentsMargins(0, 0, 0, 0)
        self._lyrics_layout.setSpacing(10)
        self._scroll.setWidget(self._lyrics_body)
        self._scroll_anim = QPropertyAnimation(self._scroll.verticalScrollBar(), b"value", popup)
        self._scroll_anim.setDuration(400)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        layout.addWidget(self._scroll)

        # Empty state
        self._empty = QFrame()
        self._empty.setProperty("class", "empty")
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        self._empty_label = plain_label("", "message")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self._empty_label)
        self._retry_btn = QPushButton("Try again")
        self._retry_btn.setProperty("class", "retry")
        self._retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_btn.clicked.connect(self._reload)
        empty_layout.addWidget(self._retry_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self._empty.setFixedHeight(cfg.lyrics_height)
        layout.addWidget(self._empty)

        # Seek bar: click anywhere to jump, press and drag to scrub
        self._seek = AbsoluteSlider("seek-slider")
        self._seek.committed.connect(self._on_seek_committed)
        layout.addWidget(self._seek)

        # A failed lookup is worth another try as soon as the popup opens.
        if self._status in ("error", "notfound") and self._key:
            self._reload()

        self._rebuild_popup_lyrics()
        self._refresh_popup()
        self._refresh_volume()
        popup.adjustSize()
        popup.setPosition(cfg.alignment, cfg.direction, cfg.offset_left, cfg.offset_top)
        popup.show()
        self._label.set_paused(True)
        QTimer.singleShot(0, lambda: self._scroll_to_current(animated=False))

    def _on_popup_destroyed(self, generation: int) -> None:
        if generation != self._popup_generation:
            return  # an older popup finished closing after a new one opened
        self._popup = None
        self._line_widgets = []
        self._label.set_paused(False)

    @override
    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None or not self._popup_open():
            return super().eventFilter(a0, a1)
        if a0 in (self._mute_btn, self._volume_slider):
            if a1.type() == QEvent.Type.Enter and self._volume.supported:
                self._volume_hide.stop()
                self._volume_slider.setVisible(True)
            elif a1.type() == QEvent.Type.Leave:
                self._volume_hide.start()
        return super().eventFilter(a0, a1)

    def _on_seek_committed(self, ratio: float) -> None:
        duration = self._duration()
        if duration > 0:
            self.seek_to(ratio * duration)

    def _refresh_volume(self) -> None:
        if not self._popup_open():
            return
        supported = self._bind_volume()
        volume = self._volume.volume() if supported else None
        muted = self._volume.muted() if supported else False
        icons = self.config.icons
        self._mute_btn.setText(icons.muted if muted or volume == 0 else icons.volume)
        self._set_class(self._mute_btn, f"btn mute{' muted' if muted else ''}{'' if supported else ' disabled'}")
        if volume is not None:
            self._volume_slider.set_ratio(volume)

    def _refresh_popup(self) -> None:
        """Cheap updates, run on every media tick while the popup is open."""
        if not self._popup_open():
            return
        session = self._session
        icons = self.config.icons
        title = session.title if session and session.title else "Nothing playing"
        artist = session.artist if session else ""
        metrics = QFontMetrics(self._title_label.font())
        width = max(40, self._title_label.width())
        self._title_label.setText(metrics.elidedText(title, Qt.TextElideMode.ElideRight, width))
        self._artist_label.setText(
            QFontMetrics(self._artist_label.font()).elidedText(artist, Qt.TextElideMode.ElideRight, width)
        )
        self._artist_label.setVisible(bool(artist))

        playing = bool(session and session.is_playing)
        self._play_btn.setText(icons.pause if playing else icons.play)
        self._set_class(self._play_btn, f"btn play{'' if session and session.controls_play_enabled else ' disabled'}")
        self._set_class(self._prev_btn, f"btn prev{'' if session and session.controls_prev_enabled else ' disabled'}")
        self._set_class(self._next_btn, f"btn next{'' if session and session.controls_next_enabled else ' disabled'}")

        status = STATUS_LABELS.get(self._status, "")
        if self._translate_status == "loading":
            status = status or "translating…"
        elif self._translate_status == "error":
            status = status or "translation failed"
        elif session is not None and not has_timeline(session) and self._status == "synced":
            status = "estimated timing"  # no timeline from the player: local clock
        self._status_label.setText(status)

        if self._cover is not None:
            self._refresh_cover()

        duration = self._duration()
        seekable = session is not None and can_seek(session)
        self._seek.setVisible(duration > 0)
        self._seek.setEnabled(seekable)
        if duration > 0:
            self._seek.set_ratio(self._position / duration)

    def _refresh_cover(self) -> None:
        if self._cover is None:
            return
        session = self._session
        image: Image.Image | None = session.thumbnail if session else None
        key = f"{self._identity}|{id(image)}"
        if key != self._cover_key:
            self._cover_key = key
            self._cover_pixmap = None
            if image is not None:
                try:
                    self._cover_pixmap = QPixmap.fromImage(ImageQt(image.convert("RGBA")))
                except Exception as e:
                    logger.debug("Could not convert the cover art: %s", e)
        icons = self.config.icons
        playing = bool(session and session.is_playing)
        self._cover.set_cover(self._cover_pixmap, icons.music, icons.pause if playing else icons.play)

    def _rebuild_popup_lyrics(self) -> None:
        """Rebuild the line list; runs when the lyrics change, not on every tick."""
        if not self._popup_open():
            return
        self._scroll_anim.stop()
        while self._lyrics_layout.count():
            item = self._lyrics_layout.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.deleteLater()
        self._line_widgets = []

        has_lines = bool(self._lines)
        self._scroll.setVisible(has_lines)
        self._empty.setVisible(not has_lines)
        if not has_lines:
            status = self._status if self._session is not None else "noplayer"
            self._empty_label.setText(EMPTY_MESSAGES.get(status, ""))
            self._retry_btn.setVisible(status in ("error", "notfound") and bool(self._key))
            return

        # Spacers so the first and the last line can sit in the middle.
        half = max(0, self.config.popup.lyrics_height // 2 - 24)
        self._lyrics_layout.addSpacing(half)
        for index, line in enumerate(self._lines):
            widget = LyricLineWidget(index, line, self.config.romanize, self.config.translate, self._seek_line)
            self._line_widgets.append(widget)
            self._lyrics_layout.addWidget(widget)
        self._lyrics_layout.addSpacing(half)
        self._refresh_line_states(scroll=False)
        self._scroll.verticalScrollBar().setValue(0)  # pyright: ignore[reportOptionalMemberAccess]
        QTimer.singleShot(0, lambda: self._scroll_to_current(animated=False))

    def _refresh_line_states(self, scroll: bool) -> None:
        if not self._line_widgets or not self._popup_open():
            return
        synced = self._status == "synced"
        seekable = synced and self._session is not None and can_seek(self._session)
        for widget in self._line_widgets:
            if not synced or self._index < 0:
                state = "future" if synced else "plain"
            elif widget.index == self._index:
                state = "current"
            elif widget.index < self._index:
                state = "past"
            else:
                state = "future"
            widget.set_state(state, seekable)
        if scroll:
            QTimer.singleShot(0, self._scroll_to_current)

    def _scroll_to_current(self, animated: bool = True) -> None:
        if not self._popup_open() or not (0 <= self._index < len(self._line_widgets)):
            return
        # Class changes resize lines (the current one is usually bigger); settle the
        # layout first so the target is computed from final geometry.
        self._lyrics_layout.activate()
        widget = self._line_widgets[self._index]
        bar = self._scroll.verticalScrollBar()
        viewport = self._scroll.viewport()
        if bar is None or viewport is None:
            return
        target = widget.y() + widget.height() // 2 - viewport.height() // 2
        target = max(bar.minimum(), min(target, bar.maximum()))
        if abs(target - bar.value()) < 2:
            return
        self._scroll_anim.stop()
        if not animated:
            bar.setValue(target)
            return
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()
