"""Testes da feature háptica (0x19B0)."""

from __future__ import annotations

import pytest

from logitune.hidpp.device import Hidpp20Device
from logitune.hidpp.features.haptic import MAX_WAVEFORM, MIN_WAVEFORM, Haptic
from tests.fake_transport import FakeTransport


def _haptic() -> tuple[Haptic, FakeTransport]:
    transport = FakeTransport(
        features={0x0000: 0, 0x0001: 1, 0x19B0: 2},
        responses={
            (0x19B0, 0x00): bytes([0x00, 0x01, 0x00, 0x3C, 0x08, 0x00, 0x7F, 0xFF]),
            (0x19B0, 0x04): bytes([0x03]),
        },
    )
    return Haptic(Hidpp20Device(transport, device_index=1)), transport


def test_capacidades_preservam_os_bytes_crus():
    haptic, _ = _haptic()
    assert haptic.get_capabilities().raw[:8] == bytes(
        [0x00, 0x01, 0x00, 0x3C, 0x08, 0x00, 0x7F, 0xFF]
    )


def test_play_envia_o_indice_do_padrao():
    haptic, transport = _haptic()
    haptic.play(3)
    # payload começa no byte 4 do report
    assert transport.written[-1][4] == 3


@pytest.mark.parametrize("waveform", [-1, MAX_WAVEFORM + 1, 255])
def test_padrao_fora_da_faixa_e_recusado_antes_de_escrever(waveform):
    haptic, transport = _haptic()
    antes = len(transport.written)
    with pytest.raises(ValueError):
        haptic.play(waveform)
    # A validação acontece do nosso lado: nada chega a ser enviado.
    assert len(transport.written) == antes


@pytest.mark.parametrize("waveform", [MIN_WAVEFORM, 7, MAX_WAVEFORM])
def test_faixa_valida_e_aceita(waveform):
    haptic, _ = _haptic()
    haptic.play(waveform)


class TestComandoHaptic:
    """A CLI precisa tocar de fato, e não cair no ramo informativo."""

    class _HapticFalso:
        def __init__(self) -> None:
            self.tocados: list[int] = []

        def play(self, waveform: int) -> int:
            self.tocados.append(waveform)
            return waveform

        def get_capabilities(self):
            return "00 01"

    class _DeviceFalso:
        def __init__(self, haptic) -> None:
            self.haptic = haptic

    def _rodar(self, **kwargs) -> list[int]:
        import argparse

        from logitune.cli import cmd_haptic

        haptic = self._HapticFalso()
        args = argparse.Namespace(waveform=None, all=False, delay=0.0)
        for key, value in kwargs.items():
            setattr(args, key, value)
        cmd_haptic(self._DeviceFalso(haptic), args)
        return haptic.tocados

    def test_all_toca_todos_os_padroes(self):
        # Regressão: --all sem número posicional caía no ramo que só imprime
        # as capacidades, e nada era tocado.
        assert self._rodar(all=True) == list(range(MIN_WAVEFORM, MAX_WAVEFORM + 1))

    def test_numero_toca_apenas_aquele_padrao(self):
        assert self._rodar(waveform=5) == [5]

    def test_sem_argumento_nenhum_nao_toca_nada(self):
        assert self._rodar() == []
