# SPDX-License-Identifier: GPL-3.0-or-later
"""O editor da roda do polegar.

A roda só oferecia três opções fixas enquanto qualquer botão escolhia entre as
53 ações do catálogo, e o resultado é que ela parecia a única parte do mouse
sem personalização. A configuração já aceitava uma ação por sentido de giro;
faltava a interface chegar lá.
"""

from __future__ import annotations

import pytest

from logitune.actions.binding import Binding, WheelBinding

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    Adw.init()
    _tem_gtk = True
except (ImportError, ValueError):  # pragma: no cover - depende do ambiente
    _tem_gtk = False

requer_gtk = pytest.mark.skipif(
    not _tem_gtk, reason="precisa do PyGObject com GTK4 e libadwaita"
)


class _Combo:
    """O mínimo de uma Adw.ComboRow para exercitar a troca de modo."""

    def __init__(self, indice: int) -> None:
        self._indice = indice

    def get_selected(self) -> int:
        return self._indice


@requer_gtk
class TestEditorDaRoda:
    @pytest.fixture
    def editor(self):
        from logitune.ui.wheel_dialog import WheelDialog

        gravado = [None]
        dialogo = WheelDialog(
            lambda: gravado[0], lambda valor: gravado.__setitem__(0, valor)
        )
        return dialogo, gravado

    def _escolher(self, dialogo, modo: str) -> None:
        from logitune.ui.wheel_dialog import _MODOS

        dialogo._on_mode_changed(_Combo(_MODOS.index(modo)), None)

    def test_comeca_na_rolagem_lateral(self, editor):
        dialogo, _gravado = editor
        assert dialogo._modo(dialogo._binding()) == "scroll"

    def test_uma_acao_por_sentido_nao_volta_sozinha_para_rolagem(self, editor):
        """Escolher o modo e ver o menu voltar atrás parece defeito.

        "Uma ação por sentido" começa sem ação nenhuma, e uma configuração
        vazia se lê como rolagem lateral. Sem lembrar a escolha, o modo
        revertia na hora e as duas linhas de ação nunca apareciam.
        """
        dialogo, _gravado = editor
        self._escolher(dialogo, "actions")
        assert dialogo._modo(dialogo._binding()) == "actions"

    def test_o_alternador_grava_o_comportamento_continuo(self, editor):
        dialogo, gravado = editor
        self._escolher(dialogo, "switch")
        assert gravado[0] == "window.switch_apps"
        assert WheelBinding.parse(gravado[0]).stateful == "window.switch_apps"

    def test_voltar_para_rolagem_apaga_a_configuracao(self, editor):
        dialogo, gravado = editor
        self._escolher(dialogo, "switch")
        self._escolher(dialogo, "scroll")
        assert gravado[0] is None

    def test_cada_sentido_guarda_a_sua_acao(self, editor):
        dialogo, gravado = editor
        dialogo._set("up", Binding(action="media.volume_up"))
        dialogo._set("down", Binding(action="media.volume_down"))
        assert gravado[0] == {
            "up": "media.volume_up",
            "down": "media.volume_down",
        }
        vinculo = WheelBinding.parse(gravado[0])
        assert vinculo.up.action == "media.volume_up"
        assert vinculo.down.action == "media.volume_down"

    def test_um_sentido_nao_apaga_o_outro(self, editor):
        dialogo, gravado = editor
        dialogo._set("up", Binding(action="media.volume_up"))
        dialogo._set("down", Binding(action="media.volume_down"))
        dialogo._set("up", None)
        assert gravado[0] == {"down": "media.volume_down"}

    def test_uma_acao_com_parametro_sobrevive_a_ida_e_volta(self, editor):
        """O que a roda grava tem que voltar igual do JSON."""
        dialogo, gravado = editor
        dialogo._set(
            "up",
            Binding(action="app.launch", params={"app": "org.gnome.Calculator.desktop"}),
        )
        vinculo = WheelBinding.parse(gravado[0])
        assert vinculo.up.action == "app.launch"
        assert vinculo.up.params == {"app": "org.gnome.Calculator.desktop"}

    def test_o_alternador_nao_vira_duas_acoes_soltas(self, editor):
        """Trocar do contínuo para "por sentido" começa vazio de propósito."""
        dialogo, gravado = editor
        self._escolher(dialogo, "switch")
        self._escolher(dialogo, "actions")
        assert gravado[0] == {}
        assert WheelBinding.parse(gravado[0]).stateful is None
