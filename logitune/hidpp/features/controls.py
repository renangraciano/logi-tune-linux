# SPDX-License-Identifier: GPL-3.0-or-later
"""Feature 0x1B04 — REPROG CONTROLS V4 (remapeamento de botões).

Cada botão físico tem um *Control ID* (CID) fixo e um *Task ID* (TID) que é a
ação padrão dele. Remapear um botão é dizer ao dispositivo que o CID de origem
deve se comportar como o CID de outro botão.

A alternativa ao remapeamento nativo é o *diversion*: pedir que o botão pare de
gerar o evento HID normal e passe a nos notificar via HID++, deixando o daemon
executar qualquer ação (atalho de teclado, comando, troca de workspace).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.features.base import Feature

_GET_COUNT = 0x00
_GET_CID_INFO = 0x01
_GET_CID_REPORTING = 0x02
_SET_CID_REPORTING = 0x03


class ControlID(enum.IntEnum):
    """Control IDs observados em mouses MX. Os nomes seguem a Logitech."""

    LEFT_CLICK = 0x0050
    RIGHT_CLICK = 0x0051
    MIDDLE_BUTTON = 0x0052
    BACK = 0x0053
    FORWARD = 0x0056
    MOUSE_GESTURE_BUTTON = 0x00C3
    SMART_SHIFT = 0x00C4
    VIRTUAL_GESTURE_BUTTON = 0x00D7
    #: Botão exclusivo do MX Master 4, sob a garra do polegar. É o que abre o
    #: Actions Ring no Logi Options+. Não aparece em nenhum modelo anterior.
    ACTIONS_RING = 0x01A0


class TaskID(enum.IntEnum):
    """Task IDs (ação padrão) correspondentes aos controles acima."""

    LEFT_CLICK = 0x0038
    RIGHT_CLICK = 0x0039
    MIDDLE_MOUSE_BUTTON = 0x003A
    BACK = 0x003C
    FORWARD = 0x003E
    GESTURE_BUTTON = 0x009C
    SMART_SHIFT = 0x009D
    VIRTUAL_GESTURE_BUTTON = 0x00B4
    #: Ação padrão do botão do Actions Ring no MX Master 4.
    ACTIONS_RING = 0x0109


#: Rótulos em português para exibir na interface.
CONTROL_LABELS: dict[int, str] = {
    ControlID.LEFT_CLICK: "Botão esquerdo",
    ControlID.RIGHT_CLICK: "Botão direito",
    ControlID.MIDDLE_BUTTON: "Botão do meio",
    ControlID.BACK: "Voltar",
    ControlID.FORWARD: "Avançar",
    ControlID.MOUSE_GESTURE_BUTTON: "Botão de gestos",
    ControlID.SMART_SHIFT: "SmartShift",
    ControlID.VIRTUAL_GESTURE_BUTTON: "Gesto virtual",
    ControlID.ACTIONS_RING: "Botão do Actions Ring",
}


class ControlFlag(enum.IntFlag):
    """Capacidades de um controle, vindas de getCidInfo."""

    MOUSE_BUTTON = 0x01
    FKEY = 0x02
    HOTKEY = 0x04
    FN_TOGGLE = 0x08
    #: Pode ser remapeado para outro CID.
    REPROGRAMMABLE = 0x10
    #: Pode ser desviado para notificações HID++.
    DIVERTABLE = 0x20
    PERSISTENTLY_DIVERTABLE = 0x40
    #: Não é um botão físico (ex.: gesto sintetizado).
    VIRTUAL = 0x80


class ControlExtraFlag(enum.IntFlag):
    """Capacidades adicionais, vindas do último byte de getCidInfo."""

    RAW_XY = 0x01
    FORCE_RAW_XY = 0x02
    ANALYTICS_KEY_EVENTS = 0x04


class ReportingFlag(enum.IntFlag):
    """Flags de setCidReporting.

    O protocolo usa pares "valor + válido": para alterar o bit ``DIVERT`` é
    preciso ligar também ``DIVERT_VALID``, senão o dispositivo ignora o campo.
    Isso permite mudar um aspecto sem mexer nos outros.
    """

    DIVERT = 0x01
    DIVERT_VALID = 0x02
    PERSIST = 0x04
    PERSIST_VALID = 0x08
    RAW_XY = 0x10
    RAW_XY_VALID = 0x20


@dataclass(frozen=True)
class ControlInfo:
    """Descrição estática de um botão."""

    index: int
    control_id: int
    task_id: int
    flags: ControlFlag
    position: int
    group: int
    group_mask: int
    extra_flags: ControlExtraFlag

    @property
    def label(self) -> str:
        return CONTROL_LABELS.get(self.control_id, f"Controle 0x{self.control_id:04X}")

    @property
    def is_remappable(self) -> bool:
        return bool(self.flags & ControlFlag.REPROGRAMMABLE)

    @property
    def is_divertable(self) -> bool:
        return bool(self.flags & ControlFlag.DIVERTABLE)

    def can_remap_to(self, other: ControlInfo) -> bool:
        """Este botão pode assumir o papel de ``other``?

        A regra do protocolo é de grupos: um controle só aceita ser remapeado
        para um CID cujo ``group`` esteja no ``group_mask`` dele.
        """
        return self.is_remappable and bool(self.group_mask & (1 << (other.group - 1)))


@dataclass(frozen=True)
class ControlReporting:
    """Configuração atual de um botão."""

    control_id: int
    diverted: bool
    persist: bool
    raw_xy: bool
    #: CID que este botão está executando (0 = comportamento padrão).
    remapped_to: int

    @property
    def is_remapped(self) -> bool:
        return self.remapped_to not in (0, self.control_id)


class ReprogControls(Feature):
    """Enumeração e remapeamento dos botões."""

    FEATURE_ID = int(FeatureID.REPROG_CONTROLS_V4)

    def get_count(self) -> int:
        return self._call(_GET_COUNT)[0]

    def get_control_info(self, index: int) -> ControlInfo:
        response = self._call(_GET_CID_INFO, bytes([index]))
        return ControlInfo(
            index=index,
            control_id=int.from_bytes(response[0:2], "big"),
            task_id=int.from_bytes(response[2:4], "big"),
            flags=ControlFlag(response[4]),
            position=response[5],
            group=response[6],
            group_mask=response[7],
            extra_flags=ControlExtraFlag(response[8] & 0x07),
        )

    def list_controls(self) -> list[ControlInfo]:
        return [self.get_control_info(i) for i in range(self.get_count())]

    def get_reporting(self, control_id: int) -> ControlReporting:
        response = self._call(_GET_CID_REPORTING, control_id.to_bytes(2, "big"))
        flags = response[2]
        return ControlReporting(
            control_id=int.from_bytes(response[0:2], "big"),
            diverted=bool(flags & ReportingFlag.DIVERT),
            persist=bool(flags & ReportingFlag.PERSIST),
            raw_xy=bool(flags & ReportingFlag.RAW_XY),
            remapped_to=int.from_bytes(response[3:5], "big"),
        )

    def set_reporting(
        self,
        control_id: int,
        *,
        diverted: bool | None = None,
        persist: bool | None = None,
        raw_xy: bool | None = None,
        remap_to: int | None = None,
    ) -> ControlReporting:
        """Configura um botão, mexendo só nos aspectos informados.

        ``remap_to`` recebe o CID do botão cujo comportamento queremos, ou o
        próprio ``control_id`` para voltar ao padrão.
        """
        flags = ReportingFlag(0)
        if diverted is not None:
            flags |= ReportingFlag.DIVERT_VALID
            if diverted:
                flags |= ReportingFlag.DIVERT
        if persist is not None:
            flags |= ReportingFlag.PERSIST_VALID
            if persist:
                flags |= ReportingFlag.PERSIST
        if raw_xy is not None:
            flags |= ReportingFlag.RAW_XY_VALID
            if raw_xy:
                flags |= ReportingFlag.RAW_XY

        target = control_id if remap_to is None else remap_to
        self._call(
            _SET_CID_REPORTING,
            control_id.to_bytes(2, "big") + bytes([int(flags)]) + target.to_bytes(2, "big"),
        )
        return self.get_reporting(control_id)

    def reset(self, control_id: int) -> ControlReporting:
        """Devolve um botão ao comportamento de fábrica."""
        return self.set_reporting(
            control_id, diverted=False, persist=False, raw_xy=False, remap_to=control_id
        )
