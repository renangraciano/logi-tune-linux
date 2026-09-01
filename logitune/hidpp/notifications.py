# SPDX-License-Identifier: GPL-3.0-or-later
"""Recepção de notificações assíncronas do dispositivo.

Além de responder ao que perguntamos, o dispositivo empurra eventos por conta
própria: bateria que mudou, roda que trocou de modo e — o que mais interessa
aqui — botões que foram *desviados* e agora reportam por HID++ em vez de
gerar o clique normal.

Uma notificação se distingue de uma resposta pelo software ID zerado: só as
requisições carregam o nosso ID.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

from logitune.hidpp.constants import (
    ERROR_FEATURE_INDEX,
    ERROR_SUB_ID_HIDPP10,
    FeatureID,
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
#: Função 0x01: divertedRawXYEvent, o deslocamento enquanto o botão está preso.
_DIVERTED_RAW_XY_EVENT = 0x01


@dataclass(frozen=True)
class RawMovement:
    """Deslocamento do mouse enquanto um botão desviado está pressionado.

    Só chega quando o botão foi desviado **e** marcado com ``raw_xy``. É a
    matéria-prima dos gestos: sem isto não há como distinguir um toque de um
    arrasto, porque o dispositivo não conta nada sobre o movimento.

    As unidades são contagens do sensor, não pixels: elas não dependem da
    aceleração do ponteiro nem do DPI configurado.
    """

    dx: int
    dy: int

    @property
    def distance_squared(self) -> int:
        """Distância ao quadrado, para comparar com um limiar sem raiz."""
        return self.dx * self.dx + self.dy * self.dy


class ThumbWheelStatus(enum.IntEnum):
    """Em que ponto do giro este evento chegou."""

    INACTIVE = 0
    START = 1
    ACTIVE = 2
    STOP = 3


@dataclass(frozen=True)
class ThumbWheelEvent:
    """Giro da roda do polegar, quando ela está desviada para o software.

    O layout foi lido do hardware, não da documentação — a Logitech não
    publica o formato do evento da 0x2150. Medido num MX Master 4 com firmware
    RBM 27.03.B0019, sobre algumas centenas de eventos::

        ff f8 00 07 02 02   →  delta -8, t=7,  ativo
        00 01 00 00 01 02   →  delta +1, t=0,  começou
        00 00 00 00 03 00   →  delta  0,       parou

    Os dois primeiros bytes são o deslocamento com sinal, os dois seguintes um
    carimbo de tempo, e o quinto o estado do giro. O sexto carrega bandeiras
    cujo significado este dispositivo não permite confirmar: o ``getInfo`` dele
    diz não ter sensor de toque nem de proximidade, então elas ficam cruas em
    vez de ganharem um nome inventado.

    **O deslocamento não vem em detents.** Ele vem na resolução desviada, que
    no MX Master 4 é 120 por volta contra 20 nativos — seis unidades por
    detent. Tratar cada unidade como um detent faria um giro dar seis vezes
    mais passos do que a mão pediu.
    """

    #: Unidades giradas desde o último evento, na resolução desviada.
    delta: int
    status: ThumbWheelStatus = ThumbWheelStatus.ACTIVE
    #: Carimbo de tempo do dispositivo, em unidades não documentadas.
    timestamp: int = 0
    #: Byte de bandeiras, sem interpretação confirmada neste modelo.
    flags: int = 0


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

    def _build(self, report: bytes) -> Notification:
        self._resolve_indexes()
        feature_index = report[2]
        return Notification(
            device_index=report[1],
            feature_index=feature_index,
            function=(report[3] & 0xF0) >> 4,
            data=report[4:],
            feature_id=self._index_to_feature.get(feature_index),
        )

    def poll(self, timeout: float = 1.0) -> Notification | None:
        """Espera a próxima notificação, ou ``None`` se nada chegar.

        A fila do dispositivo vem primeiro: ela guarda o que chegou enquanto
        uma requisição estava em curso. Sem consumi-la aqui, um comando ao
        mouse — vibrar para confirmar um gesto, por exemplo — engoliria os
        eventos que chegaram junto.
        """
        while True:
            report = self.device.take_stashed()
            if report is None:
                break
            if self._is_notification(report):
                return self._build(report)

        report = self.device.transport.read(timeout)
        if report is None or not self._is_notification(report):
            return None
        return self._build(report)

    def as_raw_movement(self, notification: Notification) -> RawMovement | None:
        """Traduz uma notificação de movimento bruto.

        Os dois eixos vêm como inteiros de 16 bits **com sinal**: ler sem
        sinal transformaria todo movimento para a esquerda ou para cima em um
        deslocamento enorme na direção oposta.
        """
        if notification.feature_id != int(FeatureID.REPROG_CONTROLS_V4):
            return None
        if notification.function != _DIVERTED_RAW_XY_EVENT:
            return None

        data = notification.data
        if len(data) < 4:
            return None
        return RawMovement(
            dx=int.from_bytes(data[0:2], "big", signed=True),
            dy=int.from_bytes(data[2:4], "big", signed=True),
        )

    def as_thumbwheel_event(self, notification: Notification) -> ThumbWheelEvent | None:
        """Traduz uma notificação de giro da roda do polegar."""
        if notification.feature_id != int(FeatureID.THUMB_WHEEL):
            return None

        data = notification.data
        if len(data) < 2:
            return None
        # Com sinal, pelo mesmo motivo do movimento bruto: girar para um lado
        # daria um número enorme no sentido oposto se lido sem sinal.
        try:
            status = ThumbWheelStatus(data[4]) if len(data) > 4 else ThumbWheelStatus.ACTIVE
        except ValueError:
            status = ThumbWheelStatus.ACTIVE
        return ThumbWheelEvent(
            delta=int.from_bytes(data[0:2], "big", signed=True),
            status=status,
            timestamp=int.from_bytes(data[2:4], "big") if len(data) > 3 else 0,
            flags=data[5] if len(data) > 5 else 0,
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
