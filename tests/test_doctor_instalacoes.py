# SPDX-License-Identifier: GPL-3.0-or-later
"""Duas cópias instaladas ao mesmo tempo.

Desde que existe um ``.deb``, dá para acabar com o pipx em ``~/.local/bin`` e o
pacote em ``/usr/bin`` ao mesmo tempo. Nenhum dos dois reclama. O PATH e o
systemd escolhem o do pipx, então instalar o pacote por cima não muda nada —
e a pessoa fica olhando para uma versão que acha que trocou.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import shutil

from logitune import cli


@pytest.fixture
def instalacoes(tmp_path, monkeypatch):
    """Dois caminhos falsos, para não depender de escrever em /usr/bin."""
    pipx = tmp_path / "local" / "bin" / "logitune-daemon"
    pacote = tmp_path / "usr" / "bin" / "logitune-daemon"
    monkeypatch.setattr(cli, "_instalacoes", lambda: (pipx, pacote))
    return pipx, pacote


def _criar(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("#!/bin/sh\n")


def _which_falso(monkeypatch, vencedora: Path) -> None:
    """Responde só pelo ``logitune-daemon``.

    Um stub que responde a tudo faria o diagnóstico chamar o caminho falso
    como se fosse o ``systemctl``.
    """
    real = shutil.which

    def which(nome, *args, **kwargs):
        if nome == "logitune-daemon":
            return str(vencedora)
        if nome == "systemctl":
            return None
        return real(nome, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", which)


def _aviso(itens):
    return next((i for i in itens if i[1] == "installation"), None)


class TestInstalacoesConcorrentes:
    def test_uma_copia_nao_gera_aviso(self, instalacoes, monkeypatch):
        pipx, _pacote = instalacoes
        _criar(pipx)
        _which_falso(monkeypatch, pipx)
        assert _aviso(cli._diagnostico()) is None

    def test_nenhuma_copia_nao_gera_aviso(self, instalacoes):
        """Rodando do código-fonte não há nada instalado, e está tudo bem."""
        assert _aviso(cli._diagnostico()) is None

    def test_duas_copias_geram_aviso(self, instalacoes, monkeypatch):
        pipx, pacote = instalacoes
        _criar(pipx)
        _criar(pacote)
        _which_falso(monkeypatch, pipx)

        item = _aviso(cli._diagnostico())
        assert item is not None, "duas cópias instaladas e o doctor não avisa"
        ok, _titulo, detalhe = item
        assert ok is False
        # O aviso só serve se disser qual das duas está rodando.
        assert str(pipx) in detalhe
        assert str(pacote) in detalhe

    def test_o_aviso_diz_como_resolver(self, instalacoes, monkeypatch):
        pipx, pacote = instalacoes
        _criar(pipx)
        _criar(pacote)
        _which_falso(monkeypatch, pipx)

        _ok, _titulo, detalhe = _aviso(cli._diagnostico())
        assert "pipx uninstall" in detalhe
        assert "apt remove" in detalhe


def test_os_caminhos_padrao_sao_os_dois_que_o_projeto_instala():
    """Um caminho novo de instalação precisa entrar aqui, senão passa batido."""
    caminhos = [str(c) for c in cli._instalacoes()]
    assert any(c.endswith("/.local/bin/logitune-daemon") for c in caminhos), caminhos
    assert "/usr/bin/logitune-daemon" in caminhos
