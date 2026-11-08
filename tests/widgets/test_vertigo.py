# pyright: reportPrivateUsage=false

import json
import threading
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.utils.win32.bindings.kernel32 import (
    CloseHandle,
    ConnectNamedPipe,
    CreateNamedPipe,
    DisconnectNamedPipe,
    ReadFile,
    WriteFile,
)
from core.utils.win32.constants import INVALID_HANDLE_VALUE, PIPE_ACCESS_DUPLEX, PIPE_WAIT
from core.validation.widgets.yasb.vertigo import VertigoWorkspacesConfig
from core.widgets.services.vertigo.client import VertigoClient, VertigoService, VertigoUnavailable, pipe_transport
from core.widgets.services.vertigo.state import (
    MonitorState,
    Rect,
    direction_to,
    find_monitor,
    parse_state,
    workspace_items,
)


def _workspace(index: int, rows: int = 1, floating: int = 0) -> dict[str, Any]:
    return {
        "index": index,
        "rows": [{"windows": [{"hwnd": f"0x{index}{r}"}]} for r in range(rows)],
        "floating": [f"0xf{i}" for i in range(floating)],
    }


def _state(active2: int = 1, active1: int = 1, focused: str = r"\\.\DISPLAY2") -> dict[str, Any]:
    """Shaped like `vertigo query state`: only non-empty workspaces are listed."""
    return {
        "monitors": [
            {
                "id": r"\\.\DISPLAY2",
                "area": {"x": 0, "y": 0, "w": 1920, "h": 1080},
                "focused": focused == r"\\.\DISPLAY2",
                "active_workspace": active2,
                "workspaces": [_workspace(1, rows=2), _workspace(7, floating=1)],
            },
            {
                "id": r"\\.\DISPLAY1",
                "area": {"x": -1920, "y": -56, "w": 1920, "h": 1200},
                "focused": focused == r"\\.\DISPLAY1",
                "active_workspace": active1,
                "workspaces": [_workspace(2)],
            },
        ],
        "windows": [{"title": "<b>ignored</b>"}],
    }


# --- parsing and what the bar shows -----------------------------------------------------


def test_parse_state_counts_tiled_and_floating_windows():
    main, notebook = parse_state(_state())
    assert main.id == r"\\.\DISPLAY2" and main.focused and main.area == Rect(0, 0, 1920, 1080)
    assert main.windows == {1: 2, 7: 2}
    assert notebook.windows == {2: 1} and not notebook.focused
    assert parse_state(None) == () and parse_state({"monitors": "x"}) == ()


def test_persistent_one_to_five_plus_occupied_and_active():
    main = parse_state(_state(active2=9))[0]
    items = workspace_items(main, persistent=5)
    assert [(i.index, i.status, i.windows) for i in items] == [
        (1, "occupied", 2),
        (2, "empty", 0),
        (3, "empty", 0),
        (4, "empty", 0),
        (5, "empty", 0),
        (7, "occupied", 2),
        (9, "active", 0),  # empty but active: shown
    ]
    assert [i.index for i in workspace_items(main, persistent=0)] == [1, 7, 9]


def test_active_wins_over_occupied():
    main = parse_state(_state(active2=1))[0]
    assert workspace_items(main)[0].status == "active"


# --- monitor mapping ----------------------------------------------------------------------


def test_monitor_mapping_by_option_name_and_geometry():
    monitors = parse_state(_state())
    assert find_monitor(monitors, explicit=r"\\.\display1").id == r"\\.\DISPLAY1"  # pyright: ignore[reportOptionalMemberAccess]
    assert find_monitor(monitors, screen_name=r"\\.\DISPLAY2").id == r"\\.\DISPLAY2"  # pyright: ignore[reportOptionalMemberAccess]
    # YASB's "22B1WG5" is not a vertigo id: fall back to the screen's center.
    assert find_monitor(monitors, screen_name="22B1WG5", screen_center=(960, 540)).id == r"\\.\DISPLAY2"  # pyright: ignore[reportOptionalMemberAccess]
    assert find_monitor(monitors, screen_center=(-960, 544)).id == r"\\.\DISPLAY1"  # pyright: ignore[reportOptionalMemberAccess]
    assert find_monitor(monitors, explicit=r"\\.\DISPLAY9", screen_center=(960, 540)) is None
    assert find_monitor(monitors, screen_center=(5000, 5000)) is None


def test_direction_between_monitors():
    main, notebook = parse_state(_state())
    assert direction_to(main.area, notebook.area) == "left"
    assert direction_to(notebook.area, main.area) == "right"
    assert direction_to(Rect(0, 0, 100, 100), Rect(0, 200, 100, 100)) == "down"


# --- commands -----------------------------------------------------------------------------


class FakeVertigo:
    """In-process vertigo: answers requests and applies focus-monitor / focus-workspace."""

    def __init__(self) -> None:
        self.state = _state()
        self.requests: list[dict[str, Any]] = []
        self.running = True

    def _monitor(self, focused: bool) -> dict[str, Any]:
        return next(m for m in self.state["monitors"] if m["focused"] is focused)

    def __call__(self, line: str) -> str:
        if not self.running:
            raise VertigoUnavailable("not running")
        request = json.loads(line)
        self.requests.append(request)
        if request == {"cmd": "query", "what": "state"}:
            return json.dumps({"ok": True, "data": self.state})
        action: str = request["action"]
        if action.startswith("focus-monitor"):
            for monitor in self.state["monitors"]:
                monitor["focused"] = not monitor["focused"]
        elif action.startswith("focus-workspace "):
            self._monitor(True)["active_workspace"] = int(action.split()[1])
        else:
            return json.dumps({"ok": False, "error": f"unknown action '{action}'"})
        return json.dumps({"ok": True})


def _actions(fake: FakeVertigo) -> list[str]:
    return [r["action"] for r in fake.requests if r["cmd"] == "action"]


def test_workspace_on_another_monitor_focuses_that_monitor_first():
    fake = FakeVertigo()
    VertigoClient(fake).focus_workspace(r"\\.\DISPLAY1", "focus-workspace 3")
    assert _actions(fake) == ["focus-monitor left", "focus-workspace 3"]
    assert parse_state(fake.state)[1].active_workspace == 3


def test_workspace_on_the_focused_monitor_is_one_action():
    fake = FakeVertigo()
    VertigoClient(fake).focus_workspace(r"\\.\DISPLAY2", "focus-workspace 4")
    assert _actions(fake) == ["focus-workspace 4"]


def test_errors_from_vertigo_are_raised():
    fake = FakeVertigo()
    with pytest.raises(ValueError, match="unknown action"):
        VertigoClient(fake).action("reboot")
    with pytest.raises(ValueError):
        VertigoClient(fake).focus_workspace(r"\\.\DISPLAY9", "focus-workspace 1")


# --- the poller ----------------------------------------------------------------------------


def test_poller_emits_only_on_change_and_reconnects(qapp: QApplication):
    fake = FakeVertigo()
    service = VertigoService(VertigoClient(fake))
    seen: list[Any] = []
    service.state_changed.connect(seen.append)

    service.poll_once()
    service.poll_once()  # same state: nothing new
    assert len(seen) == 1 and isinstance(seen[0], tuple)

    fake.state["windows"] = [{"title": "another title"}]  # not shown by the bar
    service.poll_once()
    assert len(seen) == 1

    fake.state["monitors"][0]["active_workspace"] = 2
    service.poll_once()
    assert len(seen) == 2

    fake.running = False
    service.poll_once()
    service.poll_once()
    assert seen[2:] == [None]

    fake.running = True
    service.poll_once()
    assert len(seen) == 4 and seen[3][0].active_workspace == 2  # reconnected


def test_poller_runs_queued_commands(qapp: QApplication):
    fake = FakeVertigo()
    service = VertigoService(VertigoClient(fake))
    service.focus_workspace(r"\\.\DISPLAY1", "focus-workspace 5")
    command = service._commands.get_nowait()
    assert command is not None
    service._run_command(command)
    assert _actions(fake) == ["focus-monitor left", "focus-workspace 5"]


# --- the real pipe ------------------------------------------------------------------------


@pytest.fixture
def pipe_server() -> Iterator[tuple[str, list[str]]]:
    """A one-shot named pipe server that answers like vertigo: one line in, one line out."""
    name = f"yasb-test-vertigo-{uuid4().hex}"
    received: list[str] = []
    handle = CreateNamedPipe(rf"\\.\pipe\{name}", PIPE_ACCESS_DUPLEX, PIPE_WAIT, 1, 65536, 65536, 0, None)
    assert handle and handle != INVALID_HANDLE_VALUE

    def serve() -> None:
        ConnectNamedPipe(handle, None)
        data = b""
        while b"\n" not in data:
            ok, chunk = ReadFile(handle, 4096)
            if not ok or not chunk:
                break
            data += chunk
        received.append(data.decode())
        WriteFile(handle, json.dumps({"ok": True, "data": _state()}).encode() + b"\n")
        DisconnectNamedPipe(handle)  # vertigo disconnects right after its reply

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield name, received
    thread.join(timeout=5)
    CloseHandle(handle)


def test_pipe_transport_round_trip(pipe_server: tuple[str, list[str]]):
    name, received = pipe_server
    monitors = VertigoClient(pipe_transport(name)).state()
    assert received == ['{"cmd": "query", "what": "state"}\n']
    assert [m.id for m in monitors] == [r"\\.\DISPLAY2", r"\\.\DISPLAY1"]


def test_missing_pipe_means_vertigo_is_not_running():
    with pytest.raises(VertigoUnavailable):
        VertigoClient(pipe_transport(f"yasb-test-missing-{uuid4().hex}")).state()


# --- the widget ---------------------------------------------------------------------------


class FakeService(QObject):
    state_changed = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.latest: Any = None
        self.commands: list[tuple[str, str]] = []

    def focus_workspace(self, monitor_id: str, action: str) -> None:
        self.commands.append((monitor_id, action))


@pytest.fixture
def make_widget(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    from core.widgets.yasb import vertigo as module

    service = FakeService()

    def instance(interval_ms: int = 300) -> FakeService:
        return service

    monkeypatch.setattr(module.VertigoService, "instance", instance)
    widgets: list[Any] = []

    def make(screen_name: str = r"\\.\DISPLAY2", **options: Any) -> Any:
        widget = module.WorkspacesWidget(VertigoWorkspacesConfig.model_validate(options))
        widget.screen_name = screen_name
        widgets.append(widget)
        return widget

    yield make, service
    for widget in widgets:
        widget.close()


def _buttons(widget: Any) -> list[tuple[str, str]]:
    return [(b.text(), b.property("class")) for b in widget._buttons if not b.isHidden()]


def test_widget_shows_its_monitor_and_switches_on_click(make_widget: Any):
    make, service = make_widget
    main = make(label_active="󱓻")
    notebook = make(screen_name=r"\\.\DISPLAY1")
    state: tuple[MonitorState, ...] = parse_state(_state(active2=7))
    service.state_changed.emit(state)
    assert _buttons(main) == [
        ("1", "ws-btn occupied"),
        ("2", "ws-btn empty"),
        ("3", "ws-btn empty"),
        ("4", "ws-btn empty"),
        ("5", "ws-btn empty"),
        ("󱓻", "ws-btn active"),
    ]
    assert [t for t, _ in _buttons(notebook)] == ["1", "2", "3", "4", "5"]
    assert _buttons(notebook)[1][1] == "ws-btn occupied"

    notebook._buttons[2].click()
    assert service.commands == [(r"\\.\DISPLAY1", "focus-workspace 3")]


def test_widget_dims_or_hides_while_vertigo_is_down(make_widget: Any):
    make, service = make_widget
    dim = make()
    hide = make(offline="hide")
    hide.show()
    service.state_changed.emit(None)
    assert all("offline" in c for _, c in _buttons(dim)) and len(_buttons(dim)) == 5
    assert not any(b.isEnabled() for b in dim._buttons)
    assert hide.isHidden()
    service.state_changed.emit(parse_state(_state()))
    assert not hide.isHidden() and dim.online


def test_widget_redraws_only_on_change(make_widget: Any):
    make, service = make_widget
    widget = make()
    state = parse_state(_state())
    service.state_changed.emit(state)
    first = widget._shown
    widget._buttons[0].setText("touched")
    service.state_changed.emit(parse_state(_state()))
    assert widget._shown == first and widget._buttons[0].text() == "touched"
