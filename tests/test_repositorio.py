# SPDX-License-Identifier: GPL-3.0-or-later
"""Guardas sobre o que o repositório carrega.

O pacote já teve o render oficial do MX Master 4 dentro dele. É material de
marca da Logitech, e um repositório sob GPL-3 precisa poder redistribuir tudo
o que carrega — tirar aquilo exigiu reescrever o histórico. Este teste existe
para a imagem não voltar sem que ninguém perceba.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PACOTE = RAIZ / "logitune"

#: Formatos de bitmap. Uma foto de produto chega como um destes; o que o
#: projeto desenha para si mesmo é SVG.
BITMAPS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}


def test_o_pacote_nao_carrega_bitmap():
    """Nada que o pacote instala é uma foto.

    O ícone do aplicativo é um SVG desenhado para o projeto e mora em
    ``packaging/``. Um bitmap dentro de ``logitune/`` seria material de fora,
    e é justamente o que não pode voltar.
    """
    encontrados = sorted(
        str(p.relative_to(RAIZ))
        for p in PACOTE.rglob("*")
        if p.is_file() and p.suffix.lower() in BITMAPS
    )
    assert encontrados == [], f"bitmap dentro do pacote: {encontrados}"
