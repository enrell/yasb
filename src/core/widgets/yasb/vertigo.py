"""Workspaces of vertigo, the vertical-scrolling tiling WM, like Waybar's Hyprland
workspaces in Omarchy: 1..5 always, higher ones while occupied or active.

One widget per bar shows the workspaces of that bar's monitor. State comes from
vertigo's named pipe through a shared poller thread (``VertigoService``).
"""

import logging
from collections.abc import Callable
from typing import Any, override

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QPushButton

from core.utils.tooltip import set_tooltip
from core.utils.utilities import refresh_widget_style
from core.validation.widgets.yasb.vertigo import VertigoWorkspacesConfig
from core.widgets.base import BaseWidget
from core.widgets.services.vertigo.client import VertigoService
from core.widgets.services.vertigo.state import MonitorState, WorkspaceItem, find_monitor, workspace_items

logger = logging.getLogger("vertigo")


class WorkspacesWidget(BaseWidget):
    validation_schema = VertigoWorkspacesConfig

    def __init__(self, config: VertigoWorkspacesConfig):
        super().__init__(class_name=f"vertigo-workspaces {config.class_name}".strip())
        self.config = config
        self._init_container()
        self._buttons: list[QPushButton] = []
        self._shown: tuple[Any, ...] | None = None
        self.monitor_id = ""
        self.online = False

        self._service = VertigoService.instance(self.config.update_interval)
        self._service.state_changed.connect(self._on_state)
        # Until the first poll, show the persistent workspaces dimmed. The bar manager sets
        # screen_name right after __init__, so the monitor is resolved on the next tick too.
        self._on_state(self._service.latest)
        QTimer.singleShot(0, lambda: self._on_state(self._service.latest))

    # ---------------------------------------------------------------- state
    def _screen_hint(self) -> tuple[str, tuple[float, float] | None]:
        """Name and physical center of the bar's screen (set by the bar manager after __init__)."""
        screen = next((s for s in QApplication.screens() if self.screen_name and s.name() == self.screen_name), None)
        screen = screen or self.screen()
        if screen is None:
            return self.screen_name or "", None
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        center = (geometry.center().x() * ratio, geometry.center().y() * ratio)
        return self.screen_name or screen.name(), center

    def resolve_monitor(self, monitors: tuple[MonitorState, ...]) -> MonitorState | None:
        name, center = self._screen_hint()
        return find_monitor(monitors, self.config.monitor, name, center)

    @pyqtSlot(object)
    def _on_state(self, monitors: tuple[MonitorState, ...] | None) -> None:
        monitor = self.resolve_monitor(monitors) if monitors else None
        self.online = monitor is not None
        if monitor is not None:
            self.monitor_id = monitor.id
            items = workspace_items(monitor, self.config.persistent_workspaces)
        else:
            persistent = max(1, self.config.persistent_workspaces)
            items = [WorkspaceItem(i, "empty", 0) for i in range(1, persistent + 1)]
        self._render(items)

    def _render(self, items: list[WorkspaceItem]) -> None:
        hide = not self.online and self.config.offline == "hide"
        if hide != self.isHidden():
            self.setVisible(not hide)
        key = (self.online, self.monitor_id, tuple(items))
        if key == self._shown:
            return  # redraw only on change
        self._shown = key

        self._widget_container.setProperty("class", f"widget-container{'' if self.online else ' offline'}")
        refresh_widget_style(self._widget_container)

        while len(self._buttons) < len(items):
            button = QPushButton()
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(self._click_handler(button))
            self._widget_container_layout.addWidget(button)
            self._buttons.append(button)
        for button in self._buttons[len(items) :]:
            button.hide()

        labels = {
            "active": self.config.label_active,
            "occupied": self.config.label_occupied,
            "empty": self.config.label_empty,
        }
        for button, item in zip(self._buttons, items, strict=False):
            button.setProperty("workspace", item.index)
            button.setText(labels[item.status].format(index=item.index, windows=item.windows))
            button.setProperty("class", f"ws-btn {item.status}{'' if self.online else ' offline'}")
            button.setEnabled(self.online)
            if self.config.tooltip:
                set_tooltip(button, self.config.tooltip_label.format(index=item.index, windows=item.windows))
            button.show()
            refresh_widget_style(button)

    # ---------------------------------------------------------- interaction
    def _click_handler(self, button: QPushButton) -> Callable[[bool], None]:
        def clicked(_checked: bool = False) -> None:
            self._on_click(button)

        return clicked

    def _on_click(self, button: QPushButton) -> None:
        index = button.property("workspace")
        if self.online and isinstance(index, int):
            self.switch_to(f"focus-workspace {index}")

    def switch_to(self, action: str) -> None:
        if self.monitor_id:
            self._service.focus_workspace(self.monitor_id, action)

    @override
    def wheelEvent(self, a0: QWheelEvent | None) -> None:
        if a0 is None or not self.online or not self.config.scroll_to_switch:
            return
        forward = a0.angleDelta().y() < 0
        if self.config.reverse_scroll:
            forward = not forward
        self.switch_to("focus-workspace-next" if forward else "focus-workspace-prev")
        a0.accept()
