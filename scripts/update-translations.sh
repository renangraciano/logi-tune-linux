#!/usr/bin/env bash
# Re-extracts translatable strings and merges them into every catalogue.
#
# Run this after adding or changing any _("...") string. The test suite fails
# when the .pot falls behind the code, which is what stops a message from
# quietly appearing untranslated in an otherwise translated window.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"

for tool in xgettext msgmerge msgfmt; do
  command -v "$tool" >/dev/null || {
    echo "$tool not found. Install it with: sudo apt install gettext" >&2
    exit 1
  }
done

xgettext --language=Python --keyword=_ --from-code=UTF-8 \
  --package-name=logi-tune-linux --package-version=0.1.0 \
  --msgid-bugs-address=https://github.com/renangraciano/logi-tune-linux/issues \
  --copyright-holder="logi-tune-linux contributors" \
  -o po/logi-tune-linux.pot $(find logitune -name '*.py' | sort)

for po in po/*.po; do
  msgmerge --update --backup=none --quiet "$po" po/logi-tune-linux.pot
  echo "merged $po"
done

echo
echo "Now fill in any empty msgstr, then run scripts/build-translations.sh"
