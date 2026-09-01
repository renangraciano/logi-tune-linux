# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do desenho do mouse e das coordenadas dos hotspots.

O desenho e as coordenadas são dois arquivos que precisam concordar. Nada no
programa reclama quando eles divergem: o marcador simplesmente aparece ao lado
do botão, e só quem olha percebe.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from logitune.hidpp.features.controls import CONTROL_LABELS, ControlID

ASSETS = Path(__file__).resolve().parent.parent / "logitune" / "ui" / "assets"
SVG = ASSETS / "mx-master-4.svg"

from logitune.ui.mouse_model import (
    MX_MASTER_4_HOTSPOTS,
    MX_MASTER_4_REGIONS as REGIOES,
)


@pytest.fixture(scope="module")
def hotspots() -> dict[int, tuple[float, float]]:
    # Vem de mouse_model, que é dado puro: assim estes testes rodam onde não
    # há GTK instalado, que é justamente o ambiente do CI.
    return MX_MASTER_4_HOTSPOTS


class TestDesenho:
    def test_o_svg_existe(self):
        assert SVG.is_file()

    def test_nao_ha_imagem_de_marca_no_repositorio(self):
        """O render oficial da Logitech não pode voltar.

        É material de marca, e um repositório sob GPL-3 precisa poder
        redistribuir tudo o que carrega.
        """
        binarios = [
            p.name
            for p in ASSETS.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        assert binarios == [], f"imagem de bitmap em assets: {binarios}"

    def test_cada_hotspot_tem_uma_regiao_desenhada(self, hotspots):
        """Coordenada sem desenho é um marcador sobre o nada."""
        svg = SVG.read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([^"]+)"', svg))
        faltando = {
            f"0x{cid:04X}": REGIOES[cid]
            for cid in hotspots
            if REGIOES.get(cid) not in ids
        }
        assert faltando == {}, f"sem região no SVG: {faltando}"

    def test_o_svg_nao_tem_regiao_sem_hotspot(self, hotspots):
        """Um botão desenhado e não clicável parece defeito."""
        sobrando = {c for c in REGIOES if c not in hotspots}
        assert sobrando == set(), f"regiões sem coordenada: {sobrando}"


class TestCoordenadas:
    def test_todo_hotspot_e_um_controle_conhecido(self, hotspots):
        conhecidos = {int(c) for c in ControlID}
        assert set(hotspots) <= conhecidos

    def test_todo_hotspot_tem_rotulo(self, hotspots):
        # Sem rótulo o popover e o tooltip ficariam com o CID cru.
        sem_rotulo = [f"0x{c:04X}" for c in hotspots if c not in CONTROL_LABELS]
        assert sem_rotulo == []

    @pytest.mark.parametrize("cid", sorted(REGIOES))
    def test_coordenada_dentro_da_imagem(self, hotspots, cid):
        x, y = hotspots[cid]
        assert 0 < x < 100 and 0 < y < 100

    def test_nenhum_par_de_hotspots_se_sobrepoe(self, hotspots):
        """Dois marcadores no mesmo ponto deixariam um deles inalcançável."""
        pontos = sorted(hotspots.items())
        for i, (cid_a, (xa, ya)) in enumerate(pontos):
            for cid_b, (xb, yb) in pontos[i + 1 :]:
                distancia = ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5
                assert distancia > 5, (
                    f"0x{cid_a:04X} e 0x{cid_b:04X} quase no mesmo ponto"
                )
