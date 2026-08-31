# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/renangraciano/logi-tune-linux/security/advisories/new)
rather than opening a public issue.

Expect an initial response within a week.

## What this software can do

Being clear about the capabilities matters more than a threat model in the
abstract, because this project writes to hardware and can run commands.

**It talks to your mouse over HID++.** The udev rule grants access to
Logitech devices through `uaccess`, which means the user of the local
graphical session — and only that user — can reach `/dev/hidraw*` for those
devices. The rule deliberately does not use `MODE="0666"`, which would expose
the device to every account on the machine.

**It can run commands you configure.** In `~/.config/logitune/config.json`,
the `actions` map binds a mouse button to a command line. The daemon runs
those commands as your user, without a shell, splitting arguments with
`shlex.split`.

Because of this, the configuration file is **the security boundary**: anyone
who can write it can run code as you. `logitune` creates it as `0600` inside a
`0700` directory, and the daemon warns on startup if it finds weaker
permissions. If you sync your dotfiles, keep this file out of any
world-readable location.

**It does not** talk to the network, collect telemetry, or require root.

## Firmware

Writing to undocumented HID++ features carries an inherent risk to the device.
This project only calls functions confirmed by probing, and never touches the
firmware-update features (`0x00C2` and related), which are the ones that could
brick a device. Findings are recorded with the firmware version they were seen
on, since behaviour can change between revisions.

## Supported versions

Only the latest release receives fixes while the project is pre-1.0.
