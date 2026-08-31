# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da feature de DPI, incluindo a normalização de faixas."""

from __future__ import annotations

import pytest

from logitune.hidpp.device import Hidpp20Device
from logitune.hidpp.features.dpi import AdjustableDpi, DpiRange
from tests.fake_transport import FakeTransport


class TestDpiRange:
    def test_faixa_continua_arredonda_para_o_passo(self):
        faixa = DpiRange(minimum=200, maximum=8000, step=50)
        assert faixa.clamp(3333) == 3350
        assert faixa.clamp(2800) == 2800

    def test_faixa_continua_limita_nos_extremos(self):
        faixa = DpiRange(minimum=200, maximum=8000, step=50)
        assert faixa.clamp(10) == 200
        assert faixa.clamp(99999) == 8000

    def test_clamp_nunca_ultrapassa_o_maximo(self):
        # 7990 arredondaria para 8000; com um máximo que não é múltiplo do
        # passo, o resultado ainda precisa caber na faixa.
        faixa = DpiRange(minimum=200, maximum=7990, step=50)
        assert faixa.clamp(7989) <= 7990

    def test_lista_discreta_escolhe_o_mais_proximo(self):
        faixa = DpiRange(minimum=800, maximum=3200, step=0, values=(800, 1600, 3200))
        assert faixa.clamp(1000) == 800
        assert faixa.clamp(1500) == 1600
        assert not faixa.is_continuous

    def test_steps_de_faixa_continua(self):
        faixa = DpiRange(minimum=200, maximum=400, step=100)
        assert faixa.steps() == [200, 300, 400]


class TestAdjustableDpi:
    def _device(self, dpi_list: bytes) -> AdjustableDpi:
        transport = FakeTransport(
            features={0x0000: 0, 0x0001: 1, 0x2201: 2},
            responses={
                (0x2201, 0x00): bytes([1]),
                (0x2201, 0x01): dpi_list,
                (0x2201, 0x02): bytes([0, 0x0A, 0xF0, 0x03, 0xE8]),
                (0x2201, 0x03): b"",
            },
        )
        return AdjustableDpi(Hidpp20Device(transport, device_index=1))

    def test_decodifica_faixa_continua(self):
        # sensor 0, mínimo 200, marcador de passo 0xE032 (passo 50), máximo 8000
        payload = bytes([0]) + b"\x00\xc8" + b"\xe0\x32" + b"\x1f\x40"
        faixa = self._device(payload).get_range()
        assert (faixa.minimum, faixa.step, faixa.maximum) == (200, 50, 8000)
        assert faixa.is_continuous

    def test_decodifica_lista_discreta(self):
        payload = bytes([0]) + b"\x03\x20" + b"\x06\x40" + b"\x00\x00"
        faixa = self._device(payload).get_range()
        assert faixa.values == (800, 1600)

    def test_le_dpi_atual_e_padrao(self):
        payload = bytes([0]) + b"\x00\xc8" + b"\xe0\x32" + b"\x1f\x40"
        estado = self._device(payload).get_dpi()
        assert estado.current == 2800
        assert estado.default == 1000
