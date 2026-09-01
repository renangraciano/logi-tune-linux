# SPDX-License-Identifier: GPL-3.0-or-later
"""O vocabulário de ações: o que um botão pode fazer.

Uma ação é uma coisa que o usuário reconhece — "colar", "próxima faixa",
"bloquear a tela" — separada de *como* ela acontece. O como é problema dos
backends em :mod:`logitune.actions.backends`, que variam bastante entre si:
mídia vai por D-Bus, volume por PipeWire, atalho de teclado por uinput.

Essa separação existe por dois motivos. A interface precisa listar o que dá
para atribuir a um botão sem saber nada de D-Bus; e o daemon precisa perguntar
*antes* de desviar um botão se aquela ação roda nesta sessão — um botão
desviado cuja ação falha não faz nada e não avisa, o que é pior do que deixar
o botão com a função de fábrica.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping

from logitune.i18n import _

if TYPE_CHECKING:  # pragma: no cover - só para anotação
    from logitune.device import LogitechDevice


class ActionError(Exception):
    """A ação não pôde ser executada."""


class UnknownAction(ActionError):
    """O identificador não corresponde a nenhuma ação do catálogo."""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"não existe a ação {action_id!r}")


class Category(enum.Enum):
    """Grupos do catálogo, na ordem em que a interface deve mostrá-los."""

    SISTEMA = "sistema"
    JANELAS = "janelas"
    MIDIA = "midia"
    REUNIAO = "reuniao"
    EDICAO = "edicao"
    NAVEGADOR = "navegador"
    MOUSE = "mouse"
    APLICATIVO = "aplicativo"
    PERSONALIZADO = "personalizado"

    @property
    def label(self) -> str:
        return {
            Category.SISTEMA: _("System"),
            Category.JANELAS: _("Windows and workspaces"),
            Category.MIDIA: _("Media"),
            Category.REUNIAO: _("Meeting controls"),
            Category.EDICAO: _("Editing"),
            Category.NAVEGADOR: _("Browser"),
            Category.MOUSE: _("Mouse"),
            Category.APLICATIVO: _("Open an application"),
            Category.PERSONALIZADO: _("Custom"),
        }[self]

    @property
    def order(self) -> int:
        return list(Category).index(self)


@dataclass(frozen=True)
class Availability:
    """Esta ação roda nesta sessão?

    ``reason`` explica o que falta, com o comando que resolve quando existe
    um. A interface mostra isso em vez de esconder a opção: uma ação que
    sumiu sem explicação parece bug.
    """

    ok: bool
    reason: str = ""
    #: A falta é passageira — nenhum tocador aberto agora, mas um pode abrir
    #: no minuto seguinte. Distinguir isso importa para o daemon: ele não deve
    #: recusar um botão por causa de algo que muda sozinho, só por causa do
    #: que está estruturalmente faltando (uma permissão, um programa, um id
    #: que não existe).
    transient: bool = False

    def __bool__(self) -> bool:
        return self.ok

    @property
    def usable(self) -> bool:
        """Vale a pena desviar o botão para esta ação?"""
        return self.ok or self.transient


#: Resposta pronta para o caso comum de "está tudo certo".
AVAILABLE = Availability(True)


@dataclass(frozen=True)
class Parameter:
    """Um valor que a ação precisa receber (a URL, o atalho, o comando)."""

    name: str
    label: str
    #: Dica de edição para a interface: text, url, shortcut, app, command, number.
    kind: str = "text"
    required: bool = True
    default: Any = None


@dataclass
class ActionContext:
    """O que a ação recebe na hora de rodar."""

    params: Mapping[str, Any] = field(default_factory=dict)
    #: O mouse, quando quem executa tem um aberto (o daemon sempre tem).
    device: LogitechDevice | None = None

    def get(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    def require(self, name: str) -> Any:
        value = self.params.get(name)
        if value is None or value == "":
            raise ActionError(f"falta o parâmetro {name!r}")
        return value

    def require_device(self) -> LogitechDevice:
        if self.device is None:
            raise ActionError("esta ação precisa do mouse conectado")
        return self.device


@dataclass(frozen=True)
class ActionSpec:
    """Uma entrada do catálogo."""

    id: str
    label: str
    category: Category
    run: Callable[[ActionContext], None]
    description: str = ""
    parameters: tuple[Parameter, ...] = ()
    #: O atalho que esta ação envia, quando ela é um atalho fixo. A interface
    #: mostra isso ao lado do rótulo, como o Options+ faz.
    shortcut: str = ""
    #: Pergunta ao backend se a ação roda aqui. Sem sondagem, presume-se que sim.
    probe: Callable[[], Availability] | None = None

    def available(self) -> Availability:
        if self.probe is None:
            return AVAILABLE
        try:
            return self.probe()
        except Exception as exc:  # noqa: BLE001 - sondagem nunca derruba a UI
            return Availability(False, f"a verificação falhou: {exc}")

    def missing_parameters(self, params: Mapping[str, Any]) -> list[Parameter]:
        """Parâmetros obrigatórios que não foram preenchidos."""
        return [
            p
            for p in self.parameters
            if p.required and p.default is None and not params.get(p.name)
        ]
