<h1 align="center">logi-tune-linux</h1>

<p align="center">
  <strong>Your MX Master 4, fully configurable on Linux.</strong><br>
  An open alternative to Logi Options+ — including the haptic motor and the
  Actions Ring button that no other Linux tool reaches.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: GPL v3" src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
  <a href="https://github.com/renangraciano/logi-tune-linux/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/renangraciano/logi-tune-linux/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Linux-lightgrey">
  <a href="CONTRIBUTING.md"><img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg"></a>
</p>

<p align="center">
  <a href="README.pt-BR.md">🇧🇷 Leia em português</a>
</p>

<p align="center">
  <img src="docs/screenshot.png" alt="logi-tune-linux configuring an MX Master 4" width="420">
</p>

---

Logitech ships Options+ for Windows and macOS. On Linux you get nothing — no
DPI control, no SmartShift, no button remapping, and none of the MX Master 4's
new hardware.

This project talks **HID++ 2.0 straight to `/dev/hidraw`**. No Solaar, no
logiops, no root.

## What works

Every item below was verified against real hardware: an MX Master 4
(WPID `B042`, firmware `RBM 27.03.B0019`) on a Bolt receiver, Ubuntu 24.04.4,
GNOME 46, X11.

| | Capability | HID++ |
| --- | --- | --- |
| ✅ | Battery level and charging state | `0x1004` |
| ✅ | Pointer sensitivity (200–8000 DPI) | `0x2201` |
| ✅ | SmartShift threshold and wheel mode | `0x2111` |
| ✅ | High-resolution scrolling, wheel inversion | `0x2121` |
| ✅ | Thumb wheel direction | `0x2150` |
| ✅ | Button remapping and diversion | `0x1B04` |
| ✅ | Easy-Switch between three hosts | `0x1814` `0x1815` |
| ✅ | **Haptic feedback — 15 waveforms** | `0x19B0` |
| ✅ | Per-application profiles (X11) | — |
| 🚧 | Actions Ring radial menu | `0x01A0` |

## Two things you will not find elsewhere

**The haptic motor works.** Feature `0x19B0` was undocumented. Probing the
hardware established that function `0x04` plays a waveform, that indices 0–14
are accepted, and that 15 and above are rejected with `INVALID_ARGUMENT`. Your
mouse can now buzz on command:

```bash
logitune haptic --all
```

**The Actions Ring button is reachable.** The MX Master 4 added a button that
exists on no earlier model — control `0x01A0`, task `0x0109`. It is both
remappable and divertable, so you can bind it to anything today:

```bash
logitune watch 0x01A0     # see the event arrive as you press it
```

Between the button and the motor, both hardware halves of the Actions Ring are
solved. What is left is drawing the radial menu — see the [roadmap](#roadmap).

## Install

```bash
# Dependencies (the last one is only for per-application profiles)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-xlib

# Device access without root
sudo cp packaging/udev/70-logitune.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

pip install --user .
```

Unplug and replug the receiver after installing the udev rule.

## Use

```bash
logitune                      # summary
logitune dpi 1600             # pointer sensitivity
logitune smartshift 40        # ratchet threshold
logitune scroll --invert
logitune buttons              # list controls and their mappings
logitune button back --remap 0x0052
logitune hosts                # paired computers
logitune host 2               # move the mouse to channel 2
logitune haptic 3             # play one vibration pattern
logitune-gui                  # graphical interface
```

```
MX Master 4 (receptor)
  Bateria      ██████████░░░░░░░░░░ 50% (descarregando)
  Sensibilidade 2800 DPI (padrão 1000, faixa 200–8000)
  SmartShift   modo roda livre, ponto de virada 32 (padrão 70)
  Roda         resolução normal
  Roda polegar invertida, desviada
  Host ativo   canal 1 (receptor Bolt)
```

### Per-application profiles

The daemon watches the focused window and reconfigures the mouse as you switch
apps — a lower DPI in the browser, a locked ratchet in your editor.

```bash
logitune-daemon --write-example   # creates ~/.config/logitune/config.json
cp packaging/systemd/logitune-daemon.service ~/.config/systemd/user/
systemctl --user enable --now logitune-daemon
```

```json
{
  "default": { "dpi": 2800, "smartshift": 32 },
  "profiles": [
    {
      "name": "Browser",
      "match": { "wm_class": ["firefox", "brave", "chrome"] },
      "settings": { "dpi": 2000 }
    },
    {
      "name": "Editor",
      "match": { "wm_class": ["code"] },
      "settings": {
        "dpi": 3200,
        "ratchet": true,
        "actions": { "0x01A0": "xdotool key super" }
      }
    }
  ]
}
```

`buttons` remaps a control in firmware; `actions` diverts a button so the daemon
runs a command instead. Diverted buttons are restored when the daemon exits.

The daemon blocks in `select` on the X and hidraw descriptors — no polling, no
CPU at rest.

## How it compares

| | logi-tune-linux | Solaar | logiops |
| --- | --- | --- | --- |
| Knows the MX Master 4 | ✅ | partly | ❌ (`B042` unsupported in 0.3.3) |
| Haptic feedback | ✅ | ❌ | ❌ |
| Actions Ring button | ✅ | shows as unknown | ❌ |
| Runs without root | ✅ | ✅ | ❌ |
| Per-application profiles | ✅ | ❌ | ✅ |
| Reads state back (battery, DPI) | ✅ | ✅ | ❌ |
| Scope | one device, done well | the whole Logitech line | button remapping |

Solaar is an excellent project and its reverse engineering informed parts of
this protocol work. The goal here is different: match the Options+ experience
for a specific mouse, including hardware nothing on Linux supports yet.

## Reverse engineering

The MX Master 4 advertises 46 HID++ features. These are absent from public
documentation:

| Feature | Status |
| --- | --- |
| `0x19B0` | **haptic motor** — decoded, see [docs/haptic-waveforms.md](docs/haptic-waveforms.md) |
| `0x19C0` | responds to functions `0x00`–`0x02`; values vary between reads, suggesting a sensor |
| `0x1701` | undecoded |
| `0x00D1` | undecoded |

Also corrected along the way: on feature `0x1815`, `getHostFriendlyName` is
function `0x03`, not `0x02` — `0x02` returns a host identifier.

Two commands exist for this work:

```bash
logitune features    # full HID++ feature table
logitune watch       # divert buttons and print the events they emit
```

If you decode something, please [open an issue](https://github.com/renangraciano/logi-tune-linux/issues/new/choose)
— record the raw bytes and your firmware version, not only your interpretation.

## Roadmap

- [ ] Actions Ring radial menu via a GNOME Shell extension
- [ ] Per-application profiles on Wayland (same extension solves both)
- [ ] Decode `0x19C0`
- [ ] English interface (the GUI is currently Portuguese only)
- [ ] Flatpak and `.deb` packages
- [ ] Support beyond the MX Master 4 — the stack is generic HID++ 2.0, it just
      needs testing

## Known limitations

- **Wayland**: the protocol does not let an ordinary application know which
  window has focus, so per-application profiles are disabled there. Everything
  else works. The daemon says so on startup.
- **Running alongside Solaar** works, but both write to the same device and can
  undo each other. Use one at a time.
- **Wheel mode is volatile**: with SmartShift active the firmware switches
  between ratchet and freewheel on its own. Forcing a mode lasts until the next
  fast scroll.
- Tested only with the MX Master 4 over a Bolt receiver.

## Contributing

Device reports are the most valuable contribution — `logitune features` and
`logitune buttons` from a mouse we have not seen describe its entire HID++
surface. See [CONTRIBUTING.md](CONTRIBUTING.md) for commit conventions and the
development setup.

## Credits

The reverse engineering behind [Solaar](https://github.com/pwr-Solaar/Solaar)
and Logitech's public HID++ 2.0 specification were the basis for understanding
the protocol. That feature `0x19B0` is the haptic motor was independently
identified by [ncr/mx-master-4-haptic](https://github.com/ncr/mx-master-4-haptic)
and [talamar49/orbit-mouse](https://github.com/talamar49/orbit-mouse), and the
probing here agrees with both.

## License

[GPL-3.0-or-later](LICENSE).
