# SPDX-License-Identifier: GPL-3.0-or-later
"""Abrir aplicativos, arquivos, endereços — e rodar comandos.

O ``Gio.AppInfo`` é o mesmo registro que o menu de aplicativos usa, então
"abrir o Calculadora" acha o programa pelo arquivo ``.desktop``, com o nome e
o ícone que a pessoa já conhece, e o inicia do jeito que a sessão espera.

O comando de shell continua existindo para o que não couber em nenhuma ação —
é a saída de emergência que mantém funcionando quem já configurava o daemon
com linhas de comando.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass

from logitune.actions.spec import AVAILABLE, ActionError, Availability

logger = logging.getLogger(__name__)


def _gio():
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError) as exc:  # pragma: no cover - depende do ambiente
        raise ActionError(
            "o PyGObject não está instalado (sudo apt install python3-gi)"
        ) from exc
    return Gio


@dataclass(frozen=True)
class AppEntry:
    """Um aplicativo instalado, como a interface vai listar."""

    desktop_id: str
    name: str
    icon: str = ""
    #: Classe da janela, para casar um perfil com o que está em foco.
    wm_class: str = ""


def _wm_class(info, desktop_id: str) -> str:
    """A classe de janela que este aplicativo provavelmente terá.

    ``StartupWMClass`` é a resposta autoritativa quando o arquivo .desktop a
    declara. Quando não declara — a maioria dos casos — o identificador sem o
    sufixo é o palpite que acerta quase sempre, porque é dele que os toolkits
    derivam a classe.
    """
    declarada = info.get_startup_wm_class() if hasattr(info, "get_startup_wm_class") else None
    if declarada:
        return declarada
    base = desktop_id.removesuffix(".desktop")
    # "org.gnome.Calculator" casa melhor pelo último segmento.
    return base.rsplit(".", 1)[-1] if "." in base else base


def list_apps() -> list[AppEntry]:
    """Os aplicativos que aparecem no menu, em ordem alfabética."""
    Gio = _gio()
    entradas = []
    for info in Gio.AppInfo.get_all():
        if not info.should_show():
            continue
        icone = info.get_icon()
        desktop_id = info.get_id() or ""
        entradas.append(
            AppEntry(
                desktop_id=desktop_id,
                name=info.get_display_name() or info.get_name() or "",
                icon=icone.to_string() if icone else "",
                wm_class=_wm_class(info, desktop_id),
            )
        )
    return sorted(entradas, key=lambda e: e.name.casefold())


def _desktop_info(desktop_id: str):
    """``Gio.DesktopAppInfo`` para um id, ou ``None`` se não existir.

    O PyGObject **levanta ``TypeError``** quando o construtor devolve NULL,
    em vez de devolver ``None``. Sem este embrulho a exceção sobe e mata a
    ação: era por isso que atribuir um aplicativo a um botão não fazia nada,
    nem sequer caía no caminho alternativo logo abaixo.
    """
    Gio = _gio()
    try:
        return Gio.DesktopAppInfo.new(desktop_id)
    except TypeError:
        return None


def find_app(target: str):
    """Acha um aplicativo por id ``.desktop``, executável ou nome visível.

    Quem escreve à mão põe o nome do comando — ``gnome-calculator`` — e o id
    é outra coisa, ``org.gnome.Calculator.desktop``. Procurar pelos três é o
    que faz a forma escrita à mão funcionar como a escolhida na lista.
    """
    Gio = _gio()
    ids = [target] if target.endswith(".desktop") else [f"{target}.desktop", target]
    for desktop_id in ids:
        info = _desktop_info(desktop_id)
        if info is not None:
            return info

    alvo = target.removesuffix(".desktop").casefold()
    for info in Gio.AppInfo.get_all():
        executavel = (info.get_executable() or "").rsplit("/", 1)[-1]
        if executavel.casefold() == alvo:
            return info
        if (info.get_display_name() or "").casefold() == alvo:
            return info
    return None


def launch_app(target: str) -> None:
    """Inicia um aplicativo pelo id ``.desktop`` ou por uma linha de comando.

    Aceitar as duas formas é deliberado: o id é o que a interface vai gravar,
    a linha de comando é o que uma pessoa escreve à mão no JSON.
    """
    Gio = _gio()
    info = find_app(target)
    if info is None:
        try:
            info = Gio.AppInfo.create_from_commandline(
                target, None, Gio.AppInfoCreateFlags.NONE
            )
        except TypeError as exc:
            # NULL de novo: a linha de comando não pôde ser interpretada.
            raise ActionError(f"não encontrei o aplicativo {target!r}") from exc
    if info is None:
        raise ActionError(f"não encontrei o aplicativo {target!r}")
    try:
        info.launch(None, None)
    except Exception as exc:  # noqa: BLE001 - GLib.Error vira mensagem legível
        raise ActionError(f"não consegui abrir {target!r}: {exc}") from exc


def open_uri(uri: str) -> None:
    """Abre um endereço, arquivo ou pasta no aplicativo padrão."""
    Gio = _gio()
    # Sem esquema, é um caminho no disco: o Gio precisa de uma URI completa.
    alvo = uri if "://" in uri or uri.startswith("mailto:") else Gio.File.new_for_path(uri).get_uri()
    try:
        Gio.AppInfo.launch_default_for_uri(alvo, None)
    except Exception as exc:  # noqa: BLE001
        raise ActionError(f"não consegui abrir {uri!r}: {exc}") from exc


def run_command(command: str) -> None:
    """Dispara uma linha de comando e não espera por ela.

    O processo sai da nossa sessão para não morrer junto com o daemon, e o
    kernel recolhe o filho — quem chama mantém ``SIGCHLD`` em ``SIG_IGN``.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ActionError(f"comando mal formado {command!r}: {exc}") from exc
    if not argv:
        raise ActionError("comando vazio")
    try:
        subprocess.Popen(  # noqa: S603 - o comando vem da config do usuário
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise ActionError(f"não consegui executar {command!r}: {exc}") from exc


def availability() -> Availability:
    try:
        _gio()
    except ActionError as exc:
        return Availability(False, str(exc))
    return AVAILABLE
