# SPDX-License-Identifier: GPL-3.0-or-later
"""Escolha do aplicativo ao qual um perfil se aplica.

Lê a mesma lista que o menu de aplicativos usa, então a pessoa reconhece nome
e ícone. O que o perfil guarda, porém, não é o aplicativo: é a *classe da
janela*, que é o que o daemon consegue ler da janela em foco.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gio, Gtk  # noqa: E402

from logitune.actions.backends.launch import AppEntry, list_apps  # noqa: E402

logger = logging.getLogger(__name__)


class AppPicker(Adw.Dialog):
    """Diálogo que devolve o ``AppEntry`` escolhido."""

    def __init__(self, on_chosen, *, existing: set[str] | None = None) -> None:
        super().__init__()
        self.set_title("Escolher aplicativo")
        self.set_content_width(480)
        self.set_content_height(600)

        self._on_chosen = on_chosen
        self._existing = {e.casefold() for e in (existing or set())}
        self._rows: list[tuple[Adw.ActionRow, AppEntry]] = []

        self._search = Gtk.SearchEntry(placeholder_text="Filtrar aplicativos", hexpand=True)
        self._search.connect("search-changed", self._on_search)

        group = Adw.PreferencesGroup()
        try:
            apps = list_apps()
        except Exception as exc:  # noqa: BLE001 - a lista pode falhar sem Gio
            logger.warning("não consegui listar aplicativos: %s", exc)
            apps = []

        if not apps:
            group.add(
                Adw.ActionRow(
                    title="Nenhum aplicativo encontrado",
                    subtitle="Verifique se o python3-gi está instalado.",
                )
            )
        for app in apps:
            group.add(self._make_row(app))

        page = Adw.PreferencesPage()
        page.add(group)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(page)

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        busca = Gtk.Box(margin_start=12, margin_end=12, margin_top=12, margin_bottom=6)
        busca.append(self._search)
        caixa.append(busca)
        caixa.append(scroller)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(caixa)
        self.set_child(toolbar)

    def _make_row(self, app: AppEntry) -> Adw.ActionRow:
        ja_existe = app.wm_class.casefold() in self._existing
        # O título é interpretado como markup: um "&" num nome como
        # "Software & Updates" derruba a linha inteira se não for escapado.
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(app.name),
            subtitle=GLib.markup_escape_text(
                "Já tem um perfil" if ja_existe else app.wm_class
            ),
            activatable=not ja_existe,
            sensitive=not ja_existe,
        )
        if app.icon:
            imagem = Gtk.Image(pixel_size=32)
            try:
                imagem.set_from_gicon(Gio.Icon.new_for_string(app.icon))
                row.add_prefix(imagem)
            except Exception:  # noqa: BLE001 - ícone quebrado não impede a escolha
                pass
        row.connect("activated", lambda _r, a=app: self._choose(a))
        self._rows.append((row, app))
        return row

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        alvo = entry.get_text().strip().casefold()
        for row, app in self._rows:
            row.set_visible(
                not alvo or alvo in app.name.casefold() or alvo in app.wm_class.casefold()
            )

    def _choose(self, app: AppEntry) -> None:
        self.close()
        self._on_chosen(app)
