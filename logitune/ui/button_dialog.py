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
    ) -> None:
        super().__init__()
        self.set_title(title)
        self.set_content_width(520)
        self.set_content_height(560)

        self._label = title
        self._read = read
        self._write = write
        self._gestures_enabled = gestures_enabled

        self._page = Adw.PreferencesPage()
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self._page)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
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

        modo = Adw.PreferencesGroup(
            title="Como este botão responde",
            description=(
                "Uma ação dispara no clique. Com gestos, o botão espera você "
                "soltar para saber se foi toque, segurar ou arrasto."
            ),
        )
        switch = Adw.SwitchRow(title="Usar gestos", active=usa_gestos)
        switch.connect("notify::active", self._on_mode_changed)
        modo.add(switch)
        self._page.add(modo)

        if usa_gestos and not self._gestures_enabled:
            aviso = Adw.PreferencesGroup()
            aviso.add(
                Adw.ActionRow(
                    title="O reconhecimento de gestos está desligado",
                    subtitle="Ligue em Gestos, na janela principal, para que estes valham.",
                )
            )
            self._page.add(aviso)

        if usa_gestos:
            self._add_gesture_rows(vinculo)
        else:
            self._add_single_row(vinculo)

    def _add_single_row(self, vinculo: ButtonBinding | None) -> None:
        group = Adw.PreferencesGroup(title="Ação")
        atual = vinculo.press if vinculo else None
        group.add(self._make_row("Ao clicar", atual, self._set_press, self._clear_press))
        self._page.add(group)

    def _add_gesture_rows(self, vinculo: ButtonBinding | None) -> None:
        group = Adw.PreferencesGroup(
            title="Gestos",
            description="Segure o botão e arraste. O mouse vibra ao reconhecer a direção.",
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
        botao.set_tooltip_text("Remover")
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
            return "Sem ação"
        try:
            return resolve(binding).label
        except UnknownAction:
            return f"Ação desconhecida: {binding.action}"

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
            heading="Descartar os gestos configurados?",
            body=(
                f"Uma ação só responde ao clique, então {nomes} "
                f"{'serão descartados' if len(perdidos) > 1 else 'será descartado'}."
            ),
        )
        dialogo.add_response("cancelar", "Manter os gestos")
        dialogo.add_response("descartar", "Descartar")
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
