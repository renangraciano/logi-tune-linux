# SPDX-License-Identifier: GPL-3.0-or-later
"""Compila os catálogos de tradução durante o build.

Existe só por isto: o pyproject.toml não sabe rodar um passo próprio de build,
e os arquivos ``.po`` precisam virar ``.mo`` antes de serem instalados.

Se o ``msgfmt`` não estiver na máquina, a compilação é pulada com um aviso em
vez de falhar. Uma instalação sem catálogos funciona igual, só que sempre em
inglês — o idioma do próprio código.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

DOMAIN = "logi-tune-linux"
PO_DIR = Path("po")
LOCALE_DIR = Path("logitune") / "locale"


class BuildWithTranslations(build_py):
    def run(self) -> None:
        self.compile_translations()
        super().run()

    def compile_translations(self) -> None:
        msgfmt = shutil.which("msgfmt")
        if msgfmt is None:
            self.warn(
                "msgfmt não encontrado (pacote gettext); "
                "a interface ficará só em inglês"
            )
            return

        for po in sorted(PO_DIR.glob("*.po")):
            destino = LOCALE_DIR / po.stem / "LC_MESSAGES"
            destino.mkdir(parents=True, exist_ok=True)
            alvo = destino / f"{DOMAIN}.mo"
            try:
                subprocess.run(
                    [msgfmt, "--check", "-o", str(alvo), str(po)], check=True
                )
            except subprocess.CalledProcessError as exc:
                # Um catálogo quebrado não pode impedir a instalação: sem ele
                # o idioma cai no inglês, o que ainda é um programa utilizável.
                self.warn(f"não consegui compilar {po}: {exc}")
            else:
                self.announce(f"compilado {alvo}", level=2)


setup(cmdclass={"build_py": BuildWithTranslations})
