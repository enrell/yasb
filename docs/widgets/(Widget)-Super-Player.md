# Super Player Widget

Media controls and synced lyrics for whatever is playing. The bar shows the lyric line being sung right now with a hairline progress bar under it. The popup has previous, play/pause and next, a volume slider and mute, and the full synced lyrics from [LRCLIB](https://lrclib.net). Click a line to jump there.

This widget is a YASB port of [omarchy-super-player](https://github.com/enrell/omarchy-super-player) by enrell, a Quickshell plugin for [Omarchy](https://omarchy.org). It follows the same behaviour: the same player choice, lookup order, sync clock, romanization and translation. Windows players come from the system media controls (GSMTC) through YASB's media service.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `class_name` | string | `""` | Extra CSS class on the widget. |
| `source` | string | `"auto"` | Which player to follow. `auto` follows the player that is playing (Windows' current session first), then Windows' current session, then the first one available. Any other value pins a player: its AUMID (`Spotify.exe`), the exe name without extension (`spotify`) or its display name (`Spotify`). A pinned player that isn't running falls back to `auto`. |
| `bar_label` | string | `"lyric"` | What the bar shows: `lyric` (the current line: its translation, else its romanization, else the original, falling back to the track title), `track` (the title) or `icon` (only the icon). |
| `max_label_width` | integer | `240` | Width in pixels before the bar label starts scrolling, 40-1200. |
| `scroll_label` | boolean | `true` | Scroll a label that is wider than `max_label_width`. When false the label is cut with an ellipsis. |
| `show_icon` | boolean | `true` | Show the music icon before the label. |
| `show_progress` | boolean | `true` | Show the hairline progress bar along the bottom of the widget. |
| `hide_when_no_lyrics` | boolean | `false` | Hide the widget while no synced line is being sung, instead of showing the track title. |
| `romanize` | string | `"off"` | `off`, `replace` (show only the romanized line) or `below` (romanized line under the original). See [Romanization](#romanization). |
| `translate` | string | `"off"` | `off` or a language code (`pt-BR`, `en`, `es`, `fr`, `de`, `it`, `ja`, `ko`, `zh-CN`, `ru`, ...). See [Translation](#translation). |
| `translate_to` | string | `"pt-BR"` | Language the translation switch in the settings view turns on. |
| `ui_language` | string | `"en"` | Language of the popup and settings text: `en` or `pt`. |
| `tooltip` | boolean | `true` | Tooltip with `title — artist` on hover, and the new level when you scroll the volume. |
| `volume_step` | integer | `5` | Volume change per mouse wheel step, in percent, 1-25. |
| `icons` | dict | [See below](#icons) | Icons used in the bar and the popup. |
| `popup` | dict | [See below](#popup-options) | Popup options. |
| `callbacks` | dict | [See below](#callbacks) | Mouse callbacks. |
| `keybindings` | list | `[]` | Optional hotkeys. See [Keybindings](./Keybindings). |

## Example Configuration

```yaml
super_player:
  type: "yasb.super_player.SuperPlayerWidget"
  options:
    source: "auto"
    bar_label: "lyric"
    max_label_width: 240
    hide_when_no_lyrics: false
    romanize: "off"
    translate: "off"
    popup:
      blur: true
      round_corners: true
      border_color: "System"
      alignment: "right"
      direction: "down"
      offset_top: 6
      width: 400
      lyrics_height: 300
    callbacks:
      on_left: "toggle_popup"
      on_middle: "toggle_play_pause"
      on_right: "open_settings"
```

## Usage

| Interaction | Action |
| --- | --- |
| Left click | Open or close the popup |
| Right click | Open the popup on its settings view |
| Middle click | Play/pause |
| Mouse wheel | Volume of the player, with a tooltip showing the new level |
| Hover | Tooltip with `title — artist` |

Inside the popup:

| Interaction | Action |
| --- | --- |
| Hover the cover art | Play/pause glyph; click to toggle |
| Previous / play / next | Transport controls of the followed player |
| Hover the volume icon | Reveals the volume bar next to it; click the icon to mute |
| Volume bar | Click or drag to set the level |
| Seek bar (bottom) | Click anywhere to jump there, press and drag to scrub |
| Click a lyric line | Seek to that line |
| Gear button (header) | Open or close the settings view |

The widget hides itself while no player is running.

## Settings view

The gear button in the popup header, or a right click on the widget, opens the settings view, like the original plugin's settings page:

- **Player:** `Automatic` or one of the players running now (pins `source`).
- **Romanization:** on/off switch, then *below the line* or *instead of the line*. The line under the switch says which romanizer is in use.
- **Translation:** on/off switch and, while it is on, the target language (`translate_to`). Turning it on is the only thing that sends lyrics to Google Translate; the line under the switch shows the status, including failures.
- **Bar:** lyric line / track / icon only, the progress line, and hiding the widget without lyrics.

Changes apply immediately: the lyrics re-render with the romanized and translated lines under each original line, and the current-line highlight keeps going. They are saved in `super-player.json` next to `config.yaml` (one section per widget name) and survive restarts. `config.yaml` is never rewritten: its values are the defaults, and the saved values override them. A value set back to what `config.yaml` says is removed from the file, and deleting the file resets everything to `config.yaml`.

## Popup Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `blur` | boolean | `true` | Blur the popup background. |
| `round_corners` | boolean | `true` | Round the popup corners. |
| `round_corners_type` | string | `"normal"` | `normal` or `small`. |
| `border_color` | string | `"System"` | Border color: `System`, `None` or a hex color. |
| `alignment` | string | `"right"` | `left`, `right` or `center`, relative to the widget. |
| `direction` | string | `"down"` | `down` or `up`. |
| `offset_top` | integer | `6` | Vertical offset in pixels. |
| `offset_left` | integer | `0` | Horizontal offset in pixels. |
| `width` | integer | `400` | Popup width in pixels, 240-1200. |
| `lyrics_height` | integer | `300` | Height of the lyrics list in pixels, 80-1600. |
| `show_cover` | boolean | `true` | Show the cover art in the header. |
| `cover_size` | integer | `64` | Cover art size in pixels, 24-256. |

## Icons

Defaults are Nerd Font Material Design icons, the same as the original plugin.

| Option | Default | Used for |
| --- | --- | --- |
| `music` | `\U000f075a` | Bar icon, and the cover when the player has no art |
| `prev_track` | `\U000f04ae` | Previous button |
| `next_track` | `\U000f04ad` | Next button |
| `play` | `\U000f040a` | Play button and cover overlay |
| `pause` | `\U000f03e4` | Pause button and cover overlay |
| `volume` | `\U000f057e` | Mute button while audible |
| `muted` | `\U000f0581` | Mute button while muted |
| `settings` | `\U000f0493` | Gear button in the popup header |
| `back` | `\U000f004d` | Back button in the settings view |

## Callbacks

| Callback | Action |
| --- | --- |
| `toggle_popup` | Open or close the popup. |
| `toggle_play_pause` | Play/pause the followed player. |
| `next_track` | Next track. |
| `prev_track` | Previous track. |
| `toggle_mute` | Mute or unmute the followed player. |
| `open_settings` | Open the popup on its settings view (closes it when already there). |
| `reload_lyrics` | Look the lyrics up again, ignoring the cache. |
| `do_nothing` | Nothing. |

## How it works

1. **Player.** The widget reads every GSMTC session from YASB's media service and picks one with `source`. Controls, seeking and volume always act on that player, even when another widget follows a different one.
2. **Lyrics.** A track change starts a lookup after 250 ms, so the player can finish publishing its metadata. The lookup runs on a background thread, in order: the exact `GET /api/get` (artist and title, plus album and duration when the player reports them), the filtered `GET /api/search`, then the free text `GET /api/search?q=`. Players that report no artist go straight to the free text search. Candidates prefer synced lyrics and a duration close to the track (within 25 s for synced, 10 s for unsynced) so live versions and remixes don't match. Network failures are retried twice. Results are cached in memory for the last 50 tracks.
3. **Clock.** With a timeline from the player, the highlighted line follows the player's position and re-anchors only on jumps over 1.5 s (seek, loop, restart), so it doesn't flicker at line boundaries. Some players, mostly browsers, publish no timeline: then a local clock starts when the track changes and runs while it plays. That clock is an estimate, right when the track starts from the beginning; the popup header says "estimated timing" and lines can't be clicked to seek. The progress bar then uses the duration LRCLIB reports.
4. **Volume.** GSMTC has no volume, so the widget changes the player's own audio sessions in the Windows mixer, found by AUMID and then by exe name. Mute is the mixer's real mute. When no audio session matches (the player hasn't played sound yet), the volume controls are disabled.

## Romanization

`romanize: below` or `replace` transliterates the lyrics to Latin script once per track, on a background thread:

- **Japanese** with readings for kanji needs [pykakasi](https://pypi.org/project/pykakasi/). It is not a YASB dependency; when running from source, install the pinned optional extra with `pip install -e .[lyrics]`. The widget uses it only when it can be imported, and the settings view says which romanizer is in use.
- **Kana, Hangul, Cyrillic and Greek** are romanized with built-in tables. Without pykakasi, kanji are left as they are.

## Translation

`translate: <code>` translates the whole lyrics once per track, on a background thread, with the same Google Translate endpoint the original plugin uses (`clients5.google.com`). Translations are cached per track and language. The endpoint is undocumented, so it can change or rate limit; when it fails the widget keeps the original lyrics and the popup says "translation failed". With both options on, each line shows the original, then the romanization, then the translation.

## Network and privacy

| Used for | What | Where it goes |
| --- | --- | --- |
| Lyrics | LRCLIB public API (no key) | `lrclib.net` |
| Translation (off by default) | Google Translate public endpoint | `clients5.google.com` |

Every request is abandoned after 8 s, and a reply larger than 512 KiB is refused before it is parsed or cached. Titles, artists and lyrics are always shown as plain text: a lyric that looks like HTML is never rendered as rich text, so it can't load remote images.

## Style

```css
.super-player-widget {} /* The widget */
.super-player-widget .widget-container {}
.super-player-widget .icon {} /* Music icon; also .icon.playing and .icon.paused */
.super-player-widget .label {} /* Current lyric line or title */
.super-player-widget .progress {} /* Hairline progress bar (a QProgressBar) */
.super-player-widget .progress::chunk {}

.super-player-popup {} /* The popup */
.super-player-popup .header {}
.super-player-popup .cover {} /* Cover art; the play/pause overlay is drawn on top */
.super-player-popup .title {}
.super-player-popup .artist {}
.super-player-popup .btn {} /* Also .btn.prev, .btn.play, .btn.next, .btn.mute */
.super-player-popup .btn.muted {}
.super-player-popup .btn.disabled {}
.super-player-popup .volume-slider {} /* A QSlider: style ::groove, ::sub-page, ::handle */
.super-player-popup .status {} /* "fetching lyrics…", "unsynced lyrics", ... */
.super-player-popup .lyrics {} /* Scroll area with the lines */
.super-player-popup .lyrics-body {}
.super-player-popup .line {} /* One line; also .current, .past, .future, .plain (unsynced) and .seekable */
.super-player-popup .line .text {}
.super-player-popup .line .romanized {}
.super-player-popup .line .translated {}
.super-player-popup .empty {} /* No player, loading, not found, network error */
.super-player-popup .empty .message {}
.super-player-popup .retry {} /* "Try again" button */
.super-player-popup .seek-slider {} /* A QSlider like .volume-slider */
.super-player-popup .btn.settings {} /* Gear button; .btn.settings.active while the settings view is open */
.super-player-popup .settings {} /* Settings view */
.super-player-popup .settings-title {}
.super-player-popup .back {} /* "Back" button (a QPushButton) */
.super-player-popup .section-title {} /* PLAYER, LYRICS, BAR */
.super-player-popup .section {} /* Card around each group of settings */
.super-player-popup .divider {} /* 1px line between rows of a card */
.super-player-popup .setting-label {}
.super-player-popup .setting-desc {} /* Line under a label: romanizer in use, translation status; .error when it failed */
.super-player-popup .switch {} /* Painted on/off switch: set qproperty-onColor, qproperty-offColor, qproperty-knobColor */
.super-player-popup .chip {} /* Language buttons; :checked is the selected one */
.super-player-popup .segment {} /* Joined option buttons (player, mode, bar label); .first/.last ends, :checked */
```

## Example CSS

A knobless look like the original, with colors from CSS variables so it follows your theme:

```css
:root {
    --sp-fg: #c0caf5;
    --sp-dim: #565f89;
    --sp-accent: #7aa2f7;
    --sp-track: rgba(192, 202, 245, 0.15);
}
.super-player-widget .icon {
    color: var(--sp-accent);
    padding-right: 6px;
}
.super-player-widget .icon.paused {
    color: var(--sp-dim);
}
.super-player-widget .progress {
    max-height: 1px;
    border: none;
    background-color: var(--sp-track);
}
.super-player-widget .progress::chunk {
    background-color: var(--sp-accent);
}
.super-player-popup {
    background-color: rgba(26, 27, 38, 0.92);
}
.super-player-popup .cover {
    border-radius: 6px;
    background-color: var(--sp-track);
    font-size: 28px;
}
.super-player-popup .title {
    font-size: 15px;
    font-weight: 700;
}
.super-player-popup .artist,
.super-player-popup .status {
    color: var(--sp-dim);
}
.super-player-popup .btn {
    font-size: 18px;
    padding: 2px 6px;
    border-radius: 4px;
}
.super-player-popup .btn:hover {
    background-color: var(--sp-track);
}
.super-player-popup .btn.disabled {
    color: var(--sp-dim);
}
.super-player-popup .lyrics,
.super-player-popup .lyrics-body {
    background: transparent;
    border: none;
    margin-top: 10px;
}
.super-player-popup .line .text {
    color: var(--sp-dim);
    font-size: 13px;
}
.super-player-popup .line.past .text {
    color: rgba(86, 95, 137, 0.6);
}
.super-player-popup .line.current .text {
    color: var(--sp-fg);
    font-size: 16px;
    font-weight: 700;
}
.super-player-popup .line.seekable:hover {
    background-color: var(--sp-track);
    border-radius: 4px;
}
.super-player-popup .line .romanized,
.super-player-popup .line .translated {
    color: var(--sp-dim);
    font-size: 11px;
}
.super-player-popup .line .translated {
    font-style: italic;
}
.super-player-popup .volume-slider::groove:horizontal,
.super-player-popup .seek-slider::groove:horizontal {
    height: 2px;
    background: var(--sp-track);
}
.super-player-popup .volume-slider::sub-page:horizontal,
.super-player-popup .seek-slider::sub-page:horizontal {
    background: var(--sp-accent);
}
.super-player-popup .volume-slider::handle:horizontal,
.super-player-popup .seek-slider::handle:horizontal {
    width: 0;
    margin: -4px 0;
}
.super-player-popup .seek-slider:hover::groove:horizontal {
    height: 4px;
}
/* Settings view */
.super-player-popup .section-title {
    color: var(--sp-accent);
    font-size: 10px;
    font-weight: 800;
}
.super-player-popup .section {
    background-color: rgba(36, 40, 59, 0.75);
    border: 1px solid rgba(86, 95, 137, 0.35);
    border-radius: 8px;
}
.super-player-popup .divider {
    background-color: rgba(86, 95, 137, 0.35);
}
.super-player-popup .setting-desc {
    color: var(--sp-dim);
    font-size: 10px;
}
.super-player-popup .setting-desc.error {
    color: #f7768e;
}
.super-player-popup .switch {
    qproperty-onColor: #7aa2f7;
    qproperty-offColor: #3b4261;
    qproperty-knobColor: #c0caf5;
}
.super-player-popup .chip {
    border: 1px solid rgba(86, 95, 137, 0.45);
    border-radius: 10px;
    padding: 3px 0;
    font-size: 11px;
}
.super-player-popup .chip:checked {
    background-color: var(--sp-accent);
    color: #1a1b26;
}
.super-player-popup .segment {
    border: 1px solid rgba(86, 95, 137, 0.45);
    border-left: none;
    padding: 4px 6px;
    font-size: 11px;
}
.super-player-popup .segment.first {
    border-left: 1px solid rgba(86, 95, 137, 0.45);
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
}
.super-player-popup .segment.last {
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}
.super-player-popup .segment:checked {
    background-color: rgba(122, 162, 247, 0.22);
}
```

## Limitations

- If LRCLIB only has a different version of the track, the popup says "No lyrics found on LRCLIB." rather than showing timings that don't match.
- Unsynced lyrics are listed without a highlight; the header says "unsynced lyrics".
- Browsers often report the channel as the artist and `Artist - Song` as the title, which can miss the exact lookup; the free text search usually still finds it.
- Players without a timeline only get an estimated position (see [How it works](#how-it-works)).
- The settings view covers the options that make sense on Windows; label width and the popup layout stay in `config.yaml`.

## Credits

Based on [omarchy-super-player](https://github.com/enrell/omarchy-super-player) by enrell (MIT). Lyrics come from [LRCLIB](https://lrclib.net) and belong to their respective authors and publishers.
