from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class VertigoWorkspacesConfig(CustomBaseModel):
    class_name: str = ""
    monitor: str = ""
    persistent_workspaces: int = Field(default=5, ge=0, le=9)
    label_active: str = "{index}"
    label_occupied: str = "{index}"
    label_empty: str = "{index}"
    tooltip: bool = True
    tooltip_label: str = "Workspace {index}: {windows} windows"
    scroll_to_switch: bool = True
    reverse_scroll: bool = False
    offline: Literal["dim", "hide"] = "dim"
    update_interval: int = Field(default=300, ge=100, le=5000)
