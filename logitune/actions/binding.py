# SPDX-License-Identifier: GPL-3.0-or-later
"""O que a configuração diz que um botão faz.

Três formas são aceitas, da mais curta para a mais completa::

    "0x0053": "browser.back"
    "0x0056": { "action": "key.shortcut", "keys": "ctrl+shift+t" }
    "0x01A0": { "tap": "system.overview", "drag_left": "workspace.left" }

A primeira basta para as ações sem parâmetro, que são a maioria. A segunda
aparece quando a ação precisa de um valor. A terceira dá um gesto diferente
para cada movimento do mesmo botão.

A chave antiga ``actions``, cujo valor é uma linha de comando, continua
funcionando: ela é traduzida para a ação ``shell.run``. Quem já configurou o
daemon não precisa mexer em nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from logitune.actions.gestures import GESTURE_NAMES, Gesture


class BindingError(ValueError):
    """A configuração do botão não faz sentido."""


@dataclass(frozen=True)
class Binding:
    """Uma ação com os parâmetros dela."""

    action: str
    params: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: Any) -> Binding:
        if isinstance(raw, str):
            if not raw.strip():
                raise BindingError("ação vazia")
            return cls(action=raw.strip())
        if isinstance(raw, Mapping):
            action = raw.get("action")
            if not isinstance(action, str) or not action.strip():
                raise BindingError(f"falta a chave 'action' em {dict(raw)!r}")
            params = {k: v for k, v in raw.items() if k != "action"}
            return cls(action=action.strip(), params=params)
        raise BindingError(f"não sei ler {raw!r} como ação")

    def to_json(self) -> Any:
        """Volta para a forma mais curta que representa este vínculo."""
        if not self.params:
            return self.action
        return {"action": self.action, **dict(self.params)}


@dataclass(frozen=True)
class ButtonBinding:
    """Tudo que um botão faz: uma ação no clique ou um mapa de gestos."""

    press: Binding | None = None
    gestures: Mapping[Gesture, Binding] = field(default_factory=dict)

    @property
    def on_press(self) -> Binding | None:
        """A ação a disparar quando o botão é apertado.

        Enquanto o reconhecimento de gestos não existe, um botão configurado
        só com gestos dispara o ``tap`` no clique. É o comportamento que mais
        se aproxima do pretendido, e evita que o botão fique mudo.
        """
        if self.press is not None:
            return self.press
        return self.gestures.get(Gesture.TAP)

    @property
    def is_empty(self) -> bool:
        return self.press is None and not self.gestures

    def all_bindings(self) -> list[Binding]:
        """Todos os vínculos, para validar disponibilidade de uma vez."""
        found = [self.press] if self.press else []
        found.extend(self.gestures.values())
        return found

    @classmethod
    def parse(cls, raw: Any) -> ButtonBinding:
        if isinstance(raw, Mapping) and "action" not in raw:
            # Sem 'action', só resta ser um mapa de gestos. Exigimos que todas
            # as chaves sejam gestos conhecidos: um nome errado aqui viraria um
            # gesto que nunca dispara, e falhar alto é melhor que isso.
            desconhecidos = set(raw) - GESTURE_NAMES
            if desconhecidos:
                raise BindingError(
                    f"gesto(s) desconhecido(s): {', '.join(sorted(desconhecidos))} "
                    f"(use {', '.join(sorted(GESTURE_NAMES))})"
                )
            gestures = {Gesture(name): Binding.parse(value) for name, value in raw.items()}
            return cls(gestures=gestures)
        return cls(press=Binding.parse(raw))

    def to_json(self) -> Any:
        if self.press is not None:
            return self.press.to_json()
        return {g.value: b.to_json() for g, b in self.gestures.items()}


def command_binding(command: str) -> ButtonBinding:
    """Traduz uma linha de comando da chave antiga ``actions``."""
    return ButtonBinding(press=Binding(action="shell.run", params={"command": command}))


def merge_raw(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Combina dois mapas de vínculos, gesto a gesto.

    O merge raso por botão apagaria seis gestos quando um perfil quisesse
    trocar só um. Por isso, quando os dois lados descrevem gestos do mesmo
    botão, combinamos por gesto; em qualquer outro caso o perfil sobrepõe.
    """
    merged: dict[str, Any] = dict(base)
    for cid, value in override.items():
        anterior = merged.get(cid)
        if _is_gesture_map(anterior) and _is_gesture_map(value):
            merged[cid] = {**anterior, **value}
        else:
            merged[cid] = value
    return merged


def _is_gesture_map(value: Any) -> bool:
    return isinstance(value, Mapping) and "action" not in value
