# SPDX-License-Identifier: GPL-3.0-or-later
"""O sistema de ações: o vocabulário do que um botão pode fazer.

Antes disto, uma ação só podia ser uma linha de comando — o que funcionava,
mas obrigava quem quisesse "colar" a saber qual programa sintetiza teclas, e
não dava à interface nada para listar. Agora existe um catálogo com nome,
categoria e disponibilidade, e o botão aponta para uma entrada dele.

Uso típico::

    from logitune.actions import default_registry, parse_button, resolve

    binding = parse_button("media.play_pause")
    acao = resolve(binding.press)
    if acao.available():
        acao.run()
"""

from logitune.actions.binding import (
    Binding,
    BindingError,
    ButtonBinding,
    command_binding,
    merge_raw,
)
from logitune.actions.gestures import GESTURE_NAMES, Gesture
from logitune.actions.registry import (
    Registry,
    ResolvedAction,
    default_registry,
    resolve,
)
from logitune.actions.spec import (
    AVAILABLE,
    ActionContext,
    ActionError,
    ActionSpec,
    Availability,
    Category,
    Parameter,
    UnknownAction,
)

parse_button = ButtonBinding.parse

__all__ = [
    "AVAILABLE",
    "ActionContext",
    "ActionError",
    "ActionSpec",
    "Availability",
    "Binding",
    "BindingError",
    "ButtonBinding",
    "Category",
    "GESTURE_NAMES",
    "Gesture",
    "Parameter",
    "Registry",
    "ResolvedAction",
    "UnknownAction",
    "command_binding",
    "default_registry",
    "merge_raw",
    "parse_button",
    "resolve",
]
