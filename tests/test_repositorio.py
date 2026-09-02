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


def test_o_sdist_leva_os_catalogos():
    """Sem `po/` no sdist, o wheel sai sem tradução e sem erro.

    O ``python -m build`` monta o sdist e constrói o wheel *a partir dele*.
    Sem MANIFEST.in o sdist não leva os ``.po``, então o passo de compilação
    do setup.py não acha nenhum catálogo, não reclama, e o pacote instala em
    inglês. A checagem do workflow de release pega isso, mas só na hora de
    publicar.
    """
    manifesto = RAIZ / "MANIFEST.in"
    assert manifesto.is_file(), "MANIFEST.in sumiu; o sdist perde os catálogos"
    linhas = [
        l.strip()
        for l in manifesto.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]
    assert any("po/" in l and l.endswith(".po") for l in linhas), (
        f"MANIFEST.in não inclui po/*.po: {linhas}"
    )
