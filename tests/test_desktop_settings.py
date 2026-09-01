# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes dos ajustes de ponteiro que pertencem à sessão.

Estes não tocam no dconf de verdade. O dconf **lê** de
``$XDG_CONFIG_HOME/dconf/user`` mas **escreve** por D-Bus no banco da sessão,
então redirecionar a variável isola a leitura e não a escrita — um teste que
gravasse de verdade mudaria os ajustes de quem o rodou, e foi exatamente o que
aconteceu durante o desenvolvimento.
"""

from __future__ import annotations

import pytest

from logitune.ui.desktop import ACCEL_PROFILES, SCHEMA, DesktopMouseSettings


class SettingsFalso:
    def __init__(self, valores):
        self.valores = dict(valores)
        self.escritas = []

    def get_boolean(self, chave):
        return self.valores[chave]

    def get_double(self, chave):
        return self.valores[chave]

    def get_string(self, chave):
        return self.valores[chave]

    def set_boolean(self, chave, valor):
        self.valores[chave] = valor
        self.escritas.append((chave, valor))

    def set_double(self, chave, valor):
        self.valores[chave] = valor
        self.escritas.append((chave, valor))

    def set_string(self, chave, valor):
        self.valores[chave] = valor
        self.escritas.append((chave, valor))


@pytest.fixture
def ajustes(monkeypatch):
    falso = SettingsFalso(
        {"left-handed": False, "speed": 0.5, "accel-profile": "default"}
    )
    objeto = DesktopMouseSettings.__new__(DesktopMouseSettings)
    objeto._settings = falso
    # O sync real fala com o D-Bus da sessão; aqui não há o que sincronizar.
    monkeypatch.setattr(objeto, "_write", lambda escrever: escrever(falso))
    return objeto, falso


class TestLeitura:
    def test_le_os_tres_valores(self, ajustes):
        objeto, _falso = ajustes
        assert objeto.left_handed is False
        assert objeto.speed == 0.5
        assert objeto.accel_profile == "default"


class TestEscrita:
    def test_troca_a_mao(self, ajustes):
        objeto, falso = ajustes
        objeto.left_handed = True
        assert falso.valores["left-handed"] is True

    def test_velocidade_e_limitada_a_faixa(self, ajustes):
        """O esquema aceita -1,0 a 1,0; passar disso é erro do chamador."""
        objeto, falso = ajustes
        objeto.speed = 5.0
        assert falso.valores["speed"] == 1.0
        objeto.speed = -5.0
        assert falso.valores["speed"] == -1.0

    def test_perfil_valido(self, ajustes):
        objeto, falso = ajustes
        objeto.accel_profile = "flat"
        assert falso.valores["accel-profile"] == "flat"

    def test_perfil_invalido_e_ignorado(self, ajustes):
        """Um valor fora do enum faria o gsettings estourar em runtime."""
        objeto, falso = ajustes
        objeto.accel_profile = "turbo"
        assert falso.valores["accel-profile"] == "default"
        assert falso.escritas == []

    def test_todos_os_perfis_do_rotulo_sao_aceitos(self, ajustes):
        objeto, falso = ajustes
        for valor, _rotulo in ACCEL_PROFILES:
            objeto.accel_profile = valor
            assert falso.valores["accel-profile"] == valor


class TestAusencia:
    """Fora do GNOME o esquema não existe, e isso não é erro — é um ambiente
    onde estes controles não têm o que ajustar."""

    @pytest.fixture
    def sem_esquema(self) -> DesktopMouseSettings:
        objeto = DesktopMouseSettings.__new__(DesktopMouseSettings)
        objeto._settings = None
        return objeto

    def test_available_e_falso(self, sem_esquema):
        assert sem_esquema.available is False

    @pytest.mark.parametrize("atributo", ["left_handed", "speed", "accel_profile"])
    def test_ler_erra_alto(self, sem_esquema, atributo):
        """Devolver um valor plausível faria a interface mostrar um ajuste que
        ninguém escolheu — e gravá-lo de volta ao primeiro toque no controle."""
        with pytest.raises(RuntimeError, match=SCHEMA):
            getattr(sem_esquema, atributo)
