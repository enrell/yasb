# Systray Widget

Puts your system tray icons directly in the status bar. You can pin important icons to keep them visible, collapse unpinned icons into a clean popup grid, set custom icon sizes, and hide specific apps you don't need to see.

| Option                      | Type      | Default       | Description                                                                                                                   |
| --------------------------- | --------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `class_name`                | string    | `'systray'`   | The class name for the base widget.                                                                                           |
| `label_collapsed`           | string    | `'▼'`         | Label used for the collapse button when unpinned container is hidden.                                                         |
| `label_expanded`            | string    | `'▶'`         | Label used for the collapse button when unpinned container is shown.                                                          |
| `label_position`            | string    | `'left'`      | The position of the button that collapses unpinned container. Can be "left" or "right".                                       |
| `icon_size`                 | integer   | `16`          | The size of the icons in the systray. Can be any integer between 8 and 64.                                                    |
| `pin_click_modifier`        | string    | `'alt'`       | The modifier key used to pin/unpin icons. Can be "ctrl", "alt" or "shift".                                                    |
| `show_unpinned`             | boolean   | `true`        | Whether to show unpinned container on startup.                                                                                |
| `show_unpinned_button`      | boolean   | `true`        | Whether to show the collapse unpinned icons button.                                                                           |
| `show_in_popup`             | boolean   | `false`       | Show unpinned icons in a popup grid instead of inline in the bar.                                                             |
| `icons_per_row`             | integer   | `5`           | Number of icon columns in the popup grid, 1-12 (only used when `show_in_popup` is true).                                      |
| `popup`                     | dict      | [See below](#popup-options) | Popup appearance settings (only used when `show_in_popup` is true).                                                           |
| `expand_on_hover`           | boolean   | `false`       | Open the unpinned icons while the mouse is over the tray, inline or in the popup. See [Expand on hover](#expand-on-hover).    |
| `collapse_delay`            | integer   | `400`         | Milliseconds to wait after the mouse leaves before closing hover-opened icons, 0-10000 (only used with `expand_on_hover`).    |
| `show_battery`              | boolean   | `false`       | Whether to show battery icon (from the original systray).                                                                     |
| `show_volume`               | boolean   | `false`       | Whether to show volume icon (from the original systray).                                                                      |
| `show_network`              | boolean   | `false`       | Whether to show network icon (from the original systray).                                                                     |
| `hide_icons`                | list      | `[]`          | List of process names to hide from the systray (exact match, case-insensitive).                                               |
| `tooltip`                   | boolean   | `true`        | Whether to show tooltips when hovering over systray icons.                                                                    |
| `use_hook`                  | boolean   | `true`       | Whether to use the systray hook. Default is false. False will use legacy systray monitor, true will use the new systray hook. |


## Popup Options
| Option                 | Type      | Default      | Description                                                                  |
| ---------------------- | --------- | ------------ | ---------------------------------------------------------------------------- |
| `blur`                 | boolean   | `true`       | Apply blur/acrylic effect to the popup background.                           |
| `round_corners`        | boolean   | `true`       | Round the corners of the popup window.                                       |
| `round_corners_type`   | string    | `'normal'`   | Round corner type. Can be "normal" or "small".                               |
| `border_color`         | string    | `'System'`   | Border color for the popup window. Use "System" for the system color.        |
| `alignment`            | string    | `'right'`    | Popup alignment relative to the button. Can be "left", "right", or "center". |
| `direction`            | string    | `'down'`     | Popup direction. Can be "up" or "down".                                      |
| `offset_top`           | integer   | `6`          | Vertical offset in pixels.                                                   |
| `offset_left`          | integer   | `0`          | Horizontal offset in pixels.                                                 |


## Example Configuration
```yaml
systray:
  type: "yasb.systray.SystrayWidget"
  options:
    class_name: "systray"
    label_collapsed: "▼"
    label_expanded: "▶"
    label_position: "left" # Can be "left" or "right"
    icon_size: 16 # Can be any integer between 8 and 64
    pin_click_modifier: "alt" # Can be "ctrl", "alt" or "shift"
    show_unpinned: true
    show_unpinned_button: true
    show_battery: false
    show_volume: false
    show_network: false
    use_hook: true # Whether to use the new systray hook instead of the legacy systray monitor
    hide_icons: [] # Optional, list of process names to hide (e.g. ["discord"])
```

## Example Popup Mode Configuration
When `show_in_popup` is enabled, unpinned icons are shown in a popup grid (similar to Windows) instead of inline in the bar. Pinned icons remain in the bar.
```yaml
systray:
  type: "yasb.systray.SystrayWidget"
  options:
    class_name: "systray"
    label_collapsed: "▼"
    label_expanded: "▶"
    label_position: "right"
    icon_size: 16
    pin_click_modifier: "alt"
    show_in_popup: true
    icons_per_row: 4
    popup:
      blur: true
      round_corners: true
      round_corners_type: "normal"
      border_color: None
      alignment: "center"
      direction: "down"
      offset_top: 6
      offset_left: 0
```

## Expand on hover
With `expand_on_hover: true` the unpinned icons open when the mouse reaches the tray, so you don't need to click the collapse button. It works in both modes:

- **Inline:** hovering anywhere on the tray shows the unpinned icons next to the pinned ones. This needs `show_unpinned_button: true`; without the button the unpinned icons are always shown anyway.
- **Popup** (`show_in_popup: true`): hovering the collapse button opens the popup grid. Pinned icons don't open it, so you can still reach them. A popup opened by hover doesn't take focus from the window you're working in.

When the mouse leaves, the icons close after `collapse_delay` milliseconds. Moving onto the expanded icons, or onto the popup across the gap below the bar, within that time keeps them open. The tray also stays open while you drag an icon, or while the cursor is still over it.

Clicking the collapse button while the icons are open from a hover keeps them open until the next click, like before. Icons you open with a click are never closed by the hover logic.

```yaml
systray:
  type: "yasb.systray.SystrayWidget"
  options:
    label_collapsed: "▼"
    label_expanded: "▶"
    show_unpinned: false
    expand_on_hover: true
    collapse_delay: 400 # ms after the mouse leaves the tray
```

## Systray Widget Limitations:
There are some limitations with the systray widget:
- Systray widget will not show icons for apps if they ignore "TaskbarCreated" message. Meaning that if the original developers decided to ignore this message - their systray icons will not be shown. It's rare, but there are such cases (NVIDIA App for example). This is NOT a YASB bug.
- In rare cases systray icon might ignore click events if the original application was already running before YASB was started. Example: Epic Games Launcher. No solution for this so far.

## Systray Hook vs Monitor
The systray hook is a more reliable and performant way to monitor systray icons. However, since it's an `explorer.exe` process hook (dll injection) it can potentially have some issues with Defender or other AV programs. Setting `use_hook: false` will completely bypass this method and revert back to the original systray monitor window method that is much less intrusive, but has plenty of compatibility issues with other apps. If your AV blocks the dll (or deletes it) systray widget will automatically use legacy mode.

## Description of Options
- **class_name:** The class name for the base widget. Can be changed if multiple systray widgets need to have different styling.
- **label_collapsed:** Label used for the collapse button when unpinned container is hidden.
- **label_expanded:** Label used for the collapse button when unpinned container is shown.
- **label_position:** The position of the button that collapses unpinned container.
- **icon_size:** The size of the icons in the systray. Can be any integer between 8 and 64.
- **pin_click_modifier:** The modifier key used to pin/unpin icons. Can be "ctrl", "alt" or "shift".
- **show_unpinned:** Whether to show unpinned container on startup.
- **show_unpinned_button:** Whether to show the 'collapse unpinned icons' button.
- **show_in_popup:** When enabled, unpinned icons are shown in a popup grid (like Windows system tray overflow) instead of inline. Clicking the expand/collapse button opens the popup. Pinned icons remain in the bar.
- **icons_per_row:** Number of columns in the popup icon grid. Only used when `show_in_popup` is true. Can be 1-12.
- **popup:** Popup window appearance settings. Only used when `show_in_popup` is true. See Popup Options table above.
- **expand_on_hover:** Open the unpinned icons while the mouse is over the tray (inline) or over the collapse button (popup), and close them again after `collapse_delay`. See [Expand on hover](#expand-on-hover).
- **collapse_delay:** How long, in milliseconds, hover-opened icons stay open after the mouse leaves. Moving back onto the tray or the popup in that time cancels the collapse.
- **show_battery:** Whether to show battery icon (from the original systray).
- **show_volume:** Whether to show volume icon (from the original systray).
- **show_network:** Whether to show network icon (from the original systray).
- **hide_icons:** A list of process names to hide from the systray. Each entry is matched exactly (case-insensitive) against the executable name without extension. For example, to hide Discord set `hide_icons: ["discord"]` which matches `Discord.exe`.
- **tooltip:** Whether to show tooltips when hovering over systray icons.
- **use_hook:** Whether to use the systray hook. Default is true. False will use legacy systray monitor, true will use the new systray hook.

## Debug Options
Show unpinned button has a right click menu that allows you to refresh the systray icons.

## Style
```css
.systray {} /* The base widget style */
.systray .widget-container {} /* Style for the widget container */
.systray .unpinned-container {} /* Style for container with unpinned systray icons */
.systray .pinned-container {} /* Style for container with pinned systray icons */
.systray .pinned-container[forceshow=true] {} /* Style for pinned container when it is forced to show during dragging operation */
.systray .button {} /* Style for the individual systray buttons/icons */
.systray .button.dragging {} /* Style for the icon currently being dragged */
.systray .button.drag-over {} /* Style for the icon being hovered over during a drag */
.systray .pinned-container.drop-target {} /* Style for the pinned container when it is an empty drop target */
.systray .unpinned-visibility-btn {} /* Style for the 'collapse unpinned icons' button */
.systray-popup {} /* Style for the popup window (when show_in_popup is true) */
.systray-popup-container {} /* Style for the popup grid container (when show_in_popup is true) */
```

## Example CSS
```css
.systray {
    background: transparent;
    border: none;
    margin: 0;
}
.systray .unpinned-container {
    background: transparent;
}
.systray .pinned-container {
    background: transparent;
}
.systray .button {
    border-radius: 4px;
    padding: 2px;
}

.systray .button:hover {
    background: rgba(255, 255, 255, 0.2);
}
/* Icon being dragged, we already apply some transparency to it so you don't need to use it */
.systray .button.dragging {}

.systray .button.drag-over {
     background: rgba(255, 255, 255, 0.4);
}

.systray .pinned-container.drop-target {
    background: rgba(255, 255, 255, 0.1);
}
.systray .unpinned-visibility-btn {
    border-radius: 4px;
    height: 20px;
    width: 16px;
    border: none;
    outline: none;
}

.systray .unpinned-visibility-btn:checked {
    background: transparent;
}

.systray .unpinned-visibility-btn:hover {
    background: rgba(255, 255, 255, 0.1);
}

/* Popup styles (when show_in_popup is true) */
 
/* The icon the drag is hovering over (drop target icon) */
.systray-popup .button.drag-over {
    background-color: rgba(255, 255, 255, 0.2);
}
/* Icon being dragged, we already apply some transparency to it so you don't need to use it */
.systray-popup .button.dragging {}

.systray .pinned-container.pinned-container.drop-target {
    background-color: rgba(255, 255, 255, 0.1);
}
.systray-popup {
    background-color: rgba(48, 48, 48, 0.6);
    padding: 4px;
}
.systray-popup .button {
    padding: 10px;
    margin: 0;
    border: 0;
    border-radius: 6px;
}
.systray-popup .button:hover {
    background-color: rgba(255, 255, 255, 0.05);
}
```
