"""Recepção de notificações assíncronas do dispositivo.

Além de responder ao que perguntamos, o dispositivo empurra eventos por conta
própria: bateria que mudou, roda que trocou de modo e — o que mais interessa
aqui — botões que foram *desviados* e agora reportam por HID++ em vez de
gerar o clique normal.

Uma notificação se distingue de uma resposta pelo software ID zerado: só as
requisições carregam o nosso ID.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from logitune.hidpp.constants import (
    ERROR_FEATURE_INDEX,
    ERROR_SUB_ID_HIDPP10,
    FeatureID,
    ReportType,
)
from logitune.hidpp.device import Hidpp20Device

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notification:
    """Um evento vindo do dispositivo."""

    device_index: int
    feature_index: int
    function: int
    data: bytes
    #: Feature ID resolvido, quando conhecemos o índice.
    feature_id: int | None = None

    @property
    def feature_name(self) -> str:
        if self.feature_id is None:
            return f"índice {self.feature_index}"
        try:
            return FeatureID(self.feature_id).name
        except ValueError:
            return f"0x{self.feature_id:04X}"

    def __str__(self) -> str:
        return (
            f"{self.feature_name} f{self.function} "
            f"[{self.data[:12].hex(' ')}]"
        )


@dataclass(frozen=True)
class ButtonEvent:
    """Estado dos botões desviados em um instante.

    O dispositivo não manda "pressionou" e "soltou": ele manda a lista do que
    está pressionado agora. Comparar com a lista anterior é o que produz as
    bordas de subida e descida.
    """

    pressed: frozenset[int]
    #: Botões que acabaram de ser pressionados.
    just_pressed: frozenset[int] = field(default_factory=frozenset)
    #: Botões que acabaram de ser soltos.
    just_released: frozenset[int] = field(default_factory=frozenset)


#: Função 0x00 da 0x1B04 em modo notificação: divertedButtonsEvent.
_DIVERTED_BUTTONS_EVENT = 0x00


class NotificationListener:
    """Lê notificações de um dispositivo e traduz eventos de botão."""

    def __init__(self, device: Hidpp20Device) -> None:
        self.device = device
        self._pressed: frozenset[int] = frozenset()
        self._index_to_feature: dict[int, int] = {}

    def _resolve_indexes(self) -> None:
        if self._index_to_feature:
            return
        for info in self.device.feature_table():
            self._index_to_feature[info.index] = info.feature_id

    def _is_notification(self, report: bytes) -> bool:
        if len(report) < 4:
            return False
        if report[1] != self.device.device_index:
            return False
        if report[2] in (ERROR_FEATURE_INDEX, ERROR_SUB_ID_HIDPP10):
            return False
        # Software ID zero: ninguém pediu isso, o dispositivo mandou sozinho.
        return report[3] & 0x0F == 0

    def poll(self, timeout: float = 1.0) -> Notification | None:
        """Espera a próxima notificação, ou ``None`` se nada chegar."""
        report = self.device.transport.read(timeout)
        if report is None or not self._is_notification(report):
            return None

        self._resolve_indexes()
        feature_index = report[2]
        return Notification(
            device_index=report[1],
            feature_index=feature_index,
            function=(report[3] & 0xF0) >> 4,
            data=report[4:],
            feature_id=self._index_to_feature.get(feature_index),
        )

    def as_button_event(self, notification: Notification) -> ButtonEvent | None:
        """Traduz uma notificação de botões desviados em transições."""
        if notification.feature_id != int(FeatureID.REPROG_CONTROLS_V4):
            return None
        if notification.function != _DIVERTED_BUTTONS_EVENT:
            return None

        data = notification.data
        pressed = {
            cid
            for cid in (
                int.from_bytes(data[i : i + 2], "big") for i in range(0, min(8, len(data)), 2)
            )
            if cid
        }
        pressed_set = frozenset(pressed)
        event = ButtonEvent(
            pressed=pressed_set,
            just_pressed=pressed_set - self._pressed,
            just_released=self._pressed - pressed_set,
        )
        self._pressed = pressed_set
        return event
