"""vertigo's `query state` reply, reduced to what a workspace bar needs.

Pure Python: parsing, the workspace list a bar shows, monitor mapping and the
direction to another monitor. Unit tested without the pipe.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

WORKSPACE_COUNT = 9  # vertigo's workspaces are fixed per monitor

type WorkspaceStatus = Literal["active", "occupied", "empty"]


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def contains(self, point: tuple[float, float]) -> bool:
        px, py = point
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


@dataclass(frozen=True, slots=True)
class MonitorState:
    id: str
    area: Rect
    focused: bool
    active_workspace: int
    # workspace number (1-based) -> number of windows, tiled and floating
    windows: dict[int, int] = field(default_factory=lambda: dict[int, int]())


@dataclass(frozen=True, slots=True)
class WorkspaceItem:
    index: int
    status: WorkspaceStatus
    windows: int


def _int(value: Any, default: int = 0) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _rect(value: Any) -> Rect:
    data: dict[str, Any] = value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    return Rect(_int(data.get("x")), _int(data.get("y")), _int(data.get("w")), _int(data.get("h")))


def _window_count(workspace: dict[str, Any]) -> int:
    count = 0
    rows: Any = workspace.get("rows")
    row: Any
    for row in rows if isinstance(rows, list) else []:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(row, dict):
            windows = row.get("windows")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            count += len(windows) if isinstance(windows, list) else 0  # pyright: ignore[reportUnknownArgumentType]
    floating = workspace.get("floating")
    count += len(floating) if isinstance(floating, list) else 0  # pyright: ignore[reportUnknownArgumentType]
    return count


def parse_state(data: Any) -> tuple[MonitorState, ...]:
    """Monitors from the ``data`` of ``{"cmd":"query","what":"state"}``.

    vertigo lists only the workspaces that hold something; the others are empty.
    """
    if not isinstance(data, dict):
        return ()
    raw_monitors = data.get("monitors")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    monitors: list[MonitorState] = []
    for raw in raw_monitors if isinstance(raw_monitors, list) else []:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(raw, dict):
            continue
        monitor: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
        windows: dict[int, int] = {}
        raw_workspaces: Any = monitor.get("workspaces")
        workspace: Any
        for workspace in raw_workspaces if isinstance(raw_workspaces, list) else []:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(workspace, dict):
                index = _int(workspace.get("index"))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if index > 0:
                    windows[index] = _window_count(workspace)  # pyright: ignore[reportUnknownArgumentType]
        monitors.append(
            MonitorState(
                id=str(monitor.get("id") or ""),
                area=_rect(monitor.get("area")),
                focused=monitor.get("focused") is True,
                active_workspace=_int(monitor.get("active_workspace"), 1),
                windows=windows,
            )
        )
    return tuple(monitors)


def workspace_items(monitor: MonitorState, persistent: int = 5, count: int = WORKSPACE_COUNT) -> list[WorkspaceItem]:
    """What the bar shows, like Waybar's Hyprland workspaces in Omarchy.

    Workspaces 1..``persistent`` always; higher ones only while occupied or active.
    """
    items: list[WorkspaceItem] = []
    for index in range(1, count + 1):
        windows = monitor.windows.get(index, 0)
        active = index == monitor.active_workspace
        if index > persistent and not active and windows == 0:
            continue
        status: WorkspaceStatus = "active" if active else ("occupied" if windows else "empty")
        items.append(WorkspaceItem(index, status, windows))
    return items


def normalize_id(monitor_id: str) -> str:
    return monitor_id.strip().upper()


def find_monitor(
    monitors: Sequence[MonitorState],
    explicit: str = "",
    screen_name: str = "",
    screen_center: tuple[float, float] | None = None,
) -> MonitorState | None:
    """The vertigo monitor a bar belongs to.

    An explicit ``monitor`` option wins, then the Qt screen name (``\\\\.\\DISPLAY2`` on
    Windows), then the monitor whose area holds the center of the bar's screen.
    """
    for wanted in (explicit, screen_name):
        if wanted:
            for monitor in monitors:
                if normalize_id(monitor.id) == normalize_id(wanted):
                    return monitor
    if explicit:
        return None  # pinned to a monitor vertigo does not know (yet)
    if screen_center is not None:
        for monitor in monitors:
            if monitor.area.contains(screen_center):
                return monitor
    return None


def direction_to(origin: Rect, target: Rect) -> Literal["left", "right", "up", "down"]:
    """vertigo's focus-monitor direction from one monitor to another."""
    (ox, oy), (tx, ty) = origin.center, target.center
    dx, dy = tx - ox, ty - oy
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"
