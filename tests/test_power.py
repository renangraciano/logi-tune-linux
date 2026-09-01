# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da economia de energia do motor háptico."""

from __future__ import annotations

import pytest

from logitune.actions.power import DEFAULT_THRESHOLD, BatteryGate
from logitune.config import Config
from logitune.hidpp.device import NoResponse
from logitune.hidpp.features.battery import BatteryLevel, BatteryStatus, ChargingStatus


class BateriaFalsa:
    def __init__(self, status, falha=False):
        self._status = status
        self._falha = falha
        self.leituras = 0

    def get_status(self):
        self.leituras += 1
        if self._falha:
            raise NoResponse("sem resposta")
        return self._status


class DispositivoFalso:
    def __init__(self, bateria):
        self.battery = bateria


def _status(percentual, carregando=False):
    return BatteryStatus(
        percentage=percentual,
        level=BatteryLevel.GOOD,
        charging=ChargingStatus.CHARGING if carregando else ChargingStatus.DISCHARGING,
        external_power=carregando,
    )


class TestPortao:
    def test_carga_boa_permite(self):
        assert BatteryGate(20).allows_haptics(DispositivoFalso(BateriaFalsa(_status(50))))

    def test_carga_baixa_cala(self):
        assert not BatteryGate(20).allows_haptics(DispositivoFalso(BateriaFalsa(_status(15))))

    def test_no_limiar_ainda_cala(self):
        # "abaixo de 20" inclui exatamente 20, que é o que a pessoa espera de
        # um controle chamado "silenciar abaixo de".
        assert not BatteryGate(20).allows_haptics(DispositivoFalso(BateriaFalsa(_status(20))))

    def test_carregando_permite_mesmo_com_pouca_carga(self):
        """Ligado na tomada não há o que economizar."""
        gate = BatteryGate(20)
        assert gate.allows_haptics(DispositivoFalso(BateriaFalsa(_status(5, carregando=True))))

    def test_limiar_zero_desliga_a_economia(self):
        gate = BatteryGate(0)
        bateria = BateriaFalsa(_status(1))
        assert gate.allows_haptics(DispositivoFalso(bateria))
        # Nem chega a perguntar: sem economia não há o que decidir.
        assert bateria.leituras == 0

    def test_leitura_que_falha_permite(self):
        """Silenciar o mouse por causa de uma leitura falha seria pior."""
        gate = BatteryGate(20)
        assert gate.allows_haptics(DispositivoFalso(BateriaFalsa(_status(5), falha=True)))

    def test_dispositivo_sem_bateria_permite(self):
        assert BatteryGate(20).allows_haptics(DispositivoFalso(None))

    def test_sem_dispositivo_permite(self):
        assert BatteryGate(20).allows_haptics(None)


class TestCache:
    """Um arrasto dispara dois retornos hápticos, e uma ida ao dispositivo por
    vibração acrescentaria latência no gesto que mais precisa parecer
    instantâneo."""

    def test_nao_pergunta_a_cada_vibracao(self):
        bateria = BateriaFalsa(_status(50))
        gate = BatteryGate(20)
        dispositivo = DispositivoFalso(bateria)
        for _ in range(20):
            gate.allows_haptics(dispositivo, now=0.0)
        assert bateria.leituras == 1

    def test_relê_depois_do_prazo(self):
        bateria = BateriaFalsa(_status(50))
        gate = BatteryGate(20)
        dispositivo = DispositivoFalso(bateria)
        gate.allows_haptics(dispositivo, now=0.0)
        gate.allows_haptics(dispositivo, now=30.0)
        assert bateria.leituras == 1
        gate.allows_haptics(dispositivo, now=120.0)
        assert bateria.leituras == 2

    def test_invalidate_forca_nova_leitura(self):
        bateria = BateriaFalsa(_status(50))
        gate = BatteryGate(20)
        dispositivo = DispositivoFalso(bateria)
        gate.allows_haptics(dispositivo, now=0.0)
        gate.invalidate()
        gate.allows_haptics(dispositivo, now=0.0)
        assert bateria.leituras == 2


class TestConfiguracao:
    def test_padrao(self):
        assert Config().haptics_below == DEFAULT_THRESHOLD

    def test_valor_configurado(self):
        assert Config(power={"haptics_below": 35}).haptics_below == 35

    def test_zero_e_valido_e_significa_desligado(self):
        assert Config(power={"haptics_below": 0}).haptics_below == 0

    @pytest.mark.parametrize("bruto", [-5, 150, "abc", None])
    def test_valor_invalido_cai_no_padrao(self, bruto):
        assert Config(power={"haptics_below": bruto}).haptics_below == DEFAULT_THRESHOLD

    def test_roundtrip_json(self, tmp_path):
        from logitune.config import load

        destino = tmp_path / "config.json"
        Config(power={"haptics_below": 35}).save(destino)
        assert load(destino).haptics_below == 35
