"""Runs lookups, translation and romanization off the UI thread.

Results come back through Qt signals, which are queued onto the UI thread because the
worker emits them from another thread. Each job carries a request id so the widget can
drop replies that belong to a previous track.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.widgets.services.super_player.lyrics import LyricsResult, TrackQuery, fetch_lyrics, translate_lines
from core.widgets.services.super_player.romanize import romanize_lines

logger = logging.getLogger("super_player")


class LyricsWorker(QObject):
    """One shared pool for every Super Player widget."""

    lyrics_ready = pyqtSignal(int, object)  # request id, LyricsResult
    translation_ready = pyqtSignal(int, object)  # request id, list[str] | None
    romanization_ready = pyqtSignal(int, object)  # request id, list[str]

    _instance: LyricsWorker | None = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> LyricsWorker:
        with cls._lock:
            if cls._instance is None:
                cls._instance = LyricsWorker()
            return cls._instance

    def __init__(self, fetch: Callable[[TrackQuery], LyricsResult] = fetch_lyrics):
        super().__init__()
        self._fetch = fetch
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="SuperPlayer")
        self._next_id = 0
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def next_request_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _submit(self, signal: Any, request_id: int, job: Callable[[], object]) -> None:
        def run() -> None:
            try:
                result = job()
            except Exception as e:
                logger.error("Super Player background job failed: %s", e, exc_info=True)
                result = None
            try:
                signal.emit(request_id, result)
            except RuntimeError:
                pass  # the worker was deleted while the job ran (shutdown)

        try:
            self._pool.submit(run)
        except RuntimeError:
            pass  # pool already shut down

    def fetch_lyrics(self, request_id: int, query: TrackQuery) -> None:
        self._submit(self.lyrics_ready, request_id, lambda: self._fetch(query))

    def translate(self, request_id: int, texts: Sequence[str], language: str) -> None:
        texts = list(texts)
        self._submit(self.translation_ready, request_id, lambda: translate_lines(texts, language))

    def romanize(self, request_id: int, texts: Sequence[str]) -> None:
        texts = list(texts)
        self._submit(self.romanization_ready, request_id, lambda: romanize_lines(texts))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
