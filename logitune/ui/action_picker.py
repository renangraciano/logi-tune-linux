# SPDX-License-Identifier: GPL-3.0-or-later
"""Escolha de ação para um botão.

O catálogo tem 53 entradas em nove categorias, o que é demais para um menu
suspenso. Este diálogo mostra as recomendadas primeiro, agrupa o resto por
categoria e filtra conforme se digita, que é como o Logi Options+ resolve o
mesmo problema.

Uma decisão que vale explicar: as ações indisponíveis aparecem, apagadas e com
o motivo ao lado, em vez de sumirem. Uma opção que existe na documentação e
não está na tela parece defeito do programa; uma opção que se explica ensina o
que falta instalar.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from logitune.actions import Binding, default_registry  # noqa: E402
from logitune.ui.app_picker import AppPicker  # noqa: E402
from logitune.actions.spec import ActionSpec  # noqa: E402
from logitune.i18n import _  # noqa: E402

logger = logging.getLogger(__name__)


class _EscolhaDeAplicativo(Adw.ActionRow):
    """Escolhe um aplicativo da lista instalada em vez de exigir digitação.

    O campo era uma caixa de texto e o que se escreve naturalmente é o nome do
    comando — ``gnome-calculator`` — que não é o id ``.desktop``. Escolher da
    lista grava o id certo, e mostra nome e ícone, que é como a pessoa
    reconhece o aplicativo.
    """

    __gtype_name__ = "LogituneEscolhaDeAplicativo"

    def __init__(self, titulo: str, pai) -> None:
        super().__init__(title=titulo, activatable=True)
        self._valor = ""
        self._pai = pai
        self._icone = Gtk.Image(pixel_size=24)
        self.add_prefix(self._icone)
        self.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.set_subtitle(_("Pick from the installed applications"))
        self.connect("activated", lambda _r: self._abrir())

    def _abrir(self) -> None:
        def escolhido(app) -> None:
            self.remove_css_class("error")
            self._valor = app.desktop_id or app.name
            self.set_subtitle(GLib.markup_escape_text(app.name))
            self._mostrar_icone(app.icon)

        AppPicker(escolhido).present(self._pai)

    def _mostrar_icone(self, nome: str) -> None:
        if not nome:
            self._icone.clear()
            return
        try:
            from gi.repository import Gio

            self._icone.set_from_gicon(Gio.Icon.new_for_string(nome))
        except Exception:  # noqa: BLE001 - ícone quebrado não impede a escolha
            self._icone.clear()

    # A mesma interface de uma Adw.EntryRow, para o diálogo tratar os campos
    # todos do mesmo jeito.

    def get_text(self) -> str:
        return self._valor

    def set_text(self, valor: str) -> None:
        self._valor = valor or ""
        if not self._valor:
            return
        # Um valor que já estava gravado pode ser id, executável ou nome.
        try:
            from logitune.actions.backends.launch import find_app

            info = find_app(self._valor)
        except Exception:  # noqa: BLE001 - sem Gio, mostra o texto cru
            info = None
        if info is None:
            self.set_subtitle(
                _("{} — not installed any more").format(
                    GLib.markup_escape_text(self._valor)
                )
            )
            return
        self.set_subtitle(GLib.markup_escape_text(info.get_display_name() or self._valor))
        icone = info.get_icon()
        self._mostrar_icone(icone.to_string() if icone else "")


class ActionPicker(Adw.Dialog):
    """Diálogo que devolve o vínculo escolhido pelo callback ``on_chosen``."""

    def __init__(self, on_chosen, *, current: Binding | None = None) -> None:
        super().__init__()
        self.set_title(_("Choose an action"))
        self.set_content_width(520)
        self.set_content_height(640)

        self._on_chosen = on_chosen
        self._current = current
        self._registry = default_registry()
        self._rows: list[tuple[Gtk.Widget, ActionSpec]] = []
        self._groups: list[Adw.PreferencesGroup] = []

        self._search = Gtk.SearchEntry(placeholder_text=_("Filter actions"))
        self._search.connect("search-changed", self._on_search)

        self._page = Adw.PreferencesPage()
        self._build_groups()

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self._page)

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        busca = Gtk.Box(margin_start=12, margin_end=12, margin_top=12, margin_bottom=6)
        self._search.set_hexpand(True)
        busca.append(self._search)
        caixa.append(busca)
        caixa.append(scroller)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(caixa)
        self.set_child(toolbar)

    # -- montagem ------------------------------------------------------

    def _build_groups(self) -> None:
        destaque = self._registry.recommended()
        if destaque:
            self._add_group(_("Recommended"), destaque)
        for categoria, specs in self._registry.by_category().items():
            self._add_group(categoria.label, specs)

    def _add_group(self, titulo: str, specs: list[ActionSpec]) -> None:
        group = Adw.PreferencesGroup(title=titulo)
        for spec in specs:
            group.add(self._make_row(spec))
        self._groups.append(group)
        self._page.add(group)

    def _make_row(self, spec: ActionSpec) -> Gtk.Widget:
        disponivel = spec.available()

        subtitulo = spec.description
        if spec.shortcut:
            subtitulo = f"{subtitulo}  ·  {spec.shortcut}" if subtitulo else spec.shortcut
        if not disponivel.ok:
            subtitulo = disponivel.reason

        row = Adw.ActionRow(title=spec.label, subtitle=subtitulo, activatable=True)

        if not disponivel.ok:
            # Não bloqueamos a escolha: uma falta passageira, como nenhum
            # tocador aberto, deixa de existir assim que o programa abre.
            row.add_css_class("dim-label")
            row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
        elif self._current is not None and self._current.action == spec.id:
            row.add_prefix(Gtk.Image(icon_name="object-select-symbolic"))

        row.connect("activated", lambda _r, s=spec: self._choose(s))
        self._rows.append((row, spec))
        return row

    # -- interação -----------------------------------------------------

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        alvo = entry.get_text().strip().casefold()
        for row, spec in self._rows:
            row.set_visible(
                not alvo
                or alvo in spec.id.casefold()
                or alvo in spec.label.casefold()
                or alvo in spec.category.label.casefold()
            )
        # Um grupo sem nenhuma linha visível vira só um título solto.
        for group in self._groups:
            visiveis = any(
                r.get_visible() for r, _ in self._rows if r.get_ancestor(Adw.PreferencesGroup) is group
            )
            group.set_visible(visiveis)

    def _choose(self, spec: ActionSpec) -> None:
        if spec.parameters:
            self._ask_parameters(spec)
            return
        self._finish(Binding(action=spec.id))

    def _ask_parameters(self, spec: ActionSpec) -> None:
        """Segunda etapa: preencher o que a ação precisa.

        Sem isto, escolher "abrir um endereço" gravaria um vínculo sem
        endereço — que o daemon recusaria em silêncio, e o botão ficaria de
        fábrica sem ninguém entender por quê.
        """
        dialogo = Adw.Dialog()
        dialogo.set_title(spec.label)
        dialogo.set_content_width(460)

        group = Adw.PreferencesGroup(
            title=spec.label,
            description=spec.description,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
        )
        campos: dict[str, Adw.PreferencesRow] = {}
        anterior = self._current.params if self._current and self._current.action == spec.id else {}
        for parametro in spec.parameters:
            if parametro.kind == "app":
                row = _EscolhaDeAplicativo(parametro.label, dialogo)
            else:
                row = Adw.EntryRow(title=parametro.label)
            valor = anterior.get(parametro.name, parametro.default)
            if valor is not None:
                row.set_text(str(valor))
            group.add(row)
            campos[parametro.name] = row

        confirmar = Gtk.Button(label=_("Assign"), halign=Gtk.Align.END)
        confirmar.add_css_class("suggested-action")
        confirmar.add_css_class("pill")
        confirmar.set_margin_end(12)
        confirmar.set_margin_bottom(12)

        def aplicar(_b) -> None:
            params = {n: r.get_text().strip() for n, r in campos.items() if r.get_text().strip()}
            faltando = spec.missing_parameters(params)
            if faltando:
                campos[faltando[0].name].add_css_class("error")
                return
            dialogo.close()
            self._finish(Binding(action=spec.id, params=params))

        confirmar.connect("clicked", aplicar)

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        caixa.append(group)
        caixa.append(confirmar)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(caixa)
        dialogo.set_child(toolbar)
        dialogo.present(self)

    def _finish(self, binding: Binding) -> None:
        self.close()
        self._on_chosen(binding)
