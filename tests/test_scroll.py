# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da roda do polegar (0x2150).

O desvio desta roda é o estado que mais confunde: desviada, ela para de gerar
rolagem e passa a mandar notificações HID++. Quem chega vindo do Solaar herda
o flag ligado no firmware — ele o liga e, desinstalado, não restaura.
"""

from __future__ import annotations

from logitune.hidpp.constants import SOFTWARE_ID, FeatureID
from logitune.hidpp.device import Hidpp20Device
from logitune.hidpp.features.scroll import ThumbWheel
from tests.fake_transport import FakeTransport


_GET_STATUS = 0x01
_SET_REPORTING = 0x02


def _thumbwheel(*, diverted: bool, inverted: bool) -> tuple[ThumbWheel, FakeTransport]:
    feature = int(FeatureID.THUMB_WHEEL)
    transport = FakeTransport(
        features={int(FeatureID.ROOT): 0, feature: 1},
        responses={
            (feature, _GET_STATUS): bytes([int(diverted), int(inverted)]),
            # setReporting não devolve nada útil, mas precisa responder.
            (feature, _SET_REPORTING): b"",
        },
    )
    return ThumbWheel(Hidpp20Device(transport, device_index=1)), transport


def _ultimo_set_reporting(transport: FakeTransport) -> bytes:
    """Os parâmetros do último setReporting escrito no dispositivo."""
    esperado = ((_SET_REPORTING & 0x0F) << 4) | SOFTWARE_ID
    escritas = [w for w in transport.written if w[2] == 1 and w[3] == esperado]
    return escritas[-1][4:6]


class TestDesvioDaRodaDoPolegar:
    def test_le_o_estado_desviado(self):
        roda, _ = _thumbwheel(diverted=True, inverted=True)
        estado = roda.get_state()
        assert estado.diverted is True
        assert estado.inverted is True

    def test_desfazer_o_desvio_preserva_a_inversao(self):
        """Devolver a rolagem não pode custar a preferência de direção.

        set_state lê o estado atual e só troca o que foi pedido; sem isso,
        consertar a roda zeraria a inversão de quem a usava invertida.
        """
        roda, transport = _thumbwheel(diverted=True, inverted=True)
        roda.set_state(diverted=False)
        assert _ultimo_set_reporting(transport) == bytes([0, 1])

    def test_inverter_preserva_o_desvio(self):
        roda, transport = _thumbwheel(diverted=True, inverted=False)
        roda.set_state(inverted=True)
        assert _ultimo_set_reporting(transport) == bytes([1, 1])

    def test_muda_os_dois_de_uma_vez(self):
        roda, transport = _thumbwheel(diverted=True, inverted=True)
        roda.set_state(diverted=False, inverted=False)
        assert _ultimo_set_reporting(transport) == bytes([0, 0])
