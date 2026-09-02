# SPDX-License-Identifier: GPL-3.0-or-later
"""Estado compartilhado entre a interface e o daemon.

O ``config.json`` é a fonte da verdade, inclusive para o que parece estado do
mouse. O DPI e o modo da roda ficam gravados no dispositivo, sim, mas o daemon
reaplica o perfil a cada troca de janela — então um valor que a interface
escrevesse direto no mouse, sem gravar aqui, seria desfeito no próximo
aplicativo que ganhasse o foco. A interface não aplica: ela *grava*, e avisa o
daemon.

Sem esse aviso a interface mentiria: o daemon lê a configuração ao iniciar, e
uma mudança gravada em disco não valeria até o próximo reinício. É por isso
que toda escrita aqui termina num ``reload``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from logitune import config as config_module
from logitune.config import Config

logger = logging.getLogger(__name__)

#: Nome da unidade de usuário, que sabe recarregar via ExecReload.
_SERVICE = "logitune-daemon"


class ConfigStore:
    """Lê e grava a configuração, mantendo o daemon em dia.

    Sempre relê antes de alterar em vez de guardar uma cópia: o arquivo pode
    ter sido editado à mão entre uma mudança e outra, e sobrescrever com um
    estado velho apagaria silenciosamente o que a pessoa escreveu.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def load(self) -> Config:
        return config_module.load(self.path)

    def update(self, mutate: Callable[[Config], None]) -> Config:
        """Aplica uma mudança e grava, avisando o daemon em seguida."""
        config = self.load()
        mutate(config)
        config.save(self.path)
        self.notify_daemon()
        return config

    def notify_daemon(self) -> bool:
        """Pede ao daemon que releia. Devolve se o aviso saiu.

        Um daemon parado não é erro: a configuração já está em disco e vale
        quando ele subir. Por isso a falha aqui é silenciosa.
        """
        systemctl = shutil.which("systemctl")
        if systemctl is None:
            return False
        try:
            resultado = subprocess.run(
                [systemctl, "--user", "reload", _SERVICE],
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("não consegui recarregar o daemon: %s", exc)
            return False
        if resultado.returncode != 0:
            logger.debug("o daemon não recarregou: %s", resultado.stderr.decode().strip())
            return False
        return True

    def daemon_running(self) -> bool:
        """O daemon está ativo? A interface avisa quando não está."""
        systemctl = shutil.which("systemctl")
        if systemctl is None:
            return False
        try:
            saida = subprocess.run(
                [systemctl, "--user", "is-active", _SERVICE],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return False
        return saida == "active"
