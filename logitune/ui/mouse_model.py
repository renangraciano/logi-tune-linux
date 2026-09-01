# SPDX-License-Identifier: GPL-3.0-or-later
"""Onde cada botão fica no desenho de cada modelo.

Isto é dado, não widget, e mora fora do módulo da interface de propósito: os
números precisam poder ser conferidos sem GTK instalado. O teste que garante
que cada coordenada tem uma região no SVG roda no CI justamente por isso.
"""

from __future__ import annotations

#: Posições relativas (x%, y%) de cada Control ID no desenho do MX Master 4.
#: Convertidas em pixels em tempo de execução, a partir do tamanho real da
#: imagem renderizada.
#:
#: Os números saem do centro de cada região do SVG, num viewBox de 420×620 —
#: não de tentativa e erro sobre a imagem. Se o desenho mudar, recalcule a
#: partir dos elementos com o id correspondente em ``assets/mx-master-4.svg``.
MX_MASTER_4_HOTSPOTS: dict[int, tuple[float, float]] = {
    0x0052: (62.4, 23.5),   # wheel — clique do meio
    0x00C4: (62.6, 48.1),   # smartshift
    0x0053: (28.1, 50.5),   # back
    0x0056: (28.1, 58.9),   # forward
    0x00C3: (25.2, 68.4),   # gesture
    0x01A0: (25.2, 79.1),   # actions-ring
}

#: O id da região no SVG correspondente a cada botão. Serve para conferir o
#: desenho contra as coordenadas.
MX_MASTER_4_REGIONS: dict[int, str] = {
    0x0052: "wheel",
    0x00C4: "smartshift",
    0x0053: "back",
    0x0056: "forward",
    0x00C3: "gesture",
    0x01A0: "actions-ring",
}

#: Registro de modelos → (nome do desenho, mapa de hotspots).
MODEL_REGISTRY: dict[str, tuple[str, dict[int, tuple[float, float]]]] = {
    "MX Master 4": ("mx-master-4.svg", MX_MASTER_4_HOTSPOTS),
}
