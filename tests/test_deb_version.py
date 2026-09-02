# SPDX-License-Identifier: GPL-3.0-or-later
"""A versão do .deb tem que ordenar como a do Python.

O PEP 440 e o Debian discordam nas pré-releases, e discordam do jeito pior
possível: ``0.2.0rc1`` é *maior* que ``0.2.0`` para o ``dpkg``. Sem converter,
um candidato pareceria mais novo que a versão final e o apt se recusaria a
atualizar de um para o outro — sem erro, só sem atualizar.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from deb_version import to_debian  # noqa: E402

#: Em ordem crescente segundo o PEP 440. O Debian precisa concordar.
ORDEM = [
    "0.2.0.dev5",
    "0.2.0a3",
    "0.2.0b1",
    "0.2.0rc1",
    "0.2.0rc2",
    "0.2.0",
    "0.2.0.post1",
    "0.2.1",
    "1.0.0.dev1",
    "1.0.0rc1",
    "1.0.0",
]

dpkg = shutil.which("dpkg")
requer_dpkg = pytest.mark.skipif(dpkg is None, reason="precisa do dpkg")


class TestConversao:
    def test_uma_versao_final_nao_muda(self):
        assert to_debian("0.2.0") == "0.2.0"
        assert to_debian("1.2.3") == "1.2.3"

    def test_uma_pre_release_ganha_til(self):
        assert to_debian("0.2.0rc1") == "0.2.0~rc1"
        assert to_debian("0.2.0a3") == "0.2.0~a3"
        assert to_debian("1.0.0b2") == "1.0.0~b2"

    def test_um_dev_ganha_til_duplo(self):
        """O dpkg compara o que segue o til como texto, e "dev" > "a"."""
        assert to_debian("0.3.0.dev5") == "0.3.0~~dev5"

    def test_um_post_release_nao_ganha_til(self):
        """Um post vem depois da versão base, não antes."""
        assert to_debian("1.2.3.post1") == "1.2.3.post1"


@requer_dpkg
class TestOrdenacaoReal:
    """Perguntado ao próprio dpkg, que é quem decide na máquina de quem usa."""

    def _menor(self, a: str, b: str) -> bool:
        return (
            subprocess.run(
                [dpkg, "--compare-versions", a, "lt", b], check=False
            ).returncode
            == 0
        )

    @pytest.mark.parametrize(
        "menor,maior", list(zip(ORDEM, ORDEM[1:])), ids=lambda v: v
    )
    def test_a_ordem_do_pep440_sobrevive_a_conversao(self, menor, maior):
        a, b = to_debian(menor), to_debian(maior)
        assert self._menor(a, b), f"o dpkg não põe {a} antes de {b}"

    def test_sem_a_conversao_a_ordem_quebraria(self):
        """O motivo de este módulo existir, dito como teste."""
        assert not self._menor("0.2.0rc1", "0.2.0"), (
            "se o dpkg já ordenasse o formato do PEP 440, a conversão seria "
            "desnecessária"
        )
        assert self._menor(to_debian("0.2.0rc1"), to_debian("0.2.0"))
