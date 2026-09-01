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


class TestNotificacaoDuranteRequisicao:
    """Uma requisição não pode engolir as notificações que chegam junto.

    É o cenário do retorno háptico: ao cruzar o limiar de um arrasto o daemon
    manda o mouse vibrar, e enquanto espera essa resposta continuam chegando
    eventos de movimento — e, no fim, o aviso de que o botão foi solto. Perder
    esse aviso deixaria o gesto pendurado para sempre.
    """

    def _dispositivo(self):
        from logitune.hidpp.constants import FeatureID
        from logitune.hidpp.device import Hidpp20Device
        from tests.fake_transport import FakeTransport

        haptic = int(FeatureID.MX4_HAPTIC)
        # Índices contíguos, como num dispositivo real. O FEATURE_SET precisa
        # estar presente para o listener conseguir nomear a feature de onde a
        # notificação veio.
        transport = FakeTransport(
            features={
                int(FeatureID.ROOT): 0,
                int(FeatureID.FEATURE_SET): 1,
                _REPROG: 2,
                haptic: 3,
            },
            responses={(haptic, 0x04): b"\x02"},
        )
        return Hidpp20Device(transport, device_index=1), transport

    def _notificacao_crua(self, function: int, data: bytes) -> bytes:
        # 0x11 longo, dispositivo 1, feature no índice 2 (0x1B04), software ID zero.
        return bytes([0x11, 0x01, 0x02, (function << 4) | 0x00]) + data.ljust(16, b"\x00")

    def test_evento_que_chega_durante_a_requisicao_e_preservado(self):
        from logitune.hidpp.features.haptic import Haptic

        device, transport = self._dispositivo()
        listener = NotificationListener(device)

        # O movimento e o "soltou" chegam enquanto a vibração é pedida.
        transport.queue(self._notificacao_crua(_MOVIMENTO, b"\x00\x64\x00\x00"))
        transport.queue(self._notificacao_crua(_BOTOES, b"\x00\x00\x00\x00"))

        Haptic(device).play(2)

        primeira = listener.poll(timeout=0)
        assert primeira is not None
        assert listener.as_raw_movement(primeira) == RawMovement(dx=100, dy=0)

        segunda = listener.poll(timeout=0)
        assert segunda is not None
        evento = listener.as_button_event(segunda)
        assert evento is not None and evento.pressed == frozenset()

    def test_a_fila_nao_cresce_sem_limite(self):
        device, transport = self._dispositivo()
        for _ in range(200):
            device._stashed.append(b"\x11\x01\x01\x00")
        assert len(device._stashed) <= 64


class TestRodaDoPolegar:
    """Bytes medidos num MX Master 4 (RBM 27.03.B0019), não deduzidos.

    A primeira leitura tomava o byte 3 por bandeiras e inventava toque e
    proximidade a partir de um carimbo de tempo — o mesmo dispositivo cujo
    getInfo diz não ter nenhum dos dois sensores.
    """

    from logitune.hidpp.constants import FeatureID as _F

    AMOSTRAS = [
        ("ff f8 00 07 02 02", -8, "ACTIVE", 7),
        ("00 01 00 00 01 02", +1, "START", 0),
        ("00 00 00 00 03 00", 0, "STOP", 0),
        ("00 00 00 00 00 02", 0, "INACTIVE", 0),
        ("00 18 00 05 02 02", +24, "ACTIVE", 5),
        ("00 02 00 17 02 02", +2, "ACTIVE", 23),
        ("ff ff 00 0c 02 02", -1, "ACTIVE", 12),
    ]

    @pytest.mark.parametrize("cru, delta, status, ts", AMOSTRAS)
    def test_leitura_dos_bytes_reais(self, listener, cru, delta, status, ts):
        from logitune.hidpp.constants import FeatureID

        evento = listener.as_thumbwheel_event(
            _notificacao(0x00, bytes.fromhex(cru), feature_id=int(FeatureID.THUMB_WHEEL))
        )
        assert evento is not None
        assert evento.delta == delta
        assert evento.status.name == status
        assert evento.timestamp == ts

    def test_o_sinal_separa_os_sentidos(self, listener):
        """Ler sem sinal transformaria um giro em 65528 no sentido oposto."""
        from logitune.hidpp.constants import FeatureID

        subindo = listener.as_thumbwheel_event(
            _notificacao(0x00, bytes.fromhex("00 08 00 07 02 02"), feature_id=int(FeatureID.THUMB_WHEEL))
        )
        descendo = listener.as_thumbwheel_event(
            _notificacao(0x00, bytes.fromhex("ff f8 00 07 02 02"), feature_id=int(FeatureID.THUMB_WHEEL))
        )
        assert subindo.delta == -descendo.delta == 8

    def test_ignora_outra_feature(self, listener):
        assert listener.as_thumbwheel_event(_notificacao(_MOVIMENTO, b"\x00\x08")) is None
