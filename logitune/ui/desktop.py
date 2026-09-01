# SPDX-License-Identifier: GPL-3.0-or-later
"""Ajustes de ponteiro que são do sistema, não do mouse.

O Logi Options+ mistura os dois na mesma tela, e há razão: quem quer "o
ponteiro mais rápido" não distingue se isso se resolve no sensor ou no
compositor. Mas a diferença é real e vale dizer na interface.

O DPI vive no mouse: viaja com ele para outro computador e vale para o
dispositivo sozinho. O que está aqui vive na sessão: aplica-se a todo
apontador, inclusive ao touchpad, e continua valendo depois que o mouse for
desconectado — ou desinstalado este programa.

Por isso estes ajustes não entram nos perfis por aplicação. Um perfil que
trocasse a mão dominante ao abrir o navegador seria absurdo.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SCHEMA = "org.gnome.desktop.peripherals.mouse"

#: Os perfis de aceleração que o esquema aceita, com o rótulo que a interface
#: mostra. O valor cru é o que vai para o gsettings.
ACCEL_PROFILES = (
    ("default", "Follow the system"),
    ("flat", "No acceleration"),
    ("adaptive", "Accelerate with speed"),
)


def _gio():
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    return Gio


class DesktopMouseSettings:
    """Lê e grava as chaves de ponteiro da sessão.

    Fora do GNOME o esquema não existe. Isso não é erro: é um ambiente onde
    estes controles não têm o que ajustar, e a interface os omite em vez de
    mostrar algo que não funciona.
    """

    def __init__(self) -> None:
        self._settings = None
        try:
            Gio = _gio()
            fonte = Gio.SettingsSchemaSource.get_default()
            if fonte is not None and fonte.lookup(SCHEMA, True) is not None:
                self._settings = Gio.Settings.new(SCHEMA)
        except Exception as exc:  # noqa: BLE001 - ausência não pode derrubar a janela
            logger.debug("sem o esquema %s: %s", SCHEMA, exc)

    @property
    def available(self) -> bool:
        return self._settings is not None

    def _require(self):
        """Erra alto em vez de devolver um valor plausível e errado.

        Um getter que devolve 0.0 quando não há esquema faria a interface
        mostrar uma velocidade que ninguém escolheu — e, pior, gravá-la de
        volta ao primeiro toque no controle.
        """
        if self._settings is None:
            raise RuntimeError(
                f"o esquema {SCHEMA} não está presente; confira available antes de ler"
            )
        return self._settings

    def _write(self, escrever) -> None:
        """Grava e força o flush.

        O GSettings escreve por D-Bus de forma assíncrona. Num processo que
        sai logo depois — um teste, um script — a escrita se perde sem aviso.
        """
        escrever(self._require())
        _gio().Settings.sync()

    # -- mão dominante --------------------------------------------------

    @property
    def left_handed(self) -> bool:
        return bool(self._require().get_boolean("left-handed"))

    @left_handed.setter
    def left_handed(self, value: bool) -> None:
        self._write(lambda s: s.set_boolean("left-handed", bool(value)))

    # -- velocidade -----------------------------------------------------

    @property
    def speed(self) -> float:
        """Velocidade do ponteiro, de -1,0 a 1,0. Zero é o meio da faixa."""
        return float(self._require().get_double("speed"))

    @speed.setter
    def speed(self, value: float) -> None:
        limitado = max(-1.0, min(1.0, float(value)))
        self._write(lambda s: s.set_double("speed", limitado))

    # -- aceleração -----------------------------------------------------

    @property
    def accel_profile(self) -> str:
        return self._require().get_string("accel-profile")

    @accel_profile.setter
    def accel_profile(self, value: str) -> None:
        if value not in {v for v, _r in ACCEL_PROFILES}:
            logger.warning("perfil de aceleração desconhecido ignorado: %r", value)
            return
        self._write(lambda s: s.set_string("accel-profile", value))
