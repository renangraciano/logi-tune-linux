# SPDX-License-Identifier: GPL-3.0-or-later
"""Ações que a sessão já sabe fazer, faladas por D-Bus.

Bloquear a tela, abrir a grade de aplicativos, pausar a música: tudo isso tem
um método na sessão, e chamá-lo é mais confiável do que fingir uma tecla. Um
comando de mídia por MPRIS chega ao tocador mesmo com a janela minimizada, e
funciona igual no Wayland e no X.

Nem tudo tem método, e isso não é uniforme: o ``org.gnome.Shell.Screenshot``
existe mas o GNOME recusa a chamada de quem não é o próprio shell — testado
nesta máquina, responde ``AccessDenied``. Para essas, a tecla é o caminho
sancionado, e o catálogo usa o backend de teclas.
"""

from __future__ import annotations

import logging

from logitune.actions.spec import AVAILABLE, ActionError, Availability

logger = logging.getLogger(__name__)

_MPRIS_PREFIX = "org.mpris.MediaPlayer2."
_MPRIS_PATH = "/org/mpris/MediaPlayer2"
_MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"

_SHELL_NAME = "org.gnome.Shell"
_SHELL_PATH = "/org/gnome/Shell"

#: Tempo máximo de espera por uma resposta, em milissegundos. Curto de
#: propósito: isto roda no laço do daemon, e um tocador travado não pode
#: prender o mouse inteiro.
_TIMEOUT_MS = 2000


def _gio():
    """Importa o PyGObject na hora do uso.

    Ele vem do sistema (``python3-gi``) e não é dependência da pilha HID++.
    Quem não tem simplesmente fica sem as ações de D-Bus, e a sondagem diz
    isso em vez de deixar o import estourar em outro lugar.
    """
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError) as exc:  # pragma: no cover - depende do ambiente
        raise ActionError(
            "o PyGObject não está instalado (sudo apt install python3-gi)"
        ) from exc
    return Gio, GLib


_bus = None


def _session_bus():
    global _bus
    if _bus is None:
        Gio, _ = _gio()
        try:
            _bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as exc:  # noqa: BLE001 - GLib.Error não é importável cedo
            raise ActionError(f"não consegui falar com o D-Bus da sessão: {exc}") from exc
    return _bus


def call(
    name: str,
    path: str,
    interface: str,
    method: str,
    params=None,
    reply=None,
):
    """Chama um método D-Bus e devolve a resposta."""
    Gio, _ = _gio()
    bus = _session_bus()
    try:
        return bus.call_sync(
            name, path, interface, method, params, reply,
            Gio.DBusCallFlags.NONE, _TIMEOUT_MS, None,
        )
    except Exception as exc:  # noqa: BLE001 - GLib.Error vira mensagem legível
        raise ActionError(f"{name}.{method} falhou: {exc}") from exc


def _names() -> list[str]:
    """Os nomes registrados no barramento da sessão."""
    resposta = call(
        "org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "ListNames", None,
        _gio()[1].VariantType.new("(as)"),
    )
    return list(resposta.unpack()[0])


def _has_name(name: str) -> bool:
    try:
        return name in _names()
    except ActionError:
        return False


# -- tela ------------------------------------------------------------


def lock_screen() -> None:
    call("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver", "Lock")


def screensaver_availability() -> Availability:
    try:
        _gio()
    except ActionError as exc:
        return Availability(False, str(exc))
    if not _has_name("org.gnome.ScreenSaver"):
        return Availability(False, "o org.gnome.ScreenSaver não está na sessão")
    return AVAILABLE


# -- shell -----------------------------------------------------------


def shell_call(method: str) -> None:
    call(_SHELL_NAME, _SHELL_PATH, _SHELL_NAME, method)


def shell_availability() -> Availability:
    try:
        _gio()
    except ActionError as exc:
        return Availability(False, str(exc))
    if not _has_name(_SHELL_NAME):
        return Availability(False, "esta ação depende do GNOME Shell")
    return AVAILABLE


# -- mídia -----------------------------------------------------------


def players() -> list[str]:
    """Os tocadores que expõem MPRIS agora."""
    return sorted(n for n in _names() if n.startswith(_MPRIS_PREFIX))


def _playback_status(name: str) -> str:
    _, GLib = _gio()
    try:
        resposta = call(
            name, _MPRIS_PATH, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (_MPRIS_PLAYER, "PlaybackStatus")),
            GLib.VariantType.new("(v)"),
        )
    except ActionError:
        return ""
    return str(resposta.unpack()[0])


def preferred_player() -> str | None:
    """Qual tocador deve receber o comando.

    Com vários abertos, o que está tocando é quase sempre o que a pessoa tem
    em mente. Sem nenhum tocando, o primeiro serve — é o que dá para saber sem
    inventar uma preferência que o usuário não expressou.
    """
    disponiveis = players()
    if not disponiveis:
        return None
    for name in disponiveis:
        if _playback_status(name) == "Playing":
            return name
    return disponiveis[0]


def media_call(method: str) -> None:
    """Manda um comando MPRIS para o tocador escolhido."""
    name = preferred_player()
    if name is None:
        raise ActionError("nenhum tocador de mídia aberto")
    call(name, _MPRIS_PATH, _MPRIS_PLAYER, method)
    logger.debug("MPRIS %s → %s", method, name)


def media_availability() -> Availability:
    try:
        _gio()
    except ActionError as exc:
        return Availability(False, str(exc))
    if not players():
        # Passageiro de propósito: abrir o Spotify resolve, e o botão precisa
        # continuar desviado esperando por isso.
        return Availability(False, "nenhum tocador de mídia aberto no momento", transient=True)
    return AVAILABLE
