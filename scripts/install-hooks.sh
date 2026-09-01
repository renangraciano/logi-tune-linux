#!/usr/bin/env bash
# Installs a commit-msg hook that checks the Conventional Commits format.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
hook="$root/.git/hooks/commit-msg"

cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
# Rejects commit messages that do not follow Conventional Commits.
set -euo pipefail

subject=$(head -1 "$1")

# Comments and merge commits are not ours to validate.
case "$subject" in
  \#*|Merge*|Revert*) exit 0 ;;
esac

pattern='^(feat|fix|docs|refactor|perf|test|build|ci|chore|revert)(\([a-z0-9-]+\))?!?: .{1,72}$'

if ! printf '%s' "$subject" | grep -qE "$pattern"; then
  cat >&2 <<'MSG'
Commit message does not follow Conventional Commits.

  <type>(<scope>): <subject>

Types:  feat fix docs refactor perf test build ci chore revert
Scopes: hidpp actions cli ui daemon config i18n packaging docs ci
Subject: imperative, lowercase, no trailing period, under 72 characters.

Example:
  feat(hidpp): decode the 0x19B0 haptic feature

See CONTRIBUTING.md.
MSG
  exit 1
fi
HOOK

chmod +x "$hook"
echo "commit-msg hook installed at $hook"
