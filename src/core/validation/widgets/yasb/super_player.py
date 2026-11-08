from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig


class SuperPlayerIconsConfig(CustomBaseModel):
    music: str = "\U000f075a"
    prev_track: str = "\U000f04ae"
    next_track: str = "\U000f04ad"
    play: str = "\U000f040a"
    pause: str = "\U000f03e4"
    volume: str = "\U000f057e"
    muted: str = "\U000f0581"
    settings: str = "\U000f0493"
    back: str = "\U000f004d"


class SuperPlayerPopupConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: Literal["normal", "small"] = "normal"
    border_color: str = "System"
    alignment: Literal["left", "right", "center"] = "right"
    direction: Literal["up", "down"] = "down"
    offset_top: int = 6
    offset_left: int = 0
    width: int = Field(default=400, ge=240, le=1200)
    lyrics_height: int = Field(default=300, ge=80, le=1600)
    show_cover: bool = True
    cover_size: int = Field(default=64, ge=24, le=256)


class SuperPlayerCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_popup"
    on_middle: str = "toggle_play_pause"
    on_right: str = "open_settings"


class SuperPlayerConfig(CustomBaseModel):
    class_name: str = ""
    source: str = "auto"
    bar_label: Literal["lyric", "track", "icon"] = "lyric"
    max_label_width: int = Field(default=240, ge=40, le=1200)
    scroll_label: bool = True
    show_icon: bool = True
    show_progress: bool = True
    hide_when_no_lyrics: bool = False
    romanize: Literal["off", "replace", "below"] = "off"
    translate: str = "off"
    translate_to: str = "pt-BR"
    ui_language: Literal["en", "pt"] = "en"
    tooltip: bool = True
    volume_step: int = Field(default=5, ge=1, le=25)
    icons: SuperPlayerIconsConfig = SuperPlayerIconsConfig()
    popup: SuperPlayerPopupConfig = SuperPlayerPopupConfig()
    callbacks: SuperPlayerCallbacksConfig = SuperPlayerCallbacksConfig()
    keybindings: list[KeybindingConfig] = []
