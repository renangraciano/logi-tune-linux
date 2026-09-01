# SPDX-License-Identifier: GPL-3.0-or-later
"""Economia de energia: calar o motor háptico com a bateria baixa.

O motor é o que mais consome fora do sensor, e vibrar a cada gesto tem preço.
O Logi Options+ oferece desligá-lo quando a carga cai, e aqui não custa nada
de protocolo novo: a bateria já é lida pela feature 0x1004.

O cuidado que importa é não perguntar a carga a cada vibração. Um arrasto
dispara dois retornos hápticos — um ao cruzar o limiar, outro ao confirmar — e
uma ida ao dispositivo por vibração acrescentaria latência justamente no gesto
que precisa parecer instantâneo. Por isso a leitura fica em cache.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from logitune.hidpp.device import HidppError, NoResponse

if TYPE_CHECKING:  # pragma: no cover - só para anotação
    from logitune.device import LogitechDevice

logger = logging.getLogger(__name__)

#: Abaixo desta carga o motor cala, por padrão. Vinte por cento é onde o
#: sistema já começa a avisar, então é onde a pessoa espera economia.
DEFAULT_THRESHOLD = 20

#: Quanto uma leitura de bateria vale antes de valer a pena perguntar de novo.
#: A carga não muda em segundos, e o custo de errar por um minuto é vibrar uma
#: vez a mais ou a menos.
_CACHE_S = 60.0


class BatteryGate:
    """Decide se o motor háptico pode tocar agora.

    ``threshold`` em zero desliga a economia: o motor toca sempre, que é o
    comportamento de quem não pediu nada.
    """

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        self._lida_em: float | None = None
        self._permite = True

    def allows_haptics(self, device: LogitechDevice | None, now: float | None = None) -> bool:
        if self.threshold <= 0 or device is None or device.battery is None:
            return True

        now = time.monotonic() if now is None else now
        if self._lida_em is not None and now - self._lida_em < _CACHE_S:
            return self._permite

        self._lida_em = now
        try:
            status = device.battery.get_status()
        except (HidppError, NoResponse, OSError) as exc:
            # Sem saber a carga, tocar é a escolha certa: silenciar o mouse
            # por causa de uma leitura que falhou seria pior que gastar
            # bateria.
            logger.debug("não consegui ler a bateria: %s", exc)
            self._permite = True
            return True

        if status.is_charging:
            self._permite = True
        elif status.percentage is not None:
            self._permite = status.percentage > self.threshold
        else:
            # Sem percentual, resta o nível grosseiro que o dispositivo reporta.
            self._permite = not status.is_low

        if not self._permite:
            logger.info("motor háptico em silêncio: bateria baixa")
        return self._permite

    def invalidate(self) -> None:
        """Força uma nova leitura. Usado quando a configuração muda."""
        self._lida_em = None
