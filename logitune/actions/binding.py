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


#: Comportamentos da roda que guardam estado entre um giro e o outro, e por
#: isso não podem ser descritos como duas ações independentes. O alternador de
#: aplicativos é o caso: ele segura o Alt enquanto a roda gira.
STATEFUL_WHEEL_ACTIONS = frozenset({"window.switch_apps"})


@dataclass(frozen=True)
class WheelBinding:
    """O que a roda do polegar faz.

    Duas formas. Uma ação por sentido de giro cobre o caso simples — subir e
    baixar o volume, por exemplo — e cada giro dispara uma ação independente.
    A outra é um comportamento contínuo, como o alternador de aplicativos, que
    precisa saber que a roda ainda está girando.
    """

    up: Binding | None = None
    down: Binding | None = None
    #: Id do comportamento contínuo, quando é esse o caso.
    stateful: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.up is None and self.down is None and self.stateful is None

    def for_direction(self, delta: int) -> Binding | None:
        return self.up if delta > 0 else self.down

    @classmethod
    def parse(cls, raw: Any) -> WheelBinding:
        if raw is None:
            return cls()
        if isinstance(raw, str):
            nome = raw.strip()
            if nome in STATEFUL_WHEEL_ACTIONS:
                return cls(stateful=nome)
            raise BindingError(
                f"{nome!r} não é um comportamento contínuo de roda; "
                f"use {{'up': ..., 'down': ...}} para uma ação por sentido"
            )
        if isinstance(raw, Mapping):
            desconhecidos = set(raw) - {"up", "down"}
            if desconhecidos:
                raise BindingError(
                    f"chave(s) desconhecida(s) na roda: {', '.join(sorted(desconhecidos))} "
                    f"(use 'up' e 'down')"
                )
            return cls(
                up=Binding.parse(raw["up"]) if raw.get("up") else None,
                down=Binding.parse(raw["down"]) if raw.get("down") else None,
            )
        raise BindingError(f"não sei ler {raw!r} como ação de roda")

    def to_json(self) -> Any:
        if self.stateful:
            return self.stateful
        saida = {}
        if self.up:
            saida["up"] = self.up.to_json()
        if self.down:
            saida["down"] = self.down.to_json()
        return saida


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
