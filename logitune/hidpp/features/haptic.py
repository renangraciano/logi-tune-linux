# SPDX-License-Identifier: GPL-3.0-or-later
"""Feature 0x19B0 — feedback háptico do MX Master 4.

A Logitech não documenta esta feature. O que está aqui veio de sondagem no
hardware (MX Master 4, firmware RBM 27.03.B0019) e bate com o que os projetos
``ncr/mx-master-4-haptic`` e ``talamar49/orbit-mouse`` identificaram de forma
independente: 0x19B0 é a feature háptica, com ``getCapabilities`` na função
0x00 e ``playWaveform`` na 0x04.

O que foi confirmado neste hardware:

- ``playWaveform`` aceita índices de 0 a 14 e ecoa o índice na resposta.
  Índices a partir de 15 são recusados com INVALID_ARGUMENT.
- ``getCapabilities`` devolve ``00 01 00 3c 08 00 7f ff``. O significado de
  cada campo ainda não está estabelecido, então guardamos os bytes crus em vez
  de fingir que sabemos decodificá-los.

O motor é o mesmo que a Logitech usa no Actions Ring, então esta é a peça que
faltava para reproduzir aquele recurso no Linux.
"""

from __future__ import annotations

from dataclasses import dataclass

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.features.base import Feature

_GET_CAPABILITIES = 0x00
_GET_STATUS = 0x01
_PLAY_WAVEFORM = 0x04

#: Menor e maior índice de waveform aceitos, medidos no MX Master 4.
MIN_WAVEFORM = 0
MAX_WAVEFORM = 14


@dataclass(frozen=True)
class HapticCapabilities:
    """O que o motor háptico anuncia.

    Os campos ainda não foram decodificados; ``raw`` preserva a resposta para
    quem quiser continuar a engenharia reversa.
    """

    raw: bytes

    def __str__(self) -> str:
        return self.raw[:8].hex(" ")


class Haptic(Feature):
    """Aciona o motor háptico do dispositivo."""

    FEATURE_ID = int(FeatureID.MX4_HAPTIC)

    def get_capabilities(self) -> HapticCapabilities:
        return HapticCapabilities(raw=bytes(self._call(_GET_CAPABILITIES)))

    def get_status(self) -> bytes:
        """Resposta crua da função 0x01, ainda não decodificada."""
        return bytes(self._call(_GET_STATUS))

    def play(self, waveform: int) -> int:
        """Toca um dos padrões de vibração gravados no firmware.

        Devolve o índice que o dispositivo confirmou ter tocado.
        """
        if not MIN_WAVEFORM <= waveform <= MAX_WAVEFORM:
            raise ValueError(
                f"waveform fora da faixa aceita ({MIN_WAVEFORM}–{MAX_WAVEFORM}): {waveform}"
            )
        response = self._call(_PLAY_WAVEFORM, bytes([waveform]))
        return response[0] if response else waveform
