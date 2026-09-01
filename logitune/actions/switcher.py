# SPDX-License-Identifier: GPL-3.0-or-later
"""Alternar aplicativos girando a roda do polegar.

É o recurso que dá nome ao App Switcher do Logi Options+, e o motivo de a roda
existir para muita gente. A mecânica não cabe no modelo comum de ação porque
guarda estado: a janela do alternador só fica aberta enquanto o Alt está
pressionado, então cada giro dá um Tab com o Alt ainda em baixo, e a escolha só
se confirma quando o Alt sobe.

Por isso a roda não é "duas ações, uma por sentido" neste modo. Soltar o Alt
entre um giro e outro fecharia a lista e recomeçaria do início a cada detent,
que é como o recurso deixa de funcionar.
"""

from __future__ import annotations

import logging
import time

from logitune.actions.backends import keys
from logitune.actions.spec import ActionError

logger = logging.getLogger(__name__)

#: Quanto tempo sem girar até confirmar a escolha, em milissegundos. Curto
#: demais confirma no meio de um giro lento; longo demais atrasa a janela que
#: se quis trazer para a frente.
DEFAULT_IDLE_MS = 800


class DetentCounter:
    """Junta as unidades de giro em detents.

    A roda não reporta detents: ela reporta na resolução desviada, que no
    MX Master 4 é seis vezes mais fina que a nativa. Um passo por unidade
    daria seis passos por clique da roda, e o alternador voaria pela lista.

    O resto é guardado entre eventos, senão um giro lento — que chega como
    uma sequência de deltas pequenos — nunca somaria um detent.
    """

    def __init__(self, units_per_detent: int = 1) -> None:
        self.units_per_detent = max(1, units_per_detent)
        self._resto = 0

    def feed(self, delta: int) -> int:
        """Quantos detents completos este giro fechou."""
        self._resto += delta
        detents = int(self._resto / self.units_per_detent)
        self._resto -= detents * self.units_per_detent
        return detents

    def reset(self) -> None:
        """Esquece o resto. Usado quando o giro termina."""
        self._resto = 0


class AppSwitcher:
    """Mantém o alternador aberto enquanto a roda gira.

    O tempo entra por parâmetro para os testes não dependerem do relógio.
    """

    def __init__(
        self,
        *,
        hold: str = "alt",
        forward: str = "tab",
        backward: str = "shift+tab",
        idle_ms: int = DEFAULT_IDLE_MS,
        keyboard=None,
    ) -> None:
        self._hold_text = hold
        self._forward = forward
        self._backward = backward
        self.idle_ms = idle_ms
        self._keyboard = keyboard
        self._hold_code: int | None = None
        #: Instante do último giro; ``None`` quando o alternador está fechado.
        self._last: float | None = None

    @property
    def active(self) -> bool:
        return self._last is not None

    def _kb(self):
        return self._keyboard if self._keyboard is not None else keys.keyboard()

    def step(self, delta: int, now: float | None = None) -> None:
        """Um detent da roda. ``delta`` positivo avança na lista."""
        if delta == 0:
            return
        now = time.monotonic() if now is None else now

        if not self.active:
            self._hold_code = keys.parse_shortcut(self._hold_text).key
            self._kb().press(self._hold_code)
        self._last = now

        atalho = self._forward if delta > 0 else self._backward
        self._kb().tap(keys.parse_shortcut(atalho))

    def tick(self, now: float | None = None) -> None:
        """Confirma a escolha quando a roda para."""
        if not self.active:
            return
        now = time.monotonic() if now is None else now
        if (now - self._last) * 1000 < self.idle_ms:
            return
        self.cancel()

    def next_deadline(self, now: float | None = None) -> float | None:
        """Quando o laço precisa acordar para confirmar, em segundos."""
        if not self.active:
            return None
        now = time.monotonic() if now is None else now
        return max(0.0, self.idle_ms / 1000 - (now - self._last))

    def cancel(self) -> None:
        """Solta a tecla de modo, confirmando o que estiver selecionado.

        Chamado também ao sair: uma tecla segurada sobrevive ao processo que a
        segurou, e um daemon que morre com o Alt em baixo deixa a sessão com o
        Alt em baixo.
        """
        if self._hold_code is not None:
            try:
                self._kb().release(self._hold_code)
            except ActionError as exc:  # pragma: no cover - depende do uinput
                logger.warning("não consegui soltar a tecla de modo: %s", exc)
        self._hold_code = None
        self._last = None
