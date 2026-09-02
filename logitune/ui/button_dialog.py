# SPDX-License-Identifier: GPL-3.0-or-later
"""O que um botão faz: uma ação, ou um gesto para cada movimento.

Um botão é uma coisa ou a outra, nunca as duas. Um botão com gestos precisa do
reconhecedor, que decide entre toque e arrasto só quando o botão é solto; um
botão de ação simples dispara no aperto. Misturar os dois significaria disparar
antes de saber se aquilo ia virar um arrasto.

O diálogo é desacoplado dos perfis de propósito: ele recebe funções para ler e
gravar o vínculo, e não sabe se está editando o perfil global ou o de um
aplicativo.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from logitune.actions import Binding, ButtonBinding, UnknownAction, resolve  # noqa: E402
from logitune.actions.gestures import Gesture  # noqa: E402
from logitune.i18n import _  # noqa: E402
from logitune.ui.action_picker import ActionPicker  # noqa: E402

logger = logging.getLogger(__name__)

#: A ordem em que os gestos aparecem: o toque primeiro, depois os arrastos por
#: par de eixo, que é como a mão os pensa.
_GESTURE_ORDER = (
    Gesture.TAP,
    Gesture.DOUBLE_TAP,
    Gesture.HOLD,
    Gesture.DRAG_LEFT,
    Gesture.DRAG_RIGHT,
    Gesture.DRAG_UP,
    Gesture.DRAG_DOWN,
)


class ButtonDialog(Adw.Dialog):
    """Edita o vínculo de um botão, com ou sem gestos."""

    def __init__(
        self,
        title: str,
        read,
        write,
        *,
        gestures_enabled: bool = True,
        profile: str | None = None,
    ) -> None:
        super().__init__()
        self.set_title(title)
        self.set_content_width(520)
        self.set_content_height(560)

        self._label = title
        self._read = read
        self._write = write
        self._gestures_enabled = gestures_enabled
        self._profile = profile

        self._page = Adw.PreferencesPage()
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self._page)

        # Qual botão está sendo editado precisa ficar visível o tempo todo. O
        # título de um Adw.Dialog é discreto de propósito, e com seis botões
        # parecidos e o diálogo aberto por um marcador no desenho, era fácil
        # perder a conta de qual deles estava na tela.
        subtitulo = (
            _("in “{}”").format(profile) if profile else _("this mouse")
        )
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(
            Adw.HeaderBar(title_widget=Adw.WindowTitle(title=title, subtitle=subtitulo))
        )
        toolbar.set_content(scroller)
        self.set_child(toolbar)

        self._rebuild()

    # -- montagem ------------------------------------------------------

    def _rebuild(self) -> None:
        # A Adw.PreferencesPage não remove grupos por API pública, então a
        # reconstrução troca a página inteira dentro do scroller.
        self._page = Adw.PreferencesPage()
        self.get_child().get_content().set_child(self._page)

        vinculo = self._read()
        usa_gestos = bool(vinculo and vinculo.gestures)

        identificacao = Adw.PreferencesGroup()
        cabecalho = Adw.ActionRow(
            title=GLib.markup_escape_text(self._label),
            subtitle=(
                _("Applies only while “{}” is in front").format(self._profile)
                if self._profile
                else _("Applies whenever no profile takes over")
            ),
        )
        cabecalho.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        identificacao.add(cabecalho)
        self._page.add(identificacao)

        modo = Adw.PreferencesGroup(
            title=_("How this button responds"),
            description=(
                _(
                    "One action fires on click. With gestures, the button waits "
                    "for you to release before deciding between tap, hold and drag."
                )
            ),
        )
        switch = Adw.SwitchRow(title=_("Use gestures"), active=usa_gestos)
        switch.connect("notify::active", self._on_mode_changed)
        modo.add(switch)
        self._page.add(modo)

        if usa_gestos and not self._gestures_enabled:
            aviso = Adw.PreferencesGroup()
            aviso.add(
                Adw.ActionRow(
                    title=_("Gesture recognition is switched off"),
                    subtitle=_("Turn it on under Gestures, in the main window."),
                )
            )
            self._page.add(aviso)

        if usa_gestos:
            self._add_gesture_rows(vinculo)
        else:
            self._add_single_row(vinculo)

    def _add_single_row(self, vinculo: ButtonBinding | None) -> None:
        group = Adw.PreferencesGroup(title=_("Action"))
        atual = vinculo.press if vinculo else None
        group.add(self._make_row(_("On click"), atual, self._set_press, self._clear_press))
        self._page.add(group)

    def _add_gesture_rows(self, vinculo: ButtonBinding | None) -> None:
        group = Adw.PreferencesGroup(
            title=_("Gestures"),
            description=_(
                "Hold the button and drag. The mouse buzzes when it recognises the direction."
            ),
        )
        gestos = vinculo.gestures if vinculo else {}
        for gesto in _GESTURE_ORDER:
            group.add(
                self._make_row(
                    gesto.label.capitalize(),
                    gestos.get(gesto),
                    lambda b, g=gesto: self._set_gesture(g, b),
                    lambda g=gesto: self._clear_gesture(g),
                )
            )
        self._page.add(group)

    def _make_row(self, titulo: str, binding: Binding | None, definir, limpar) -> Adw.ActionRow:
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(titulo),
            subtitle=self._describe(binding),
            activatable=True,
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

    def _describe(self, binding: Binding | None) -> str:
        if binding is None:
            return _("No action")
        try:
            return resolve(binding).label
        except UnknownAction:
            return _("Unknown action: {}").format(binding.action)

    # -- edição --------------------------------------------------------

    def _on_mode_changed(self, row: Adw.SwitchRow, _param) -> None:
        vinculo = self._read()
        if row.get_active():
            # Trocar para gestos leva a ação atual para o toque, que é o gesto
            # equivalente ao clique — descartá-la faria o botão emudecer.
            atual = vinculo.press if vinculo else None
            gestos = {Gesture.TAP: atual} if atual else {}
            self._write(ButtonBinding(gestures=gestos))
            self._rebuild()
            return

        gestos = dict(vinculo.gestures) if vinculo else {}
        perdidos = [g for g in gestos if g is not Gesture.TAP]
        if perdidos:
            # Só o toque sobrevive como ação de clique. Descartar cinco gestos
            # configurados sem avisar é perda de trabalho sem desfazer.
            self._confirm_drop(row, gestos, perdidos)
            return
        self._apply_single(gestos)

    def _apply_single(self, gestos: dict) -> None:
        self._write(ButtonBinding(press=gestos.get(Gesture.TAP)))
        self._rebuild()

    def _confirm_drop(self, row: Adw.SwitchRow, gestos: dict, perdidos: list) -> None:
        nomes = ", ".join(g.label for g in perdidos)
        dialogo = Adw.AlertDialog(
            heading=_("Discard the configured gestures?"),
            body=(
                _("An action only responds to a click, so {} will be discarded.").format(nomes)
            ),
        )
        dialogo.add_response("cancelar", _("Keep the gestures"))
        dialogo.add_response("descartar", _("Discard"))
        dialogo.set_response_appearance("descartar", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_default_response("cancelar")

        def respondeu(_d, resposta: str) -> None:
            if resposta == "descartar":
                self._apply_single(gestos)
            else:
                # Devolve o interruptor sem disparar o handler de novo.
                row.handler_block_by_func(self._on_mode_changed)
                row.set_active(True)
                row.handler_unblock_by_func(self._on_mode_changed)

        dialogo.connect("response", respondeu)
        dialogo.present(self)

    def _set_press(self, binding: Binding) -> None:
        self._write(ButtonBinding(press=binding))

    def _clear_press(self) -> None:
        self._write(None)

    def _set_gesture(self, gesto: Gesture, binding: Binding) -> None:
        vinculo = self._read()
        gestos = dict(vinculo.gestures) if vinculo else {}
        gestos[gesto] = binding
        self._write(ButtonBinding(gestures=gestos))

    def _clear_gesture(self, gesto: Gesture) -> None:
        vinculo = self._read()
        gestos = dict(vinculo.gestures) if vinculo else {}
        gestos.pop(gesto, None)
        self._write(ButtonBinding(gestures=gestos) if gestos else None)
