# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da tradução.

O que mais importa aqui não é se uma frase traduz, e sim se o catálogo
acompanha o código: uma mensagem nova que ninguém traduziu aparece em inglês
no meio de uma janela em português, e nada avisa.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from logitune import i18n

PO_DIR = Path(__file__).resolve().parent.parent / "po"
POT = PO_DIR / "logi-tune-linux.pot"
FONTES = Path(__file__).resolve().parent.parent / "logitune"


def _mensagens(caminho: Path) -> set[str]:
    """Os msgid de um .po ou .pot, já remontados quando quebrados em linhas."""
    texto = caminho.read_text(encoding="utf-8")
    encontrados: set[str] = set()
    atual: list[str] | None = None
    for linha in texto.split("\n"):
        if linha.startswith("msgid "):
            atual = [linha[len("msgid ") :]]
        elif atual is not None and linha.startswith('"'):
            atual.append(linha)
        elif atual is not None:
            partes = re.findall(r'"((?:[^"\\]|\\.)*)"', "\n".join(atual))
            msgid = "".join(partes)
            if msgid:
                encontrados.add(msgid)
            atual = None
    return encontrados


class TestFallback:
    def test_sem_catalogo_devolve_o_proprio_texto(self):
        """Uma instalação sem tradução funciona, só que em inglês."""
        assert i18n._("Buttons") in ("Buttons", "Botões")

    def test_traducao_de_idioma_inexistente_nao_estoura(self, monkeypatch):
        monkeypatch.setenv("LOGITUNE_LANG", "xx_YY")
        i18n.reload_language()
        try:
            assert i18n._("Buttons") == "Buttons"
        finally:
            monkeypatch.delenv("LOGITUNE_LANG", raising=False)
            i18n.reload_language()


def _entradas(po: Path) -> list[tuple[str, str]]:
    """Os pares ``(msgid, msgstr)`` de um .po, já juntando as continuações."""

    def juntar(linhas: list[str]) -> str:
        partes = [
            m.group(1)
            for m in (re.search(r'"((?:[^"\\]|\\.)*)"\s*$', ln) for ln in linhas)
            if m
        ]
        return "".join(partes)

    pares: list[tuple[str, str]] = []
    for bloco in po.read_text(encoding="utf-8").split("\n\n"):
        linhas = bloco.split("\n")
        i_id = next((i for i, l in enumerate(linhas) if l.startswith("msgid ")), None)
        i_str = next((i for i, l in enumerate(linhas) if l.startswith("msgstr ")), None)
        if i_id is None or i_str is None:
            continue
        pares.append((juntar(linhas[i_id:i_str]), juntar(linhas[i_str:])))
    return pares


class TestCatalogo:
    def test_o_pot_existe(self):
        assert POT.is_file(), "rode xgettext para gerar po/logi-tune-linux.pot"

    @pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
    def test_nenhuma_mensagem_sem_traducao(self, po: Path):
        """Uma mensagem sem tradução vira inglês no meio da janela traduzida.

        A entrada precisa ser lida inteira. O gettext quebra uma mensagem
        longa em ``msgstr ""`` seguido das linhas de continuação, e uma busca
        por ``msgstr ""`` sozinha acusa como vazia toda tradução comprida —
        que foi o que aconteceu na primeira versão deste teste.
        """
        vazias = [
            msgid
            for msgid, msgstr in _entradas(po)
            if msgid and not msgstr
        ]
        assert vazias == [], f"sem tradução em {po.name}: {vazias[:5]}"

    @pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
    def test_nenhuma_entrada_fuzzy(self, po: Path):
        """O gettext ignora entradas fuzzy, então elas valem como ausentes.

        O msgmerge marca assim tudo o que ele adivinhou por semelhança de
        texto, e o palpite costuma ser errado: numa fusão real ele traduziu
        "Calibration" como "Aplicativo". Sem esta checagem, o catálogo
        parecia completo e a janela saía metade em cada idioma.
        """
        fuzzy = [
            bloco.split("msgid ", 1)[1].split("\n")[0]
            for bloco in po.read_text(encoding="utf-8").split("\n\n")
            if "#, fuzzy" in bloco and "msgid " in bloco
        ]
        assert fuzzy == [], f"entradas fuzzy em {po.name}: {fuzzy[:5]}"

    @pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
    def test_o_po_cobre_o_pot(self, po: Path):
        faltando = sorted(_mensagens(POT) - _mensagens(po))
        assert faltando == [], f"{po.name} não tem: {faltando[:5]}"

    @pytest.mark.skipif(shutil.which("msgfmt") is None, reason="precisa do gettext")
    @pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
    def test_o_po_compila(self, po: Path, tmp_path: Path):
        subprocess.run(
            ["msgfmt", "--check", "-o", str(tmp_path / "saida.mo"), str(po)],
            check=True,
            capture_output=True,
        )


class TestCobertura:
    @pytest.mark.skipif(shutil.which("xgettext") is None, reason="precisa do gettext")
    def test_o_pot_esta_em_dia_com_o_codigo(self, tmp_path: Path):
        """Marcar uma string nova e esquecer de extrair deixa-a sem tradução.

        Este teste é o que impede o catálogo de envelhecer em silêncio.
        """
        gerado = tmp_path / "atual.pot"
        arquivos = sorted(str(p) for p in FONTES.rglob("*.py"))
        subprocess.run(
            ["xgettext", "--language=Python", "--keyword=_", "--from-code=UTF-8",
             "-o", str(gerado), *arquivos],
            check=True,
            capture_output=True,
        )
        novas = sorted(_mensagens(gerado) - _mensagens(POT))
        assert novas == [], (
            f"mensagens no código e fora do .pot: {novas[:5]} — "
            f"rode scripts/update-translations.sh"
        )
