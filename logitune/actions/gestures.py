# SPDX-License-Identifier: GPL-3.0-or-later
"""Gestos: os movimentos que um botão desviado pode reconhecer.

O MX Master 4 anuncia a capacidade ``RAW_XY`` em todos os seis botões
desviáveis, inclusive o do Actions Ring. Com o botão desviado o dispositivo
reporta o deslocamento enquanto ele está pressionado, o que permite distinguir
um toque de um arrasto e dar sete funções a um botão só — contra uma no app
oficial da Logitech, que é uma limitação do software deles, não do hardware.

Os limiares abaixo não são chute: saíram de 25 pressionadas medidas com
``watch --raw-xy`` num MX Master 4 (``RBM 27.03.B0019``, receptor Bolt). Vale
registrar o que a medição mostrou, porque contraria o que se esperaria.

**O sensor não reporta ruído com o botão parado.** Doze das dezessete
pressionadas sem intenção de mover não geraram amostra nenhuma. Não é preciso
filtrar por velocidade.

**Mas um clique comum pode deslocar bastante.** Um dos cliques mediu 98
unidades — a mão empurra o mouse ao apertar. O limiar de 50 que parecia
razoável no papel transformaria esse clique num arrasto para a esquerda.

**A contagem de amostras separa melhor que a distância.** Todo movimento
acidental veio em zero ou uma amostra; todo arrasto real veio em 29 a 72. Um
esbarrão é um solavanco só, um arrasto é um fluxo. Por isso exigimos as duas
coisas: distância *e* continuidade.

Medições, para quem for recalibrar:

===============  =========================  ==================
                 acidental (17 amostras)    arrasto (8)
===============  =========================  ==================
deslocamento     0 a 98 unidades            723 a 1551
amostras         0 ou 1                     29 a 72
duração          75 a 173 ms (um de 630)    562 a 2198 ms
===============  =========================  ==================
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Callable, Iterable


class Gesture(enum.Enum):
    """Os gestos que um botão pode distinguir."""

    TAP = "tap"
    DOUBLE_TAP = "double_tap"
    HOLD = "hold"
    DRAG_UP = "drag_up"
    DRAG_DOWN = "drag_down"
    DRAG_LEFT = "drag_left"
    DRAG_RIGHT = "drag_right"

    @property
    def label(self) -> str:
        return {
            Gesture.TAP: "toque",
            Gesture.DOUBLE_TAP: "toque duplo",
            Gesture.HOLD: "segurar",
            Gesture.DRAG_UP: "arrastar para cima",
            Gesture.DRAG_DOWN: "arrastar para baixo",
            Gesture.DRAG_LEFT: "arrastar para a esquerda",
            Gesture.DRAG_RIGHT: "arrastar para a direita",
        }[self]

    @property
    def is_drag(self) -> bool:
        return self.value.startswith("drag_")


#: Os nomes válidos em JSON, para reconhecer um mapa de gestos na configuração.
GESTURE_NAMES = frozenset(g.value for g in Gesture)

#: Qual gesto corresponde a cada direção dominante.
_DRAG_BY_AXIS = {
    ("x", True): Gesture.DRAG_RIGHT,
    ("x", False): Gesture.DRAG_LEFT,
    ("y", True): Gesture.DRAG_DOWN,
    ("y", False): Gesture.DRAG_UP,
}


class Feedback(enum.Enum):
    """Momentos que merecem um retorno háptico.

    É o que torna o gesto usável sem olhar para a tela: você sente que a
    direção foi reconhecida antes mesmo de soltar o botão.
    """

    #: O deslocamento cruzou o limiar: daqui em diante isto é um arrasto.
    CROSSED = "crossed"
    #: O gesto foi reconhecido e a ação vai disparar.
    CONFIRMED = "confirmed"


@dataclass(frozen=True)
class GestureThresholds:
    """Os números que separam um gesto do outro.

    Os padrões vêm da medição descrita no topo do módulo. Todos são
    configuráveis porque dependem da mão: quem tem pulso mais firme pode
    baixar ``drag_units``, quem esbarra no mouse ao clicar precisa subir.
    """

    #: Deslocamento acumulado que caracteriza um arrasto. Duas vezes o pior
    #: acidente medido, e ainda três vezes e meia abaixo do menor arrasto real.
    drag_units: int = 200
    #: Amostras mínimas para aceitar um arrasto. Um esbarrão chega em uma só.
    drag_samples: int = 3
    #: A partir daqui, segurar parado é o gesto "hold".
    hold_ms: int = 500
    #: Janela para o segundo toque. O padrão é o do duplo clique do GNOME.
    double_tap_ms: int = 400

    def __post_init__(self) -> None:
        if self.drag_units <= 0 or self.hold_ms <= 0 or self.double_tap_ms <= 0:
            raise ValueError("os limiares de gesto precisam ser positivos")


@dataclass
class _Press:
    """Uma pressionada em andamento."""

    cid: int
    started: float
    dx: int = 0
    dy: int = 0
    samples: int = 0
    #: Assim que um gesto se decide, a pressionada para de mudar de ideia.
    committed: Gesture | None = None

    def accumulate(self, dx: int, dy: int) -> None:
        self.dx += dx
        self.dy += dy
        self.samples += 1

    def elapsed_ms(self, now: float) -> float:
        return (now - self.started) * 1000

    @property
    def distance_squared(self) -> int:
        return self.dx * self.dx + self.dy * self.dy

    def drag_gesture(self) -> Gesture:
        """A direção do arrasto, pelo eixo que mais andou."""
        if abs(self.dx) >= abs(self.dy):
            return _DRAG_BY_AXIS[("x", self.dx > 0)]
        return _DRAG_BY_AXIS[("y", self.dy > 0)]


@dataclass(frozen=True)
class Recognized:
    """Um gesto reconhecido, pronto para virar ação."""

    cid: int
    gesture: Gesture


class GestureRecognizer:
    """Transforma pressionar, mover e soltar em gestos.

    O tempo entra sempre por parâmetro para que os testes não dependam do
    relógio; quem chama de verdade pode omitir.
    """

    def __init__(
        self,
        thresholds: GestureThresholds | None = None,
        *,
        bound: Callable[[int], Iterable[Gesture]] | None = None,
        feedback: Callable[[Feedback, Gesture], None] | None = None,
    ) -> None:
        self.thresholds = thresholds or GestureThresholds()
        #: Quais gestos aquele botão tem configurados. Saber disso deixa o
        #: toque disparar na hora quando não há duplo toque para esperar.
        self._bound = bound or (lambda cid: Gesture)
        self._feedback = feedback
        self._active: dict[int, _Press] = {}
        #: Toques aguardando para ver se viram duplo toque: cid → instante.
        self._pending_tap: dict[int, float] = {}

    # -- entradas ------------------------------------------------------

    def press(self, cid: int, now: float | None = None) -> list[Recognized]:
        now = time.monotonic() if now is None else now
        self._active[cid] = _Press(cid=cid, started=now)
        return []

    def movement(self, dx: int, dy: int, now: float | None = None) -> list[Recognized]:
        """Distribui o deslocamento entre os botões pressionados.

        O evento de movimento não diz de qual botão ele é — ele só existe
        enquanto algum está preso, então vale para todos os que estão.
        """
        now = time.monotonic() if now is None else now
        for press in self._active.values():
            if press.committed is not None:
                continue
            press.accumulate(dx, dy)
            if self._is_drag(press):
                # Cruzou: a partir daqui é arrasto, e um retorno háptico avisa
                # qual direção foi reconhecida antes de soltar.
                press.committed = press.drag_gesture()
                self._notify(Feedback.CROSSED, press.committed)
        return []

    def release(self, cid: int, now: float | None = None) -> list[Recognized]:
        now = time.monotonic() if now is None else now
        press = self._active.pop(cid, None)
        if press is None:
            return []

        if press.committed is Gesture.HOLD:
            # O hold já disparou enquanto o botão estava preso.
            return []
        if press.committed is not None:
            return self._emit(cid, press.committed)
        if self._is_drag(press):
            return self._emit(cid, press.drag_gesture())
        if press.elapsed_ms(now) >= self.thresholds.hold_ms:
            return self._emit(cid, Gesture.HOLD)

        return self._tap(cid, now)

    def tick(self, now: float | None = None) -> list[Recognized]:
        """Dispara o que depende só da passagem do tempo.

        Sem isto, segurar o botão não faria nada até soltar, e o toque simples
        ficaria preso esperando um segundo toque que não veio.
        """
        now = time.monotonic() if now is None else now
        saida: list[Recognized] = []

        for cid, press in self._active.items():
            if press.committed is None and press.elapsed_ms(now) >= self.thresholds.hold_ms:
                press.committed = Gesture.HOLD
                saida.extend(self._emit(cid, Gesture.HOLD))

        for cid, quando in list(self._pending_tap.items()):
            if (now - quando) * 1000 >= self.thresholds.double_tap_ms:
                del self._pending_tap[cid]
                saida.extend(self._emit(cid, Gesture.TAP))

        return saida

    def next_deadline(self, now: float | None = None) -> float | None:
        """Quando o laço precisa acordar, em segundos, ou ``None``.

        O daemon dorme em ``select`` até um descritor falar. Um gesto que
        depende de tempo — o hold, a janela do duplo toque — nunca chegaria na
        hora se ninguém encurtasse essa espera.
        """
        now = time.monotonic() if now is None else now
        prazos: list[float] = []

        for press in self._active.values():
            if press.committed is None:
                restante = self.thresholds.hold_ms / 1000 - (now - press.started)
                prazos.append(max(0.0, restante))
        for quando in self._pending_tap.values():
            restante = self.thresholds.double_tap_ms / 1000 - (now - quando)
            prazos.append(max(0.0, restante))

        return min(prazos) if prazos else None

    def reset(self) -> None:
        """Esquece o que estava em andamento (troca de perfil, por exemplo)."""
        self._active.clear()
        self._pending_tap.clear()

    # -- internos ------------------------------------------------------

    def _is_drag(self, press: _Press) -> bool:
        """Distância *e* continuidade.

        A distância sozinha aceitaria o esbarrão de 98 unidades que a medição
        pegou; as amostras sozinhas aceitariam um tremor longo e curto.
        """
        limiar = self.thresholds.drag_units
        return (
            press.distance_squared >= limiar * limiar
            and press.samples >= self.thresholds.drag_samples
        )

    def _tap(self, cid: int, now: float) -> list[Recognized]:
        """Resolve um toque, adiando só quando há duplo toque configurado."""
        anterior = self._pending_tap.pop(cid, None)
        if anterior is not None and (now - anterior) * 1000 < self.thresholds.double_tap_ms:
            return self._emit(cid, Gesture.DOUBLE_TAP)

        if Gesture.DOUBLE_TAP not in self._bound(cid):
            # Nada a esperar: quem não configurou duplo toque não deve pagar
            # a latência da janela.
            return self._emit(cid, Gesture.TAP)

        self._pending_tap[cid] = now
        return []

    def _emit(self, cid: int, gesture: Gesture) -> list[Recognized]:
        self._notify(Feedback.CONFIRMED, gesture)
        return [Recognized(cid=cid, gesture=gesture)]

    def _notify(self, kind: Feedback, gesture: Gesture) -> None:
        if self._feedback is None:
            return
        try:
            self._feedback(kind, gesture)
        except Exception:  # noqa: BLE001 - vibrar é acessório, nunca fatal
            pass
