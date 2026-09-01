# Contributing

Thanks for wanting to help. This project exists because the MX Master 4 has no
first-party software on Linux, and every device someone tests it against makes
it better.

## Getting set up

```bash
git clone https://github.com/renangraciano/logi-tune-linux
cd logi-tune-linux
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

The test suite uses a fake HID++ transport, so it runs without a mouse and
without access to `/dev/hidraw`. Anything that needs real hardware belongs in a
manual check, not in the suite.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/), in
English, so that changelogs and version bumps can be derived automatically.

```
<type>(<scope>): <subject>

<body: what changed and, more importantly, why>

<footer: Closes #123, BREAKING CHANGE: ...>
```

**Types**

| Type | Use for | Version effect |
| --- | --- | --- |
| `feat` | a new capability | minor |
| `fix` | a bug fix | patch |
| `docs` | documentation only | none |
| `refactor` | restructuring with no behaviour change | none |
| `perf` | performance work | patch |
| `test` | tests only | none |
| `build` | packaging, dependencies | none |
| `ci` | workflows | none |
| `chore` | anything else | none |

**Scopes**: `hidpp`, `actions`, `cli`, `ui`, `daemon`, `config`, `i18n`, `packaging`, `docs`, `ci`.

A commit that breaks compatibility carries `!` after the type/scope **and** a
`BREAKING CHANGE:` footer explaining the migration.

```
feat(hidpp): decode the 0x19B0 haptic feature

playWaveform accepts indices 0-14 and echoes the index back; 15 and above are
rejected with INVALID_ARGUMENT. The limit was established by probing each
index on firmware RBM 27.03.B0019.

Closes #12
```

Subject line: imperative mood, lowercase, no trailing period, under 72
characters. Explain *why* in the body — the diff already shows *what*.

To have the format checked locally before each commit:

```bash
scripts/install-hooks.sh
```

## Pull requests

- Branch from `main`, named `<type>/<short-description>` (`feat/actions-ring`).
- The PR title follows the same Conventional Commits format — it becomes the
  squashed commit message.
- Fill in the template: it asks how you tested, which matters a lot here
  because most of this code talks to physical hardware.
- Keep one concern per PR.
- `pytest` must pass. CI runs it on Python 3.10, 3.11 and 3.12.

## Reporting device support

The most valuable contribution is a report from a device we have not seen.
Open a *Device support* issue and attach:

```bash
logitune features
logitune buttons
```

Those two outputs describe the whole HID++ surface of a device, which is what
we need to add support for it.

## Reverse engineering notes

Several features on the MX Master 4 are undocumented. When you work one out:

- Record the raw bytes you observed, not just your interpretation.
- Say which firmware version you saw it on (`logitune status` shows it).
- If a field's meaning is not established, keep the raw bytes in the code
  instead of inventing a layout. `logitune/hidpp/features/haptic.py` is the
  reference for this style.

## Code style

Match the surrounding code. Comments explain *why* something is done, never
what the line already says. Public functions carry a docstring; obvious private
helpers do not need one.
