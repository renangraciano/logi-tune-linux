#!/usr/bin/env bash
# Installs the udev rule that grants this user access to the mouse and to
# /dev/uinput, so nothing here needs to run as root.
#
#   sudo scripts/install-udev.sh
#   sudo scripts/install-udev.sh --uninstall
set -euo pipefail

RULE="70-logitune.rules"
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
target="/etc/udev/rules.d/$RULE"

if [ "$(id -u)" -ne 0 ]; then
  echo "This needs root to write to /etc/udev/rules.d." >&2
  echo "Run: sudo $0 ${1:-}" >&2
  exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$target"
  echo "Removed $target"
else
  install -m 644 "$root/packaging/udev/$RULE" "$target"
  echo "Installed $target"
fi

udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=misc

cat <<'NOTE'

Done. Two things to be aware of:

  1. Unplug and replug the receiver so the mouse picks up the new rule.
  2. The uinput ACL usually applies immediately. If `logitune doctor` still
     reports no uinput access, log out and back in — uaccess grants the ACL
     to the active local seat at login.

Check with: logitune doctor
NOTE
