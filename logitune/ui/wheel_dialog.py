# SPDX-License-Identifier: GPL-3.0-or-later
"""O que a roda do polegar faz.

A roda tinha três opções fixas num menu suspenso — rolagem lateral, alternar
aplicativos, volume — enquanto qualquer botão escolhia entre as 53 ações do
catálogo. A configuração já aceitava uma ação por sentido de giro desde o
começo; era só a interface que não deixava chegar lá, e o resultado é que a
roda parecia não ter personalização nenhuma.

São dois modos, e eles não se misturam. Uma ação por sentido dispara a cada
giro e é o caso comum. O alternador de aplicativos é contínuo: precisa saber
que a roda ainda está girando para só trazer a janela à frente quando ela
para, e por isso não pode ser descrito como "uma ação para cima, outra para
baixo".
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from logitune.actions import Binding, UnknownAction, resolve  # noqa: E402
from logitune.actions.binding import WheelBinding  # noqa: E402
from logitune.i18n import _  # noqa: E402
from logitune.ui.action_picker import ActionPicker  # noqa: E402

logger = logging.getLogger(__name__)

#: O comportamento contínuo que a roda sabe fazer hoje.
_ALTERNADOR = "window.switch_apps"

#: Os modos, na ordem em que aparecem. O primeiro é o de fábrica.
_MODOS = ("scroll", "actions", "switch")


def _rotulo_do_modo(modo: str) -> str:
    """O nome de um modo, traduzido na hora de montar.

    Traduzir numa constante de módulo fixaria o texto no idioma que valia na
    importação, que é antes de o programa escolher o seu.
    """
    return {
        "scroll": _("Scroll sideways"),
        "actions": _("An action for each direction"),
        "switch": _("Switch applications"),
    }[modo]


class WheelDialog(Adw.Dialog):
    """Edita o que a roda do polegar faz, com o mesmo catálogo dos botões."""

    def __init__(self, read, write, *, profile: str | None = None) -> None:
        super().__init__()
        self.set_title(_("Thumb wheel"))
        self.set_content_width(520)
        self.set_content_height(520)

        self._read = read
        self._write = write
        self._profile = profile
        #: O modo que a pessoa escolheu, quando ele ainda não dá para deduzir
        #: do que está gravado. "Uma ação por sentido" começa sem ação
        #: nenhuma, e sem esta lembrança a configuração vazia se leria como
        #: "rolagem lateral" — o modo voltava sozinho e as linhas de ação
        #: nunca chegavam a aparecer.
        self._modo_escolhido: str | None = None

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._page = Adw.PreferencesPage()
        scroller.set_child(self._page)

        subtitulo = _("in “{}”").format(profile) if profile else _("this mouse")
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(
            Adw.HeaderBar(
                title_widget=Adw.WindowTitle(title=_("Thumb wheel"), subtitle=subtitulo)
            )
        )
        toolbar.set_content(scroller)
        self.set_child(toolbar)

        self._rebuild()

    # -- montagem ------------------------------------------------------

    def _binding(self) -> WheelBinding:
        return WheelBinding.parse(self._read())

    def _modo(self, vinculo: WheelBinding) -> str:
        if vinculo.stateful:
            return "switch"
        if vinculo.up is not None or vinculo.down is not None:
            return "actions"
        return self._modo_escolhido or "scroll"

    def _rebuild(self) -> None:
        # A Adw.PreferencesPage não remove grupos por API pública, então a
        # reconstrução troca a página inteira dentro do scroller.
        self._page = Adw.PreferencesPage()
        self.get_child().get_content().set_child(self._page)

        vinculo = self._binding()
        modo = self._modo(vinculo)

        identificacao = Adw.PreferencesGroup()
        cabecalho = Adw.ActionRow(
            title=_("Thumb wheel"),
            subtitle=(
                _("Applies only while “{}” is in front").format(self._profile)
                if self._profile
                else _("Applies whenever no profile takes over")
            ),
        )
        cabecalho.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        identificacao.add(cabecalho)
        self._page.add(identificacao)

        grupo = Adw.PreferencesGroup(
            title=_("What rolling does"),
            description=_(
                "The wheel keeps scrolling sideways until you give it "
                "something else to do."
            ),
        )
        combo = Adw.ComboRow(title=_("Mode"))
        modelo = Gtk.StringList()
        for valor in _MODOS:
            modelo.append(_rotulo_do_modo(valor))
        combo.set_model(modelo)
        combo.set_selected(_MODOS.index(modo))
        combo.connect("notify::selected", self._on_mode_changed)
        grupo.add(combo)
        self._page.add(grupo)

        if modo == "actions":
            acoes = Adw.PreferencesGroup(
                title=_("Actions"),
                description=_("Each notch of the wheel fires one of these."),
            )
            acoes.add(
                self._make_row(
                    _("Roll forward"),
                    vinculo.up,
                    lambda b: self._set("up", b),
                    lambda: self._set("up", None),
                )
            )
            acoes.add(
                self._make_row(
                    _("Roll back"),
                    vinculo.down,
                    lambda b: self._set("down", b),
                    lambda: self._set("down", None),
                )
            )
            self._page.add(acoes)
        elif modo == "switch":
            aviso = Adw.PreferencesGroup()
            aviso.add(
                Adw.ActionRow(
                    title=_("Rolling walks through the open windows"),
                    subtitle=_(
                        "The chosen window comes forward once the wheel stops. "
                        "How long it waits is under Thumb wheel, in the main "
                        "window."
                    ),
                )
            )
            self._page.add(aviso)

    def _make_row(self, titulo: str, binding, definir, limpar) -> Adw.ActionRow:
        row = Adw.ActionRow(
            title=titulo, subtitle=self._describe(binding), activatable=True
        )
        row.set_tooltip_text(
            _("Choose what one notch of the wheel does in this direction.")
        )

        botao = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        botao.add_css_class("flat")
        botao.set_sensitive(binding is not None)
        botao.set_tooltip_text(_("Remove"))
        botao.connect("clicked", lambda _b: (limpar(), self._rebuild()))
        row.add_suffix(botao)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))

        def escolher(_r) -> None:
            def pronto(novo: Binding) -> None:
                definir(novo)
                self._rebuild()

            ActionPicker(pronto, current=binding).present(self)

        row.connect("activated", escolher)
        return row

    def _describe(self, binding) -> str:
        if binding is None:
            return _("No action")
        try:
            return resolve(binding).label
        except UnknownAction:
            return _("Unknown action: {}").format(binding.action)

    # -- edição --------------------------------------------------------

    def _on_mode_changed(self, row: Adw.ComboRow, _param) -> None:
        modo = _MODOS[row.get_selected()]
        if modo == self._modo(self._binding()):
            return
        self._modo_escolhido = modo
        if modo == "scroll":
            self._write(None)
        elif modo == "switch":
            self._write(_ALTERNADOR)
        else:
            # Trocar para "uma ação por sentido" começa vazio de propósito: o
            # alternador não se traduz em duas ações independentes, e herdar
            # qualquer coisa dele seria inventar.
            self._write({})
        self._rebuild()

    def _set(self, sentido: str, binding: Binding | None) -> None:
        vinculo = self._binding()
        atual = {
            "up": vinculo.up.to_json() if vinculo.up else None,
            "down": vinculo.down.to_json() if vinculo.down else None,
        }
        atual[sentido] = binding.to_json() if binding else None
        self._write({k: v for k, v in atual.items() if v is not None})
