# pyright: reportPrivateUsage=false

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.systray import SystrayWidgetConfig
from core.widgets.yasb import systray
from core.widgets.yasb.systray import SystrayWidget

type MakeTray = Callable[..., SystrayWidget]


@pytest.fixture
def make_tray(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[MakeTray]:
    # No tray monitor or Explorer hook in tests.
    def no_client(self: SystrayWidget) -> None:
        pass

    monkeypatch.setattr(SystrayWidget, "setup_client", no_client)
    widgets: list[SystrayWidget] = []

    def make(**options: Any) -> SystrayWidget:
        config = SystrayWidgetConfig.model_validate(
            {"use_hook": False, "show_unpinned": False, "collapse_delay": 0, **options}
        )
        widget = SystrayWidget(config)
        widget.set_containers_visibility()
        widget.show()
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        widget.icon_check_timer.stop()
        widget.close()


def _send(widget: Any, kind: QEvent.Type) -> None:
    QApplication.sendEvent(widget, QEvent(kind))


def _fire_collapse(tray: SystrayWidget) -> None:
    assert tray._collapse_timer.isActive()
    tray._collapse_timer.stop()
    tray._collapse_if_idle()


def test_hover_is_off_by_default():
    config = SystrayWidgetConfig()
    assert config.expand_on_hover is False and config.collapse_delay == 400


def test_collapse_delay_is_bounded():
    with pytest.raises(ValueError):
        SystrayWidgetConfig.model_validate({"collapse_delay": -1})


def test_without_the_option_hover_does_nothing(make_tray: MakeTray):
    tray = make_tray()
    _send(tray, QEvent.Type.Enter)
    assert tray.unpinned_widget.isHidden()


def test_inline_expands_on_enter_and_collapses_after_leave(make_tray: MakeTray, monkeypatch: pytest.MonkeyPatch):
    tray = make_tray(expand_on_hover=True)
    monkeypatch.setattr(tray, "_cursor_over_tray", lambda: False)

    _send(tray, QEvent.Type.Enter)
    assert not tray.unpinned_widget.isHidden()
    assert tray.unpinned_vis_btn.isChecked() and tray.unpinned_vis_btn.text() == tray.config.label_expanded

    _send(tray, QEvent.Type.Leave)
    _fire_collapse(tray)
    assert tray.unpinned_widget.isHidden()
    assert not tray.unpinned_vis_btn.isChecked() and tray.unpinned_vis_btn.text() == tray.config.label_collapsed


def test_coming_back_before_the_delay_keeps_the_icons_open(make_tray: MakeTray):
    tray = make_tray(expand_on_hover=True, collapse_delay=5000)
    _send(tray, QEvent.Type.Enter)
    _send(tray, QEvent.Type.Leave)
    assert tray._collapse_timer.isActive()
    _send(tray, QEvent.Type.Enter)
    assert not tray._collapse_timer.isActive()
    assert not tray.unpinned_widget.isHidden()


def test_collapse_waits_while_the_cursor_is_still_over_the_tray(make_tray: MakeTray, monkeypatch: pytest.MonkeyPatch):
    tray = make_tray(expand_on_hover=True)
    over = True
    monkeypatch.setattr(tray, "_cursor_over_tray", lambda: over)
    _send(tray, QEvent.Type.Enter)
    _send(tray, QEvent.Type.Leave)
    _fire_collapse(tray)
    assert not tray.unpinned_widget.isHidden()  # a missed Leave must not hide icons under the cursor
    over = False
    _fire_collapse(tray)
    assert tray.unpinned_widget.isHidden()


def test_click_on_a_hover_expanded_tray_keeps_it_open(make_tray: MakeTray, monkeypatch: pytest.MonkeyPatch):
    tray = make_tray(expand_on_hover=True)
    monkeypatch.setattr(tray, "_cursor_over_tray", lambda: False)
    _send(tray, QEvent.Type.Enter)
    tray.unpinned_vis_btn.click()
    _send(tray, QEvent.Type.Leave)
    assert not tray._collapse_timer.isActive()
    assert not tray.unpinned_widget.isHidden() and tray.unpinned_vis_btn.isChecked()

    tray.unpinned_vis_btn.click()  # a second click collapses as before
    assert tray.unpinned_widget.isHidden()


def test_icons_opened_by_click_are_not_collapsed_by_leave(make_tray: MakeTray):
    tray = make_tray(expand_on_hover=True)
    tray.unpinned_vis_btn.click()
    assert not tray.unpinned_widget.isHidden()
    _send(tray, QEvent.Type.Enter)
    _send(tray, QEvent.Type.Leave)
    assert not tray._collapse_timer.isActive()


def test_inline_without_toggle_button_ignores_hover(make_tray: MakeTray):
    tray = make_tray(expand_on_hover=True, show_unpinned_button=False)
    assert not tray.unpinned_widget.isHidden()
    _send(tray, QEvent.Type.Enter)
    _send(tray, QEvent.Type.Leave)
    assert not tray._collapse_timer.isActive()


def test_collapse_is_postponed_during_a_drag(make_tray: MakeTray, monkeypatch: pytest.MonkeyPatch):
    tray = make_tray(expand_on_hover=True)
    monkeypatch.setattr(tray, "_cursor_over_tray", lambda: False)
    monkeypatch.setattr(systray.IconWidget, "drag_in_progress", True)
    _send(tray, QEvent.Type.Enter)
    _send(tray, QEvent.Type.Leave)
    _fire_collapse(tray)
    assert not tray.unpinned_widget.isHidden()


def test_popup_opens_without_focus_from_the_button_and_closes_after_leaving_it(
    make_tray: MakeTray, monkeypatch: pytest.MonkeyPatch
):
    tray = make_tray(expand_on_hover=True, show_in_popup=True)
    popup = tray._systray_popup
    monkeypatch.setattr(tray, "_cursor_over_tray", lambda: False)

    _send(tray.pinned_widget, QEvent.Type.Enter)  # pinned icons stay reachable
    assert not popup.isVisible()

    _send(tray.unpinned_vis_btn, QEvent.Type.Enter)
    assert popup.is_visible
    assert popup.testAttribute(systray.Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert tray.unpinned_vis_btn.isChecked()

    _send(tray.unpinned_vis_btn, QEvent.Type.Leave)
    _send(popup, QEvent.Type.Enter)  # moving onto the grid cancels the collapse
    assert not tray._collapse_timer.isActive()
    _send(popup, QEvent.Type.Leave)
    _fire_collapse(tray)
    assert not popup.is_visible
    assert not tray.unpinned_vis_btn.isChecked()


def test_popup_click_after_hover_activates_it_and_keeps_it(make_tray: MakeTray, monkeypatch: pytest.MonkeyPatch):
    tray = make_tray(expand_on_hover=True, show_in_popup=True)
    popup = tray._systray_popup
    _send(tray.unpinned_vis_btn, QEvent.Type.Enter)
    tray.unpinned_vis_btn.click()
    assert popup.is_visible and not popup.testAttribute(systray.Qt.WidgetAttribute.WA_ShowWithoutActivating)
    _send(tray.unpinned_vis_btn, QEvent.Type.Leave)
    assert not tray._collapse_timer.isActive()
    popup.hide()
