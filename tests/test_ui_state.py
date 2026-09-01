# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do estado compartilhado entre interface e daemon."""

from __future__ import annotations

from logitune.config import Config, Settings
from logitune.ui.state import ConfigStore


class TestConfigStore:
    def test_grava_e_le_de_volta(self, tmp_path, monkeypatch):
        store = ConfigStore(tmp_path / "config.json")
        monkeypatch.setattr(store, "notify_daemon", lambda: True)

        store.update(lambda c: c.default.bindings.__setitem__("0x53", "browser.back"))
        assert store.load().default.bindings == {"0x53": "browser.back"}

    def test_sempre_rele_antes_de_alterar(self, tmp_path, monkeypatch):
        """Guardar uma cópia apagaria o que foi editado à mão no intervalo."""
        destino = tmp_path / "config.json"
        store = ConfigStore(destino)
        monkeypatch.setattr(store, "notify_daemon", lambda: True)

        store.update(lambda c: c.default.bindings.__setitem__("0x53", "browser.back"))

        # Alguém edita o arquivo por fora, sem passar pela interface.
        editado = Config(default=Settings(bindings={"0x53": "browser.back", "0x56": "edit.copy"}))
        editado.save(destino)

        store.update(lambda c: c.default.bindings.__setitem__("0xC4", "media.next"))
        assert store.load().default.bindings == {
            "0x53": "browser.back",
            "0x56": "edit.copy",
            "0xC4": "media.next",
        }

    def test_avisa_o_daemon_a_cada_escrita(self, tmp_path, monkeypatch):
        # Sem o aviso a interface mentiria: o daemon só releria ao reiniciar.
        avisos = []
        store = ConfigStore(tmp_path / "config.json")
        monkeypatch.setattr(store, "notify_daemon", lambda: avisos.append(1) or True)

        store.update(lambda c: None)
        store.update(lambda c: None)
        assert len(avisos) == 2

    def test_daemon_parado_nao_e_erro(self, tmp_path, monkeypatch):
        """A configuração já está em disco e vale quando ele subir."""
        import subprocess

        store = ConfigStore(tmp_path / "config.json")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"not loaded"),
        )
        store.update(lambda c: c.default.bindings.__setitem__("0x53", "browser.back"))
        assert store.load().default.bindings == {"0x53": "browser.back"}

    def test_permissoes_sao_preservadas(self, tmp_path, monkeypatch):
        """O arquivo define comandos que o daemon executa: 0600 não é detalhe."""
        destino = tmp_path / "config.json"
        store = ConfigStore(destino)
        monkeypatch.setattr(store, "notify_daemon", lambda: True)
        store.update(lambda c: c.default.bindings.__setitem__("0x53", "browser.back"))
        assert destino.stat().st_mode & 0o777 == 0o600


class TestNomesComMarkup:
    """Os títulos das linhas são interpretados como markup Pango.

    Um "&" num nome de aplicativo — "Software & Updates" existe no Ubuntu —
    derruba a linha inteira, e o GTK só reclama no terminal.
    """

    def test_nomes_com_e_comercial_sao_escapados(self):
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib

        assert GLib.markup_escape_text("Software & Updates") == "Software &amp; Updates"

    def test_o_seletor_escapa_o_nome(self, monkeypatch):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from logitune.actions.backends.launch import AppEntry
        from logitune.ui import app_picker

        monkeypatch.setattr(
            app_picker,
            "list_apps",
            lambda: [AppEntry(desktop_id="x.desktop", name="Software & Updates", wm_class="x")],
        )
        picker = app_picker.AppPicker(lambda app: None)
        titulos = [row.get_title() for row, _ in picker._rows]
        assert titulos == ["Software &amp; Updates"]
