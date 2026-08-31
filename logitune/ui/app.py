# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicação GTK do logi-tune-linux."""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from logitune.ui.window import LogituneWindow  # noqa: E402

APP_ID = "io.github.renangraciano.LogiTuneLinux"


class LogituneApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.create_action("quit", lambda *_: self.quit(), ["<primary>q"])

    def do_activate(self) -> None:
        window = self.props.active_window or LogituneWindow(application=self)
        window.present()

    def create_action(self, name: str, callback, shortcuts: list[str] | None = None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return LogituneApplication().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
