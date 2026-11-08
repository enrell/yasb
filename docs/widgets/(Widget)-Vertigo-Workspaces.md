# Vertigo Workspaces Widget

Workspaces of [vertigo](https://github.com/enrell/vertigo), a vertical-scrolling tiling window manager for Windows, shown like Waybar's Hyprland workspaces in [Omarchy](https://omarchy.org): workspaces 1 to 5 are always there, and higher ones appear while they hold windows or are active. Each bar shows the workspaces of its own monitor.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `class_name` | string | `""` | Extra CSS class on the widget. |
| `monitor` | string | `""` | vertigo monitor id (`\\.\DISPLAY2`) to show. Empty: the bar's own monitor, found by screen name, then by geometry. |
| `persistent_workspaces` | integer | `5` | Workspaces always shown, 0-9. Higher ones show while occupied or active. |
| `label_active` | string | `"{index}"` | Label of the active workspace. `{index}` and `{windows}` are replaced; a glyph works too. |
| `label_occupied` | string | `"{index}"` | Label of a workspace with windows. |
| `label_empty` | string | `"{index}"` | Label of an empty workspace. |
| `tooltip` | boolean | `true` | Tooltip on each workspace. |
| `tooltip_label` | string | `"Workspace {index}: {windows} windows"` | Tooltip text; `{index}` and `{windows}` are replaced. |
| `scroll_to_switch` | boolean | `true` | Mouse wheel goes to the previous/next workspace of that monitor. |
| `reverse_scroll` | boolean | `false` | Swap the wheel directions. |
| `offline` | string | `"dim"` | While vertigo is not running: `dim` (persistent workspaces, dimmed, not clickable) or `hide`. The widget reconnects on its own. |
| `update_interval` | integer | `300` | How often vertigo is polled, in ms (100-5000). Shared by all bars; the first widget sets it. |

## Example Configuration

```yaml
workspaces:
  type: "yasb.vertigo.WorkspacesWidget"
  options:
    persistent_workspaces: 5
    label_active: "{index}"
    label_occupied: "{index}"
    label_empty: "{index}"
    tooltip_label: "Workspace {index}: {windows} windows"
    offline: "dim"
```

Put the same widget on every bar; each one follows its monitor.

## Interaction

| Action | Result |
| --- | --- |
| Click a workspace | Switch that monitor to it (vertigo first focuses the monitor if needed) |
| Mouse wheel | Previous / next workspace on that monitor |
| Hover | Number of windows in the workspace |

## How it works

The widget talks to vertigo's named pipe `\\.\pipe\vertigo` directly (one JSON line in, one JSON line out, the same protocol `vertigo.exe` uses). One background thread, shared by every bar, polls `{"cmd":"query","what":"state"}` and the bars redraw only when what they show changes. vertigo lists only the workspaces that hold windows, so the others are drawn as empty.

vertigo's workspace actions apply to the focused monitor, so a click on another monitor's bar sends `focus-monitor <direction>` first (found from the monitors' positions), then `focus-workspace N`.

## Style

```css
.vertigo-workspaces {} /* The widget */
.vertigo-workspaces .widget-container {} /* Also .widget-container.offline while vertigo is not running */
.vertigo-workspaces .ws-btn {} /* Every workspace (a QPushButton) */
.vertigo-workspaces .ws-btn.active {}
.vertigo-workspaces .ws-btn.occupied {}
.vertigo-workspaces .ws-btn.empty {}
.vertigo-workspaces .ws-btn.offline {} /* While vertigo is not running */
```

## Example CSS

Tokyo Night, like Omarchy's default theme:

```css
.vertigo-workspaces .ws-btn {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    min-width: 22px;
    padding: 0 4px;
    margin: 3px 1px;
    font-weight: 700;
}
.vertigo-workspaces .ws-btn.empty { color: #565f89; }
.vertigo-workspaces .ws-btn.occupied { color: #c0caf5; }
.vertigo-workspaces .ws-btn.active { color: #1a1b26; background-color: #7aa2f7; }
.vertigo-workspaces .ws-btn:hover { background-color: rgba(36, 40, 59, 0.92); color: #7aa2f7; }
.vertigo-workspaces .ws-btn.offline { color: rgba(86, 95, 137, 0.45); }
```
