"""Settings changed from the popup, saved next to config.yaml.

config.yaml stays hand-written and is never rewritten: it holds the defaults, and the
values saved here (``super-player.json`` in the YASB config folder) override them.
Each widget keeps its own section, keyed by its name in config.yaml.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.validation.widgets.yasb.super_player import SuperPlayerConfig

logger = logging.getLogger("super_player")

STATE_FILENAME = "super-player.json"

# Only these keys can be changed from the popup, so only these are read back.
EDITABLE_KEYS = (
    "source",
    "romanize",
    "translate",
    "translate_to",
    "bar_label",
    "show_progress",
    "hide_when_no_lyrics",
)


def state_path() -> Path:
    from settings import DEFAULT_CONFIG_DIRECTORY

    return Path(DEFAULT_CONFIG_DIRECTORY) / STATE_FILENAME


def load_state(path: Path) -> dict[str, dict[str, Any]]:
    """The whole file; an unreadable or malformed file counts as empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(name): dict(section)  # pyright: ignore[reportUnknownArgumentType]
        for name, section in data.items()  # pyright: ignore[reportUnknownVariableType]
        if isinstance(section, dict)
    }


def save_overrides(path: Path, widget: str, overrides: dict[str, Any]) -> None:
    """Replace this widget's section, keeping the others. Written atomically."""
    state = load_state(path)
    state[widget] = {key: overrides[key] for key in EDITABLE_KEYS if key in overrides}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".super-player-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_overrides(config: SuperPlayerConfig, overrides: dict[str, Any]) -> SuperPlayerConfig:
    """``config`` with the saved values on top. Invalid saved values are skipped one by one."""
    result = config
    for key in EDITABLE_KEYS:
        if key not in overrides:
            continue
        candidate = {**result.model_dump(), key: overrides[key]}
        try:
            result = SuperPlayerConfig.model_validate(candidate)
        except ValidationError:
            logger.warning("Ignoring invalid saved Super Player setting %s=%r", key, overrides[key])
    return result
