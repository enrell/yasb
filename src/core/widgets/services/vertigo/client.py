"""Talks to vertigo over its named pipe and polls the state on a background thread.

Protocol (vertigo's crate ``vertigo``, ``ipc.rs``): connect to ``\\\\.\\pipe\\vertigo``,
write one JSON line, read one JSON line back, the server disconnects::

    {"cmd":"query","what":"state"}                 -> {"ok":true,"data":{...}}
    {"cmd":"action","action":"focus-workspace 2"}  -> {"ok":true}

vertigo has no event subscription yet, so the state is polled. Signals only fire when
what a bar shows changes.
"""

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.widgets.services.vertigo.state import MonitorState, direction_to, normalize_id, parse_state

logger = logging.getLogger("vertigo")

DEFAULT_PIPE = "vertigo"
CONNECT_TIMEOUT = 2.0
MAX_REPLY_BYTES = 4 * 1024 * 1024
ERROR_PIPE_BUSY = 231
MAX_MONITOR_HOPS = 4

type Transport = Callable[[str], str]


class VertigoUnavailable(Exception):
    """vertigo is not running, or did not answer."""


def pipe_transport(name: str = DEFAULT_PIPE) -> Transport:
    """One request per connection, like ``vertigo.exe`` itself."""
    path = rf"\\.\pipe\{name}"

    def send(line: str) -> str:
        start = time.monotonic()
        while True:
            try:
                pipe = open(path, "r+b", buffering=0)  # noqa: SIM115
                break
            except FileNotFoundError as e:
                # Not found can also be the server between two instances.
                if time.monotonic() - start > 0.3:
                    raise VertigoUnavailable(f"{path} not found") from e
            except OSError as e:
                if getattr(e, "winerror", None) != ERROR_PIPE_BUSY or time.monotonic() - start > CONNECT_TIMEOUT:
                    raise VertigoUnavailable(str(e)) from e
            time.sleep(0.02)
        reply = bytearray()
        with pipe:
            try:
                pipe.write(line.encode("utf-8") + b"\n")
                while b"\n" not in reply:
                    chunk = pipe.read(65536)
                    if not chunk:
                        break
                    reply += chunk
                    if len(reply) > MAX_REPLY_BYTES:
                        raise VertigoUnavailable("reply too large")
            except OSError as e:
                # After its reply the server disconnects; reads then fail instead of EOF.
                if b"\n" not in reply:
                    raise VertigoUnavailable(str(e)) from e
        return bytes(reply).split(b"\n", 1)[0].decode("utf-8", errors="replace")

    return send


class VertigoClient:
    def __init__(self, transport: Transport | None = None):
        self._transport = transport or pipe_transport()

    def request(self, payload: dict[str, Any]) -> Any:
        """Send a request; returns ``data`` (or None). Raises VertigoUnavailable or ValueError."""
        try:
            reply = json.loads(self._transport(json.dumps(payload)))
        except json.JSONDecodeError as e:
            raise VertigoUnavailable(f"invalid reply: {e}") from e
        if not isinstance(reply, dict):
            raise VertigoUnavailable("invalid reply")
        response: dict[str, Any] = reply  # pyright: ignore[reportUnknownVariableType]
        if response.get("ok") is not True:
            raise ValueError(str(response.get("error") or "vertigo refused the request"))
        return response.get("data")

    def state(self) -> tuple[MonitorState, ...]:
        return parse_state(self.request({"cmd": "query", "what": "state"}))

    def action(self, action: str) -> None:
        self.request({"cmd": "action", "action": action})

    def focus_workspace(self, monitor_id: str, action: str) -> None:
        """Run a workspace action (``focus-workspace 3``, ``focus-workspace-next``) on a monitor.

        vertigo's workspace actions apply to the focused monitor, so focus moves to the
        target monitor first (``focus-monitor <direction>``), hopping until it gets there.
        """
        wanted = normalize_id(monitor_id)
        for _ in range(MAX_MONITOR_HOPS):
            monitors = self.state()
            target = next((m for m in monitors if normalize_id(m.id) == wanted), None)
            focused = next((m for m in monitors if m.focused), None)
            if target is None:
                raise ValueError(f"vertigo does not manage {monitor_id}")
            if focused is None or normalize_id(focused.id) == wanted:
                break
            self.action(f"focus-monitor {direction_to(focused.area, target.area)}")
        self.action(action)


class VertigoService(QObject):
    """One poller for every bar. ``state_changed`` carries the monitors, or None while
    vertigo is not running (the poller keeps trying, so it reconnects by itself)."""

    state_changed = pyqtSignal(object)

    _instance: VertigoService | None = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls, interval_ms: int = 300) -> VertigoService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = VertigoService(interval_ms=interval_ms)
                cls._instance.start()
            return cls._instance

    def __init__(self, client: VertigoClient | None = None, interval_ms: int = 300):
        super().__init__()
        self._client = client or VertigoClient()
        self._interval = interval_ms / 1000
        self._commands: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last: tuple[MonitorState, ...] | None = None
        self._reported = False  # whether anything was emitted yet
        self.latest: tuple[MonitorState, ...] | None = None
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="VertigoPoller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._commands.put(None)

    def focus_workspace(self, monitor_id: str, action: str) -> None:
        """Queue a workspace action for a monitor; runs on the poller thread."""
        self._commands.put((monitor_id, action))

    def poll_once(self) -> None:
        """Read the state and emit it when it changed. Runs on the poller thread."""
        try:
            monitors: tuple[MonitorState, ...] | None = self._client.state()
        except VertigoUnavailable, ValueError:
            monitors = None
        if self._reported and monitors == self._last:
            return
        if monitors is None and self._last is not None:
            logger.info("vertigo is not answering; will keep trying")
        elif monitors is not None and self._last is None and self._reported:
            logger.info("vertigo is back")
        self._last = monitors
        self._reported = True
        self.latest = monitors
        try:
            self.state_changed.emit(monitors)
        except RuntimeError:
            pass  # deleted during shutdown

    def _run_command(self, command: tuple[str, str]) -> None:
        monitor_id, action = command
        try:
            self._client.focus_workspace(monitor_id, action)
        except (VertigoUnavailable, ValueError) as e:
            logger.warning("vertigo %s on %s failed: %s", action, monitor_id, e)

    def _run(self) -> None:
        while self._running:
            self.poll_once()
            try:
                command = self._commands.get(timeout=self._interval)
            except queue.Empty:
                continue
            if command is None:
                break
            self._run_command(command)
