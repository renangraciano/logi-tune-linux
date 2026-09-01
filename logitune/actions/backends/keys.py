# SPDX-License-Identifier: GPL-3.0-or-later
"""Síntese de teclas por ``uinput``.

É o único backend que precisa da regra udev: escrever em ``/dev/uinput`` cria
um teclado virtual, e o kernel não deixa qualquer processo fazer isso. Em
compensação é o único caminho que alcança o aplicativo em foco, o que nenhuma
API de sessão faz — não existe D-Bus para "colar no que estiver na frente".

O teclado virtual é criado na primeira tecla e fica vivo depois disso. Criar um
dispositivo de entrada por acionamento seria lento e, pior, instável: o
compositor leva alguns milissegundos para notar um teclado novo, e as
primeiras teclas se perderiam.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from logitune.actions.spec import AVAILABLE, ActionError, Availability

logger = logging.getLogger(__name__)

UINPUT_NODE = "/dev/uinput"

#: Tempo para o compositor perceber o teclado recém-criado. Sem esta pausa as
#: primeiras teclas somem, porque ninguém está ouvindo o dispositivo ainda.
_SETTLE = 0.15

#: Apelidos dos modificadores. Aceitamos os nomes que as pessoas escrevem,
#: não só os do kernel.
_MODIFIERS = {
    "ctrl": "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL",
    "rctrl": "KEY_RIGHTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "rshift": "KEY_RIGHTSHIFT",
    "alt": "KEY_LEFTALT",
    "altgr": "KEY_RIGHTALT",
    "super": "KEY_LEFTMETA",
    "meta": "KEY_LEFTMETA",
    "win": "KEY_LEFTMETA",
    "cmd": "KEY_LEFTMETA",
}

#: Nomes amigáveis para teclas cujo nome no kernel ninguém adivinharia.
_ALIASES = {
    "esc": "KEY_ESC",
    "escape": "KEY_ESC",
    "return": "KEY_ENTER",
    "enter": "KEY_ENTER",
    "del": "KEY_DELETE",
    "ins": "KEY_INSERT",
    "pgup": "KEY_PAGEUP",
    "pageup": "KEY_PAGEUP",
    "pgdn": "KEY_PAGEDOWN",
    "pagedown": "KEY_PAGEDOWN",
    "print": "KEY_SYSRQ",
    "printscreen": "KEY_SYSRQ",
    "prtsc": "KEY_SYSRQ",
    "plus": "KEY_EQUAL",
    "equal": "KEY_EQUAL",
    "minus": "KEY_MINUS",
    "space": "KEY_SPACE",
    "backspace": "KEY_BACKSPACE",
    "capslock": "KEY_CAPSLOCK",
    "menu": "KEY_COMPOSE",
    "playpause": "KEY_PLAYPAUSE",
    "nextsong": "KEY_NEXTSONG",
    "previoussong": "KEY_PREVIOUSSONG",
}


@dataclass(frozen=True)
class Shortcut:
    """Um atalho já traduzido para códigos de tecla do kernel."""

    modifiers: tuple[int, ...]
    key: int
    #: Como o usuário escreveu, para mensagens de erro e para a interface.
    text: str = ""

    def __str__(self) -> str:
        return self.text or f"<{self.key}>"


def _ecodes():
    """Importa o evdev na hora do uso.

    A pilha HID++ não depende de nada externo, e queremos que continue assim:
    quem só usa a CLI para ler a bateria não precisa ter o evdev instalado.
    """
    try:
        from evdev import ecodes
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise ActionError(
            "o python3-evdev não está instalado (sudo apt install python3-evdev)"
        ) from exc
    return ecodes


def _resolve(name: str, ecodes) -> int | None:
    """Traduz um nome de tecla para o código do kernel."""
    canonical = _ALIASES.get(name) or _MODIFIERS.get(name)
    if canonical is None:
        canonical = f"KEY_{name.upper()}"
    code = ecodes.ecodes.get(canonical)
    return code if isinstance(code, int) else None


def parse_shortcut(text: str) -> Shortcut:
    """Lê ``"ctrl+shift+t"`` e devolve os códigos de tecla correspondentes.

    A última parte é a tecla; tudo antes dela são modificadores. Escrever o
    modificador por último (``"t+ctrl"``) é aceito, porque a ordem só importa
    na hora de emitir, e nós é que a controlamos.

    Um modificador sozinho (``"super"``) é um atalho legítimo: é assim que se
    abre a visão de atividades do GNOME.
    """
    ecodes = _ecodes()
    if not text.strip():
        raise ActionError("atalho vazio")
    partes = [p.strip().lower() for p in text.split("+")]
    # "ctrl++" quer dizer ctrl mais a tecla '+', e o split de um separador que
    # também é tecla deixa pedaços vazios para trás. Eles não são partes: são
    # o rastro do '+' literal, que entra uma vez só.
    if any(not p for p in partes):
        partes = [p for p in partes if p] + ["plus"]
    if not partes:
        raise ActionError(f"atalho vazio: {text!r}")

    modificadores: list[int] = []
    tecla: int | None = None
    for parte in partes:
        if parte in _MODIFIERS:
            code = _resolve(parte, ecodes)
            if code is not None and code not in modificadores:
                modificadores.append(code)
            continue
        code = _resolve(parte, ecodes)
        if code is None:
            raise ActionError(f"não conheço a tecla {parte!r} (em {text!r})")
        if tecla is not None:
            raise ActionError(f"o atalho {text!r} tem mais de uma tecla principal")
        tecla = code

    if tecla is None:
        if not modificadores:
            raise ActionError(f"atalho vazio: {text!r}")
        # Só modificadores: o último deles é a tecla que se quer emitir.
        tecla = modificadores.pop()

    return Shortcut(modifiers=tuple(modificadores), key=tecla, text=text)


def _keyboard_capabilities(ecodes) -> dict[int, list[int]]:
    """Todas as teclas de um teclado comum.

    O uinput exige declarar as capacidades na criação, e não dá para
    acrescentar depois. Declarar o teclado inteiro de uma vez evita ter que
    recriar o dispositivo quando aparece um atalho com uma tecla nova.
    """
    codes = sorted(
        code
        for code, name in ecodes.keys.items()
        if isinstance(code, int) and 0 < code < 256 and _is_key_name(name)
    )
    return {ecodes.EV_KEY: codes}


def _is_key_name(name) -> bool:
    if isinstance(name, (list, tuple)):
        return any(str(n).startswith("KEY_") for n in name)
    return str(name).startswith("KEY_")


class Keyboard:
    """Um teclado virtual, criado sob demanda e mantido aberto."""

    def __init__(self, name: str = "logi-tune-linux") -> None:
        self.name = name
        self._device = None
        #: Teclas que estão pressionadas agora, para poder soltá-las.
        self._held: set[int] = set()

    def _open(self):
        if self._device is not None:
            return self._device
        ecodes = _ecodes()
        try:
            from evdev import UInput

            self._device = UInput(_keyboard_capabilities(ecodes), name=self.name)
        except OSError as exc:
            raise ActionError(
                f"não consegui criar o teclado virtual em {UINPUT_NODE}: {exc}. "
                f"Instale a regra udev com scripts/install-udev.sh e reconecte-se."
            ) from exc
        logger.debug("teclado virtual %r criado", self.name)
        time.sleep(_SETTLE)
        return self._device

    def tap(self, shortcut: Shortcut) -> None:
        """Pressiona e solta o atalho.

        Os modificadores sobem na ordem inversa da que desceram, que é o que um
        teclado de verdade faz e o que os aplicativos esperam ver.
        """
        ecodes = _ecodes()
        device = self._open()
        sequencia = [*shortcut.modifiers, shortcut.key]
        for code in sequencia:
            device.write(ecodes.EV_KEY, code, 1)
        device.syn()
        for code in reversed(sequencia):
            device.write(ecodes.EV_KEY, code, 0)
        device.syn()

    def press(self, code: int) -> None:
        """Pressiona uma tecla e a deixa pressionada.

        Existe para o alternador de aplicativos, que só funciona com o Alt
        segurado: soltá-lo entre um Tab e outro fecharia a janela do
        alternador e recomeçaria a lista a cada giro da roda.
        """
        ecodes = _ecodes()
        device = self._open()
        device.write(ecodes.EV_KEY, code, 1)
        device.syn()
        self._held.add(code)

    def release(self, code: int) -> None:
        ecodes = _ecodes()
        if code not in self._held:
            return
        device = self._open()
        device.write(ecodes.EV_KEY, code, 0)
        device.syn()
        self._held.discard(code)

    def release_all(self) -> None:
        """Solta o que ficou pressionado.

        Uma tecla segurada sobrevive ao processo que a segurou: se o daemon
        morrer com o Alt em baixo, a sessão fica com o Alt em baixo.
        """
        for code in list(self._held):
            self.release(code)

    def close(self) -> None:
        if self._device is not None:
            self.release_all()
            self._device.close()
            self._device = None


_keyboard = Keyboard()


def keyboard() -> Keyboard:
    """O teclado virtual do processo."""
    return _keyboard


def close() -> None:
    """Fecha o teclado virtual, se ele chegou a ser criado."""
    _keyboard.close()


def availability() -> Availability:
    """Dá para sintetizar teclas nesta sessão?"""
    try:
        _ecodes()
    except ActionError as exc:
        return Availability(False, str(exc))
    if not os.path.exists(UINPUT_NODE):
        return Availability(
            False, f"{UINPUT_NODE} não existe (o módulo uinput não está carregado)"
        )
    if not os.access(UINPUT_NODE, os.W_OK):
        return Availability(
            False,
            f"sem permissão de escrita em {UINPUT_NODE} — "
            f"rode scripts/install-udev.sh e faça login de novo",
        )
    return AVAILABLE


def tap(text: str) -> None:
    """Emite um atalho escrito como ``"ctrl+shift+t"``."""
    keyboard().tap(parse_shortcut(text))
