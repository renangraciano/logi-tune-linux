# SPDX-License-Identifier: GPL-3.0-or-later
"""Gestos: os movimentos que um botão desviado pode reconhecer.

O MX Master 4 anuncia a capacidade ``RAW_XY`` em todos os seis botões
desviáveis, inclusive o do Actions Ring. Com o botão desviado o dispositivo
reporta o deslocamento enquanto ele está pressionado, o que permite distinguir
um toque de um arrasto e dar sete funções a um botão só — contra uma no app
oficial da Logitech, que é uma limitação do software deles, não do hardware.

Aqui ficam apenas os nomes dos gestos, que são o que a configuração referencia.
A máquina de estados que os reconhece a partir dos eventos de movimento é a
próxima etapa.
"""

from __future__ import annotations

import enum


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
