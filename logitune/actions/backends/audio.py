# SPDX-License-Identifier: GPL-3.0-or-later
"""Volume e mudo pelo PipeWire.

O ``wpctl`` acompanha o PipeWire, que é o servidor de áudio padrão do Ubuntu
desde a 22.10, e mexe direto no destino padrão — sem depender de quem está em
foco nem da regra udev do ``uinput``.

Em troca disso, o GNOME não mostra o indicador de volume na tela: aquele OSD
responde às teclas de mídia que ele mesmo captura, não a mudanças vindas de
fora. O ajuste acontece, mas em silêncio.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from logitune.actions.spec import AVAILABLE, ActionError, Availability

logger = logging.getLogger(__name__)

#: Saída de áudio padrão e entrada padrão, na notação do wpctl.
SINK = "@DEFAULT_AUDIO_SINK@"
SOURCE = "@DEFAULT_AUDIO_SOURCE@"

#: Quanto um passo de volume mexe, em pontos percentuais.
DEFAULT_STEP = 5

#: Teto ao subir o volume. O PipeWire aceita passar de 100%, o que distorce;
#: quem quiser amplificar tem os controles do sistema para isso.
_LIMIT = "1.0"


def _wpctl() -> str:
    caminho = shutil.which("wpctl")
    if caminho is None:
        raise ActionError("o wpctl não está instalado (faz parte do wireplumber)")
    return caminho


def _run(*args: str) -> str:
    comando = [_wpctl(), *args]
    try:
        resultado = subprocess.run(  # noqa: S603 - argumentos são nossos
            comando, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ActionError(f"o wpctl não respondeu: {exc}") from exc
    if resultado.returncode != 0:
        raise ActionError(f"wpctl {' '.join(args)}: {resultado.stderr.strip()}")
    return resultado.stdout.strip()


def change_volume(step: int = DEFAULT_STEP, *, target: str = SINK) -> None:
    """Sobe (positivo) ou desce (negativo) o volume."""
    direcao = "+" if step >= 0 else "-"
    _run("set-volume", target, f"{abs(step)}%{direcao}", "-l", _LIMIT)


def toggle_mute(*, target: str = SINK) -> None:
    _run("set-mute", target, "toggle")


def volume(*, target: str = SINK) -> float:
    """O volume atual, de 0.0 a 1.0."""
    # "Volume: 0.66" — e "Volume: 0.66 [MUTED]" quando está no mudo.
    saida = _run("get-volume", target)
    for pedaco in saida.replace("Volume:", "").split():
        try:
            return float(pedaco)
        except ValueError:
            continue
    raise ActionError(f"não entendi a resposta do wpctl: {saida!r}")


def is_muted(*, target: str = SINK) -> bool:
    return "MUTED" in _run("get-volume", target)


def availability() -> Availability:
    if shutil.which("wpctl") is None:
        return Availability(False, "o wpctl não está instalado (sudo apt install wireplumber)")
    return AVAILABLE
