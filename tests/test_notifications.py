# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes das notificações do 0x1B04, incluindo o movimento bruto.

O ``divertedRawXYEvent`` é a matéria-prima dos gestos: sem ele o dispositivo
não conta nada sobre o movimento, e não há como separar um toque de um
arrasto.
"""

from __future__ import annotations

import pytest

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.notifications import (
    Notification,
    NotificationListener,
    RawMovement,
)

_REPROG = int(FeatureID.REPROG_CONTROLS_V4)
_BOTOES = 0x00
_MOVIMENTO = 0x01


def _notificacao(function: int, data: bytes, feature_id: int = _REPROG) -> Notification:
    return Notification(
        device_index=1,
        feature_index=7,
        function=function,
        data=data,
        feature_id=feature_id,
    )


@pytest.fixture
def listener() -> NotificationListener:
    # Nenhum método exercitado aqui toca no dispositivo.
    return NotificationListener(device=None)  # type: ignore[arg-type]


class TestMovimentoBruto:
    def test_le_deslocamento_positivo(self, listener):
        movimento = listener.as_raw_movement(_notificacao(_MOVIMENTO, b"\x00\x0a\x00\x05"))
        assert movimento == RawMovement(dx=10, dy=5)

    def test_le_deslocamento_negativo(self, listener):
        """Arrastar para a esquerda e para cima dá valores negativos.

        Ler estes bytes sem sinal transformaria um arrasto para a esquerda em
        um deslocamento de 65526 para a direita — o gesto sairia invertido e
        com magnitude absurda.
        """
        movimento = listener.as_raw_movement(_notificacao(_MOVIMENTO, b"\xff\xf6\xff\xfb"))
        assert movimento == RawMovement(dx=-10, dy=-5)

    def test_extremos_de_16_bits(self, listener):
        assert listener.as_raw_movement(
            _notificacao(_MOVIMENTO, b"\x7f\xff\x80\x00")
        ) == RawMovement(dx=32767, dy=-32768)

    def test_distancia_ao_quadrado(self):
        assert RawMovement(dx=3, dy=4).distance_squared == 25
        assert RawMovement(dx=-3, dy=-4).distance_squared == 25

    def test_ignora_a_notificacao_de_botoes(self, listener):
        assert listener.as_raw_movement(_notificacao(_BOTOES, b"\x01\xa0\x00\x00")) is None

    def test_ignora_outra_feature(self, listener):
        outra = _notificacao(_MOVIMENTO, b"\x00\x0a\x00\x05", feature_id=0x1004)
        assert listener.as_raw_movement(outra) is None

    def test_payload_curto_nao_estoura(self, listener):
        assert listener.as_raw_movement(_notificacao(_MOVIMENTO, b"\x00\x0a")) is None


class TestEventosDeBotao:
    def test_produz_bordas_de_subida_e_descida(self, listener):
        # O dispositivo manda a lista do que está pressionado agora; as
        # transições saem de comparar com a lista anterior.
        primeiro = listener.as_button_event(_notificacao(_BOTOES, b"\x01\xa0\x00\x00"))
        assert primeiro.just_pressed == {0x01A0}
        assert primeiro.just_released == frozenset()

        segundo = listener.as_button_event(_notificacao(_BOTOES, b"\x00\x00\x00\x00"))
        assert segundo.just_pressed == frozenset()
        assert segundo.just_released == {0x01A0}

    def test_movimento_nao_e_lido_como_botao(self, listener):
        assert listener.as_button_event(_notificacao(_MOVIMENTO, b"\x00\x0a\x00\x05")) is None
