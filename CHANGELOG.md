# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

While the version is below `1.0.0`, the minor number may carry breaking
changes; they are always called out under **Changed** with a migration note.

## [Unreleased]

## [0.2.0] - 2026-09-01

The release where the mouse becomes configurable without a text editor. 0.1.0
could read and write the device; this one gives buttons something to do, and
gives you a window to say what.

### Added

- **A catalogue of 53 actions** a button can be bound to, grouped the way Logi
  Options+ groups them. Each one reports whether it can run in your session and
  why not, so a missing dependency reads as a missing dependency rather than an
  option that silently vanished.

  The backends are chosen per action rather than synthesised across the board:
  media over MPRIS reaches a minimised player, volume over PipeWire needs no
  compositor, applications open through `Gio.AppInfo`. Only keyboard shortcuts
  need `/dev/uinput`, because reaching the focused application is the one thing
  no session API does.

- **Gestures**, opt-in: tap, double tap, hold and drag in four directions on a
  single button — seven functions where the official application allows one,
  which was a limit of their software and not of the hardware. The mouse buzzes
  when a direction is recognised and again when the action fires.

  The thresholds were measured across 25 presses on real hardware, not guessed,
  and the measurement contradicted the plan twice. An ordinary click can shove
  the mouse 98 units, so distance alone fires drags nobody asked for; what
  separates them is continuity, since accidental movement arrives in one sample
  and a real drag in dozens.

- **A window that can do the work**: a drawing of the mouse with markers over
  each button, profile tabs per application, an action picker, and the gesture
  editor. Editing `config.json` by hand is now optional.

- **The thumb wheel as an application switcher**, the feature Logi Options+
  calls App Switcher. Alt is held while the wheel turns and released when it
  stops, since letting go between notches would close the switcher and restart
  the list every time.

- **Power saving**: silence the haptic motor below a chosen battery level.
  Charging always allows it, and so does a battery reading that fails.

- **System settings** — left-handed buttons, pointer speed, acceleration —
  edited through GNOME's own keys, and labelled as the session's rather than
  the mouse's.

- **English as the source language**, with Portuguese as a `gettext` catalogue.
  Two tests keep the catalogue from rotting: one fails when it falls behind the
  code, one when a message is untranslated or fuzzy.

- The daemon reloads on `SIGHUP`, so a change applies without dropping the
  service and losing the state of the diverted buttons.

- `logitune actions`, `logitune doctor`, `watch --raw-xy`, `watch --thumb`,
  `watch --passive` and `scroll --thumb-divert`.

- A desktop entry and icon, so the application appears in the menu.

### Changed

- **The interface speaks English by default.** Portuguese is still there, as a
  translation; set `LOGITUNE_LANG=pt_BR` or use a Portuguese session.

- **One action per button is the documented default.** Gestures are invisible —
  nothing on screen says which direction does what — so they are opt-in, and
  the proper answer for many actions on one button remains the radial menu.

- Third-party brand material was removed from the repository and from its
  history. A GPL-3 project has to be able to redistribute everything it ships.

- The configuration gained `bindings`, `gestures`, `wheel` and `power`. The old
  `actions` key still works: each entry becomes the `shell.run` action, so
  existing configurations run untouched.

### Fixed

- **Diverted button actions never fired.** `HidrawTransport.read(0)` computed
  its deadline and then compared it against a later clock reading, so the
  remaining time was always negative and it returned `None` even with a report
  waiting in the queue. The daemon polls with exactly `timeout=0`, so every
  button action configured since 0.1.0 was silently dead.

  The same defect also spun the daemon: `select` kept reporting the descriptor
  readable, the read never consumed anything, and the loop turned over without
  pause. Measured on an idle desktop, CPU use at rest went from roughly 30% of
  a core to 0.01%.

- **A request could swallow the notifications that arrived during it.** Reports
  that were not the reply being waited for were discarded, which is exactly
  what happens while the mouse is asked to buzz mid-gesture — including the
  notification saying the button was released, leaving a gesture that never
  completed.

- **Window titles no longer reach the log.** The daemon records the focused
  window on every switch, so the journal accumulated a browsing history — the
  same journal this project asks people to attach to bug reports.

- **A diverted thumb wheel is now told apart from an orphaned one.** Solaar
  diverts it and does not restore it on uninstall; the flag lives in the mouse's
  firmware, so the wheel keeps reporting to software that is gone and simply
  stops scrolling. `logitune doctor` detects it and `logitune scroll
  --no-thumb-divert` fixes it.

- The daemon drains every queued report per wakeup instead of one. A burst of
  events could overflow the bounded hidraw queue, and the kernel drops the
  *oldest* report — which may be the one saying the button was released.
- The window no longer gets stuck on "searching for the mouse". Building the
  page could raise while another process was talking to the device, and GLib
  swallowed the exception, leaving the placeholder on screen forever. Sections
  are now built independently and a failure is reported instead of hiding.
- Transient HID++ errors (`BUSY`, `HARDWARE_ERROR`) are retried. They mean the
  device could not answer right now, which happens whenever the daemon or
  Solaar talks to it at the same moment, and are not a reason to give up.
- Processes launched by button actions are reaped, instead of the most recent
  one lingering as a zombie until the next launch.
- Application names are escaped before going into row titles. They are parsed
  as Pango markup, and Ubuntu ships "Software & Updates", whose ampersand
  silently dropped the whole row.
- `StartupWMClass` now matches the actual window class, so the dock shows the
  application icon rather than a generic one.
- The configuration file is written as `0600` inside a `0700` directory, and
  a warning is issued when weaker permissions are found. It maps buttons to
  commands the daemon runs, so write access to it is code execution.
- A malformed `config.json` is reported by `logitune doctor` instead of only
  making the daemon fall back to defaults with a line in the journal.
- The application ID and the documentation URLs pointed at the wrong GitHub
  account, which broke the association between the window and its icon.

## [0.1.0] - 2026-08-31

First release. Everything below was verified against real hardware: an
MX Master 4 (WPID `B042`, firmware `RBM 27.03.B0019`) on a Bolt receiver,
running Ubuntu 24.04.4 with GNOME 46 on X11.

### Added

- HID++ 2.0 stack written from scratch on top of `/dev/hidraw`, with no
  dependency on Solaar or logiops and no need for root.
- Battery level and charging state (feature `0x1004`).
- Pointer sensitivity, including continuous and discrete DPI ranges (`0x2201`).
- SmartShift threshold and wheel mode (`0x2111`).
- High-resolution scrolling and wheel inversion (`0x2121`).
- Thumb wheel direction and diversion (`0x2150`).
- Button remapping and diversion for all nine controls (`0x1B04`).
- Easy-Switch between paired hosts (`0x1814`, `0x1815`).
- Haptic feedback (`0x19B0`) — 15 waveforms, previously undocumented.
- GTK4 and libadwaita interface.
- Daemon applying per-application profiles from the focused window on X11.
- Command line covering every capability, plus `logitune features` and
  `logitune watch` for reverse engineering.

### Discovered

- Feature `0x19B0` is the haptic motor: function `0x00` reports capabilities
  and `0x04` plays a waveform. Indices 0-14 are accepted; 15 and above are
  rejected with `INVALID_ARGUMENT`. The feature has exactly five functions —
  `0x05` and above return `INVALID_FUNCTION_ID` — and `playWaveform` takes only
  the pattern index, ignoring any further bytes. The fifteen patterns are
  catalogued in `docs/haptic-waveforms.md`.
- Control `0x01A0` (task `0x0109`) is the Actions Ring button, which exists on
  no earlier MX model. It is both remappable and divertable.
- Features `0x19C0`, `0x1701` and `0x00D1` are present on the MX Master 4 and
  remain undecoded.
- On feature `0x1815`, `getHostFriendlyName` is function `0x03`, not `0x02`;
  `0x02` returns a host identifier.

[Unreleased]: https://github.com/renangraciano/logi-tune-linux/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/renangraciano/logi-tune-linux/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/renangraciano/logi-tune-linux/releases/tag/v0.1.0
