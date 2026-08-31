#!/usr/bin/env bash
# Cuts a release: bumps the version, updates the changelog heading and tags.
#
#   scripts/release.sh 0.2.0
#
# Pushing the tag is left to you, and is what triggers the release workflow.
set -euo pipefail

version="${1:-}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.]+)?$ ]]; then
  echo "usage: $0 <version>   e.g. $0 0.2.0" >&2
  exit 1
fi

root=$(git rev-parse --show-toplevel)
cd "$root"

if [ -n "$(git status --porcelain)" ]; then
  echo "working tree is not clean; commit or stash first" >&2
  exit 1
fi

today=$(date +%Y-%m-%d)

sed -i "s/^__version__ = \".*\"/__version__ = \"$version\"/" logitune/__init__.py
sed -i "s|^## \[Unreleased\]|## [Unreleased]\n\n## [$version] - $today|" CHANGELOG.md

git add logitune/__init__.py CHANGELOG.md
git commit -m "chore(release): v$version"
git tag -a "v$version" -m "v$version"

echo
echo "Tagged v$version. Review it, then:"
echo "  git push && git push origin v$version"
