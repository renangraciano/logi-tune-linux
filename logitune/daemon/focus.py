# SPDX-License-Identifier: GPL-3.0-or-later
"""Descobre qual janela está em foco.

No X11 dá para saber isso sem custo: o gerenciador de janelas mantém a
propriedade ``_NET_ACTIVE_WINDOW`` na janela raiz e nos avisa quando ela muda.
Ficamos parados no descritor do X até chegar um evento — nada de polling.

No Wayland não existe equivalente acessível a um cliente comum: a política de
segurança do protocolo esconde as janelas das outras aplicações. Ali o
observador se declara indisponível e o daemon roda só com o perfil padrão.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Window:
    """A janela em foco."""

    wm_class: str
    title: str

    def __str__(self) -> str:
        return f"{self.wm_class or '?'} — {self.title or '(sem título)'}"


class FocusWatcher:
    """Observa trocas de janela ativa no X11."""

    def __init__(self) -> None:
        self._display = None
        self._root = None
        self._atom_active = None
        self._atom_name = None
        self._atom_utf8 = None

    # -- disponibilidade -----------------------------------------------

    @staticmethod
    def session_type() -> str:
        return os.environ.get("XDG_SESSION_TYPE", "").casefold()

    def open(self) -> bool:
        """Conecta ao X. Devolve ``False`` se não der para observar o foco."""
        if self.session_type() == "wayland":
            logger.warning(
                "Sessão Wayland: o protocolo não deixa um aplicativo comum saber "
                "qual janela está em foco, então os perfis por aplicação ficam "
                "desativados. Use uma sessão Xorg para ter esse recurso."
            )
            return False

        try:
            from Xlib import X, display
            from Xlib.error import DisplayError
        except ImportError:
            logger.warning(
                "python-xlib não encontrado; perfis por aplicação desativados. "
                "Instale com: sudo apt install python3-xlib"
            )
            return False

        try:
            self._display = display.Display()
        except (DisplayError, OSError) as exc:
            logger.warning("não foi possível conectar ao servidor X: %s", exc)
            return False

        self._root = self._display.screen().root
        self._atom_active = self._display.intern_atom("_NET_ACTIVE_WINDOW")
        self._atom_name = self._display.intern_atom("_NET_WM_NAME")
        self._atom_utf8 = self._display.intern_atom("UTF8_STRING")
        # Só nos interessam mudanças de propriedade na janela raiz.
        self._root.change_attributes(event_mask=X.PropertyChangeMask)
        self._display.flush()
        return True

    def close(self) -> None:
        if self._display is not None:
            self._display.close()
            self._display = None

    @property
    def fileno(self) -> int | None:
        return self._display.fileno() if self._display is not None else None

    # -- leitura -------------------------------------------------------

    def _window_title(self, window) -> str:
        try:
            prop = window.get_full_property(self._atom_name, self._atom_utf8)
            if prop and prop.value:
                value = prop.value
                if isinstance(value, bytes):
                    return value.decode("utf-8", errors="replace")
                return str(value)
            return window.get_wm_name() or ""
        except Exception:  # noqa: BLE001 - a janela pode sumir no meio
            return ""

    def current(self) -> Window | None:
        """Lê a janela em foco agora."""
        if self._display is None:
            return None
        try:
            prop = self._root.get_full_property(self._atom_active, 0)
            if not prop or not prop.value:
                return None
            window = self._display.create_resource_object("window", prop.value[0])
            wm_class = window.get_wm_class()
            # get_wm_class devolve (instância, classe); a instância é o que
            # costuma bater com o nome do executável.
            name = wm_class[0] if wm_class else ""
            return Window(wm_class=name, title=self._window_title(window))
        except Exception as exc:  # noqa: BLE001 - janelas somem entre chamadas
            logger.debug("não consegui ler a janela ativa: %s", exc)
            return None

    def drain_events(self) -> bool:
        """Consome os eventos X pendentes. Devolve ``True`` se o foco mudou."""
        if self._display is None:
            return False
        changed = False
        for _ in range(self._display.pending_events()):
            event = self._display.next_event()
            if getattr(event, "atom", None) == self._atom_active:
                changed = True
        return changed
