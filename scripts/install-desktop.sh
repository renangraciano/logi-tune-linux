#!/usr/bin/env bash
# Adds Logi Tune Linux to the desktop: application menu entry and icon.
#
# pipx and pip install the commands, but neither installs a .desktop file or
# an icon, so the graphical interface would not show up in the app menu.
#
#   scripts/install-desktop.sh            install for the current user
#   scripts/install-desktop.sh --uninstall  remove it
set -euo pipefail

APP_ID="io.github.renangraciano.LogiTuneLinux"
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$apps_dir/$APP_ID.desktop" "$icon_dir/$APP_ID.svg"
  echo "Removed the menu entry and icon."
else
  if ! command -v logitune-gui >/dev/null; then
    echo "warning: logitune-gui is not on PATH; install the package first" >&2
    echo "         (pipx install --system-site-packages .)" >&2
  fi

  mkdir -p "$apps_dir" "$icon_dir"
  install -m 644 "$root/packaging/desktop/$APP_ID.desktop" "$apps_dir/"
  install -m 644 "$root/packaging/icons/$APP_ID.svg" "$icon_dir/"
  echo "Installed:"
  echo "  $apps_dir/$APP_ID.desktop"
  echo "  $icon_dir/$APP_ID.svg"
fi

# Refresh the caches so the entry shows up without logging out.
command -v update-desktop-database >/dev/null && \
  update-desktop-database -q "$apps_dir" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -qtf "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true

echo "Done. Look for \"Logi Tune Linux\" in your application menu."
