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

    def test_a_tag_svg_aparece_nos_primeiros_bytes(self):
        """O GTK reconhece o formato farejando o começo do arquivo.

        Um comentário de licença entre a declaração XML e a tag ``<svg>``
        empurra a tag para fora dessa janela, e aí o desenho não carrega —
        sem erro visível, só um espaço vazio na janela. Foi o que aconteceu:
        um cabeçalho de 13 linhas pôs a tag no byte 640. O comentário mora
        dentro do elemento por isso.
        """
        inicio = SVG.read_bytes()[:256]
        assert b"<svg" in inicio, (
            "a tag <svg> não está nos primeiros 256 bytes; "
            "mova qualquer comentário para dentro do elemento"
        )

    def test_o_desenho_carrega_no_gtk(self):
        """O teste acima explica o porquê; este confere o fato."""
        gdkpixbuf = pytest.importorskip(
            "gi.repository.GdkPixbuf", reason="GdkPixbuf não está neste ambiente"
        )
        pixbuf = gdkpixbuf.Pixbuf.new_from_file(str(SVG))
        assert pixbuf.get_width() > 0 and pixbuf.get_height() > 0

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


# -- Posicionamento dos marcadores ----------------------------------------
#
# Estes precisam de GTK de verdade: o defeito que motivou o teste não aparece
# em nada que se possa ler no código. O ``get-child-position`` do Gtk.Overlay
# entrega o retângulo a preencher como argumento, e devolver um retângulo novo
# não tem efeito — o overlay cai no posicionamento padrão e dá a cada marcador
# a área inteira. Como o marcador é um círculo branco, o desenho some atrás
# dele, sem erro nenhum no console.

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401

    _tem_gtk = True
except (ImportError, ValueError):  # pragma: no cover - depende do ambiente
    _tem_gtk = False

requer_gtk = pytest.mark.skipif(
    not _tem_gtk, reason="precisa do PyGObject com GTK4 e libadwaita"
)


@requer_gtk
class TestMarcadores:
    @pytest.fixture
    def vista(self):
        import types

        from gi.repository import GLib, Gtk

        from logitune.hidpp.features.controls import CONTROL_LABELS
        from logitune.ui.mouse_view import MouseHotspotView

        Gtk.init()
        controles = [
            types.SimpleNamespace(
                control_id=cid, label=CONTROL_LABELS[cid], is_divertable=True
            )
            for cid in MX_MASTER_4_HOTSPOTS
        ]
        vista = MouseHotspotView(
            controls=controles,
            model_name="MX Master 4",
            binding_for=lambda cid: (None, False),
            describe_binding=lambda b: "padrão",
            on_configure=lambda c: None,
            on_clear=lambda c: None,
        )
        janela = Gtk.Window(default_width=520, default_height=620)
        janela.set_child(vista)
        janela.present()

        # A alocação só acontece com o laço principal rodando: iterar os
        # eventos pendentes na mão não basta, a janela precisa ser mapeada.
        laco = GLib.MainLoop()
        tentativas = [0]

        def pronto() -> bool:
            tentativas[0] += 1
            if vista.get_width() > 0 or tentativas[0] > 60:
                laco.quit()
                return False
            return True

        GLib.timeout_add(50, pronto)
        GLib.timeout_add(5000, lambda: (laco.quit(), False)[1])
        laco.run()

        yield vista
        janela.destroy()

    def test_a_vista_esta_disponivel(self, vista):
        assert vista.available
        assert vista.get_width() > 0, "a vista nunca foi alocada"

    def test_nenhum_marcador_cobre_o_desenho(self, vista):
        """Um marcador do tamanho do overlay esconde o mouse inteiro."""
        largura = vista._overlay.get_width()
        altura = vista._overlay.get_height()
        inchados = {
            f"0x{cid:04X}": (btn.get_width(), btn.get_height())
            for cid, btn in vista._hotspot_buttons.items()
            if btn.get_width() >= largura or btn.get_height() >= altura
        }
        assert inchados == {}, (
            f"marcador ocupando o overlay ({largura}x{altura}): {inchados} — "
            "o get-child-position precisa preencher o retângulo recebido"
        )

    def test_cada_marcador_fica_sobre_o_seu_botao(self, vista):
        """A posição de cada marcador tem que bater com o percentual dele.

        É esta a verificação que pega o retorno em tupla: sem o retângulo
        preenchido, o overlay posiciona todos os marcadores pelo alinhamento
        padrão e eles acabam empilhados no mesmo canto, longe do botão que
        deveriam apontar.
        """
        area = vista._image_area()
        assert area is not None, "a imagem não foi medida"
        offset_x, offset_y, largura, altura = area

        erros = {}
        for cid, btn in vista._hotspot_buttons.items():
            ok, limites = btn.compute_bounds(vista._overlay)
            assert ok, f"0x{cid:04X} não tem posição no overlay"
            x_pct, y_pct = MX_MASTER_4_HOTSPOTS[cid]
            centro_x = limites.origin.x + limites.size.width / 2
            centro_y = limites.origin.y + limites.size.height / 2
            esperado_x = offset_x + x_pct / 100.0 * largura
            esperado_y = offset_y + y_pct / 100.0 * altura
            if abs(centro_x - esperado_x) > 3 or abs(centro_y - esperado_y) > 3:
                erros[f"0x{cid:04X}"] = (
                    (round(centro_x), round(centro_y)),
                    (round(esperado_x), round(esperado_y)),
                )
        assert erros == {}, f"marcador fora do lugar (obtido, esperado): {erros}"

    def test_os_marcadores_nao_se_empilham(self, vista):
        """Todos no mesmo ponto é o sintoma de posicionamento ignorado."""
        pontos = set()
        for btn in vista._hotspot_buttons.values():
            ok, limites = btn.compute_bounds(vista._overlay)
            assert ok
            pontos.add((round(limites.origin.x), round(limites.origin.y)))
        assert len(pontos) == len(vista._hotspot_buttons), (
            f"marcadores empilhados: {len(pontos)} posições para "
            f"{len(vista._hotspot_buttons)} botões"
        )
