#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Converte a versão do pacote Python para a forma que o Debian ordena.

Os dois esquemas discordam justamente nas pré-releases. O PEP 440 escreve
``0.2.0rc1``, e o ``dpkg`` compara isso como *maior* que ``0.2.0`` — o
candidato pareceria mais novo que a versão final, e o apt se recusaria a
atualizar de um para o outro. O Debian usa o til, que ordena antes de tudo:
``0.2.0~rc1``.

Mora fora do ``build-deb.sh`` para poder ser testado sem montar um pacote.
"""

from __future__ import annotations

import sys

from packaging.version import Version


def to_debian(versao: str) -> str:
    """A mesma versão, escrita como o Debian a ordena."""
    v = Version(versao)
    base = ".".join(str(n) for n in v.release)
    if v.epoch:
        base = f"{v.epoch}:{base}"

    sufixos = []
    # O til ordena antes de qualquer coisa, inclusive antes do fim da string.
    if v.pre is not None:
        rotulo, numero = v.pre
        sufixos.append(f"~{rotulo}{numero}")
    if v.dev is not None:
        # Til duplo: no PEP 440 um dev vem antes de um alpha, e o dpkg compara
        # o que segue o til como texto — "dev" > "a" pela letra. Com "~~dev" o
        # segundo til garante a ordem certa.
        sufixos.append(f"~~dev{v.dev}")
    # Um post-release vem *depois* da versão base, então não leva til.
    if v.post is not None:
        sufixos.append(f".post{v.post}")
    if v.local:
        sufixos.append("+" + v.local.replace("_", ".").replace("!", "."))

    return base + "".join(sufixos)


if __name__ == "__main__":
    print(to_debian(sys.argv[1]))
