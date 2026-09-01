# SPDX-License-Identifier: GPL-3.0-or-later
"""Tradução das mensagens visíveis ao usuário.

O idioma de origem do código é o inglês, e os outros idiomas são catálogos
``gettext`` — inclusive o português, que era o original. A inversão é
deliberada: o README, os commits e as issues são em inglês, e alguém que chega
pelo repositório não deveria encontrar uma janela num idioma que talvez não
leia.

Se não houver catálogo compilado para o idioma da sessão, tudo cai no inglês
do próprio código. Isso significa que uma instalação sem os arquivos de
tradução funciona igual, só que sem traduzir — nunca quebra.
"""

from __future__ import annotations

import gettext
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DOMAIN = "logi-tune-linux"

#: Catálogos que acompanham o pacote, usados quando não há instalação de
#: sistema. É o caso de quem instala com pipx a partir do repositório.
_BUNDLED = Path(__file__).parent / "locale"

#: Onde a distribuição instala catálogos quando o projeto vira um .deb.
_SYSTEM = Path("/usr/share/locale")


def _locale_dir() -> Path:
    """Onde procurar os catálogos.

    A cópia do pacote vem primeiro: se ela existe, é a que corresponde a este
    código. A do sistema serve ao pacote da distribuição.
    """
    if (_BUNDLED).is_dir() and any(_BUNDLED.glob("*/LC_MESSAGES/*.mo")):
        return _BUNDLED
    return _SYSTEM


def _build_translation() -> gettext.NullTranslations:
    idiomas = None
    forcado = os.environ.get("LOGITUNE_LANG")
    if forcado:
        # Existe para testar uma tradução sem mexer no idioma da sessão.
        idiomas = [forcado]
    try:
        return gettext.translation(
            DOMAIN, localedir=str(_locale_dir()), languages=idiomas, fallback=True
        )
    except OSError as exc:  # pragma: no cover - depende do sistema de arquivos
        logger.debug("sem catálogo de tradução: %s", exc)
        return gettext.NullTranslations()


_translation = _build_translation()

#: Traduz uma mensagem. O nome curto é a convenção do gettext, e mantê-la é o
#: que deixa o xgettext encontrar as mensagens sozinho.
gettext_ = _translation.gettext
ngettext = _translation.ngettext


def _(message: str) -> str:
    return gettext_(message)


def reload_language() -> None:
    """Relê o catálogo. Usado pelos testes ao trocar de idioma."""
    global _translation, gettext_, ngettext
    _translation = _build_translation()
    gettext_ = _translation.gettext
    ngettext = _translation.ngettext
