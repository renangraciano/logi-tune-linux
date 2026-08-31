# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

While the version is below `1.0.0`, the minor number may carry breaking
changes; they are always called out under **Changed** with a migration note.

## [Unreleased]

### Added

- `logitune doctor`, reporting udev rule, device access, `/dev/uinput`, evdev,
  session type and daemon state in one place.
- The udev rule now also grants `/dev/uinput`, which key synthesis will need,
  and `scripts/install-udev.sh` installs it.

- Desktop entry and icon, so the graphical interface appears in the
  application menu. Install with `scripts/install-desktop.sh`.

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
- The daemon now drains every queued report per wakeup instead of one. A burst
  of events could overflow the bounded hidraw queue, and the kernel drops the
  *oldest* report — which may be the one saying the button was released.
- The window no longer gets stuck on "searching for the mouse". Building the
  page could raise while another process was talking to the device, and GLib
  swallowed the exception, leaving the placeholder on screen forever. Sections
  are now built independently and a failure is reported instead of hiding.
- Transient HID++ errors (`BUSY`, `HARDWARE_ERROR`) are retried. They mean the
  device could not answer right now, which happens whenever the daemon or
  Solaar talks to it at the same moment, and are not a reason to give up.
- `StartupWMClass` now matches the actual window class, so the dock shows the
  application icon rather than a generic one.
- The configuration file is written as `0600` inside a `0700` directory, and
  a warning is issued when weaker permissions are found. It maps buttons to
  commands the daemon runs, so write access to it is code execution.
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

[Unreleased]: https://github.com/renangraciano/logi-tune-linux/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/renangraciano/logi-tune-linux/releases/tag/v0.1.0
