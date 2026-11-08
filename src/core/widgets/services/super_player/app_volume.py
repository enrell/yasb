"""Volume and mute of the player's own audio sessions (Windows mixer, per app).

GSMTC has no volume, so the player is matched to its audio sessions like the media
widget's popup does, by the process AUMID and then by the executable, extended to the
player's child processes: many players play audio from a helper (TIDAL from
``TIDALPlayer.exe``, Chromium browsers from an audio service process). All sessions of
the player are changed together.
"""

import logging
import os
from collections.abc import Iterable
from typing import Any

from pycaw.pycaw import AudioUtilities

from core.utils.win32.aumid import get_aumid_for_process
from core.utils.win32.aumid_process import get_process_name_for_aumid
from core.utils.win32.bindings.kernel32 import ProcessEntry, snapshot_processes

logger = logging.getLogger("super_player")


def _process_of(session: Any) -> Any | None:
    try:
        return getattr(session, "Process", None)
    except Exception:
        return None


# Hosts that start unrelated apps: their children are never part of the player.
SHELL_HOSTS = {"explorer.exe", "applicationframehost.exe", "svchost.exe", "runtimebroker.exe", "sihost.exe"}


def process_tree(processes: Iterable[ProcessEntry], exe_name: str) -> set[int]:
    """PIDs of every process named ``exe_name`` and all of their descendants."""
    processes = list(processes)
    target = exe_name.lower()
    tree = {p.pid for p in processes if p.exe and os.path.basename(p.exe).lower() == target}
    if target in SHELL_HOSTS:
        return tree
    children: dict[int, list[int]] = {}
    for p in processes:
        if p.pid != p.parent_pid:
            children.setdefault(p.parent_pid, []).append(p.pid)
    pending = list(tree)
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in tree:
                tree.add(child)
                pending.append(child)
    return tree


def find_audio_sessions(aumid: str) -> list[Any]:
    """Audio sessions that belong to the player with this AUMID."""
    if not aumid:
        return []
    try:
        sessions: list[Any] = list(AudioUtilities.GetAllSessions())
    except Exception as e:
        logger.debug("Could not list audio sessions: %s", e)
        return []

    target = aumid.lower()
    matched: list[Any] = []
    for session in sessions:
        process = _process_of(session)
        try:
            if process and process.pid and (get_aumid_for_process(int(process.pid)) or "").lower() == target:
                matched.append(session)
        except Exception:
            continue
    if matched:
        return matched

    exe = aumid if aumid.lower().endswith(".exe") else get_process_name_for_aumid(aumid) or ""
    if not exe:
        return []
    pids = process_tree(snapshot_processes(), exe)
    for session in sessions:
        process = _process_of(session)
        try:
            if process and int(process.pid) in pids:
                matched.append(session)
        except Exception:
            continue
    return matched


class AppVolume:
    """Cached binding to one player's audio sessions."""

    def __init__(self) -> None:
        self._aumid = ""
        self._interfaces: list[Any] = []

    def bind(self, aumid: str, force: bool = False) -> bool:
        if force or aumid != self._aumid or not self._interfaces:
            self._aumid = aumid
            self._interfaces = [
                iface
                for session in find_audio_sessions(aumid)
                if (iface := getattr(session, "SimpleAudioVolume", None)) is not None
            ]
        return bool(self._interfaces)

    @property
    def supported(self) -> bool:
        return bool(self._interfaces)

    def _first(self) -> Any | None:
        return self._interfaces[0] if self._interfaces else None

    def volume(self) -> float | None:
        iface = self._first()
        if iface is None:
            return None
        try:
            return float(iface.GetMasterVolume())
        except Exception:
            self._interfaces = []  # the session ended; rebind on next use
            return None

    def muted(self) -> bool:
        iface = self._first()
        if iface is None:
            return False
        try:
            return bool(iface.GetMute())
        except Exception:
            return False

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        for iface in self._interfaces:
            try:
                iface.SetMasterVolume(value, None)
                if value > 0.001 and iface.GetMute():
                    iface.SetMute(False, None)
            except Exception as e:
                logger.debug("Could not set the player volume: %s", e)

    def set_muted(self, muted: bool) -> None:
        for iface in self._interfaces:
            try:
                iface.SetMute(muted, None)
            except Exception as e:
                logger.debug("Could not mute the player: %s", e)
