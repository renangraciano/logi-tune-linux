# SPDX-License-Identifier: GPL-3.0-or-later
"""Onde cada botão fica no desenho de cada modelo.

Isto é dado, não widget, e mora fora do módulo da interface de propósito: os
números precisam poder ser conferidos sem GTK instalado. O teste que garante
que cada coordenada tem uma região no SVG roda no CI justamente por isso.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Posições relativas (x%, y%) de cada Control ID no desenho do MX Master 4.
#: Convertidas em pixels em tempo de execução, a partir do tamanho real da
#: imagem renderizada.
#:
#: Os números saem do centro de cada região do SVG, num viewBox de 520×360 —
#: não de tentativa e erro sobre a imagem. Se o desenho mudar, recalcule a
#: partir dos elementos com o id correspondente em ``assets/mx-master-4.svg``.
MX_MASTER_4_HOTSPOTS: dict[int, tuple[float, float]] = {
    0x0052: (33.7, 32.8),   # wheel — clique do meio, na face de cima
    0x00C4: (52.5, 32.8),   # smartshift, atrás da roda
    0x0056: (18.5, 51.1),   # forward, o da frente na lateral
    0x0053: (30.0, 51.1),   # back
    0x00C3: (28.8, 68.9),   # gesture — o apoio do polegar inteiro
    0x01A0: (63.5, 67.0),   # actions-ring, o painel háptico atrás do apoio
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


@dataclass(frozen=True)
class ExtraHotspot:
    """Um ponto do desenho que não é um botão programável.

    A roda do polegar aparece no desenho e não tem Control ID: ela não é um
    botão, é uma roda. Sem uma entrada aqui ela ficava desenhada e sem
    marcador, e a única forma de configurá-la era achar a seção certa lá
    embaixo na página — o que na prática queria dizer que ela não tinha
    personalização.
    """

    #: Identificador interno, usado como chave no lugar do Control ID.
    key: str
    #: Posição relativa no desenho, em porcento.
    x: float
    y: float
    #: Id da região correspondente no SVG, para o teste conferir.
    region: str


#: Pontos do desenho do MX Master 4 que não são botões.
MX_MASTER_4_EXTRAS: tuple[ExtraHotspot, ...] = (
    # Centro do ``rect`` id="thumb-wheel" (x=196, y=160, 96x30) no viewBox
    # de 520x360.
    ExtraHotspot(key="thumbwheel", x=46.9, y=48.6, region="thumb-wheel"),
)


#: Registro de modelos → (nome do desenho, mapa de hotspots).
MODEL_REGISTRY: dict[str, tuple[str, dict[int, tuple[float, float]]]] = {
    "MX Master 4": ("mx-master-4.svg", MX_MASTER_4_HOTSPOTS),
}
