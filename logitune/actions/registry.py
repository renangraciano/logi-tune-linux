# SPDX-License-Identifier: GPL-3.0-or-later
"""O catálogo em memória: procurar uma ação e prepará-la para rodar.

A interface pergunta ao registro o que existe, agrupado por categoria. O
daemon pergunta se uma ação específica está disponível *antes* de desviar o
botão. As duas perguntas passam por aqui.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from logitune.actions.binding import Binding
from logitune.actions.spec import (
    ActionContext,
    ActionSpec,
    Availability,
    Category,
    UnknownAction,
)

logger = logging.getLogger(__name__)


class Registry:
    """As ações conhecidas, indexadas pelo identificador."""

    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}

    def register(self, spec: ActionSpec) -> ActionSpec:
        if spec.id in self._specs:
            raise ValueError(f"ação duplicada no catálogo: {spec.id}")
        self._specs[spec.id] = spec
        return spec

    def get(self, action_id: str) -> ActionSpec | None:
        return self._specs.get(action_id)

    def require(self, action_id: str) -> ActionSpec:
        spec = self._specs.get(action_id)
        if spec is None:
            raise UnknownAction(action_id)
        return spec

    def by_category(self) -> dict[Category, list[ActionSpec]]:
        """As ações agrupadas, na ordem em que a interface as mostra."""
        agrupado: dict[Category, list[ActionSpec]] = {}
        for spec in self._specs.values():
            agrupado.setdefault(spec.category, []).append(spec)
        return {
            categoria: sorted(agrupado[categoria], key=lambda s: s.label.casefold())
            for categoria in sorted(agrupado, key=lambda c: c.order)
        }

    def recommended(self) -> list[ActionSpec]:
        """As ações em destaque, na ordem em que o catálogo as declara."""
        from logitune.actions.catalog import RECOMMENDED

        return [spec for spec in (self.get(i) for i in RECOMMENDED) if spec is not None]

    def search(self, needle: str) -> list[ActionSpec]:
        """Ações que casam com o trecho.

        Procuramos também no nome da categoria porque é assim que as pessoas
        buscam: quem escreve "navegador" quer as ações de aba e histórico, e
        nenhuma delas tem essa palavra no identificador nem no rótulo.
        """
        alvo = needle.casefold()
        return [
            spec
            for spec in self
            if alvo in spec.id.casefold()
            or alvo in spec.label.casefold()
            or alvo in spec.category.label.casefold()
        ]

    def __iter__(self) -> Iterator[ActionSpec]:
        return iter(sorted(self._specs.values(), key=lambda s: (s.category.order, s.label)))

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._specs


_default: Registry | None = None


def default_registry() -> Registry:
    """O catálogo padrão, montado na primeira consulta."""
    global _default
    if _default is None:
        from logitune.actions import catalog

        _default = catalog.build()
    return _default


@dataclass(frozen=True)
class ResolvedAction:
    """Uma ação do catálogo já casada com os parâmetros da configuração."""

    spec: ActionSpec
    params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.spec.label

    def available(self) -> Availability:
        """Roda nesta sessão, com estes parâmetros?

        Um parâmetro obrigatório em branco conta como indisponível: a ação
        existe, mas não tem o que executar, e o daemon precisa saber disso
        antes de desviar o botão.
        """
        faltando = self.spec.missing_parameters(self.params)
        if faltando:
            nomes = ", ".join(p.name for p in faltando)
            return Availability(False, f"falta preencher: {nomes}")
        return self.spec.available()

    def run(self, device=None, power=None) -> None:
        parametros = {
            p.name: p.default
            for p in self.spec.parameters
            if p.default is not None and p.name not in self.params
        }
        parametros.update(self.params)
        self.spec.run(ActionContext(params=parametros, device=device, power=power))


def resolve(binding: Binding, registry: Registry | None = None) -> ResolvedAction:
    """Casa um vínculo da configuração com a ação correspondente."""
    registro = registry or default_registry()
    return ResolvedAction(spec=registro.require(binding.action), params=dict(binding.params))
