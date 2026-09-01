#!/usr/bin/env bash
# Compiles the .po catalogues so a checkout runs translated.
#
# The build does this on its own when installing; this script is for running
# straight from the source tree, where nothing has been built.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"

if ! command -v msgfmt >/dev/null; then
  echo "msgfmt not found. Install it with: sudo apt install gettext" >&2
  exit 1
fi

for po in po/*.po; do
  lang=$(basename "$po" .po)
  dir="logitune/locale/$lang/LC_MESSAGES"
  mkdir -p "$dir"
  msgfmt --check --statistics -o "$dir/logi-tune-linux.mo" "$po"
  echo "  $lang -> $dir/logi-tune-linux.mo"
done
