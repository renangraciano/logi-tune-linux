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


class TestCatalogo:
    def test_o_pot_existe(self):
        assert POT.is_file(), "rode xgettext para gerar po/logi-tune-linux.pot"

    @pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
    def test_nenhuma_mensagem_sem_traducao(self, po: Path):
        """Uma mensagem sem tradução vira inglês no meio da janela traduzida."""
        texto = po.read_text(encoding="utf-8")
        # O cabeçalho é o único msgid vazio, e o msgstr dele não é tradução.
        corpo = texto.split('\n\n', 1)[1] if '\n\n' in texto else texto
        vazias = re.findall(r'msgid "((?:[^"\\]|\\.)+)"\nmsgstr ""\n', corpo)
        assert vazias == [], f"sem tradução em {po.name}: {vazias[:5]}"

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
