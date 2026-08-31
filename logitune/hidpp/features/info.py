# SPDX-License-Identifier: GPL-3.0-or-later
"""Features de identificação: 0x0005 DEVICE NAME e 0x0007 DEVICE FRIENDLY NAME."""

from __future__ import annotations

import enum

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.features.base import Feature

_GET_NAME_COUNT = 0x00
_GET_NAME = 0x01
_GET_DEVICE_TYPE = 0x02

_FRIENDLY_GET_COUNT = 0x00
_FRIENDLY_GET_NAME = 0x01


class DeviceType(enum.IntEnum):
    KEYBOARD = 0x00
    REMOTE_CONTROL = 0x01
    NUMPAD = 0x02
    MOUSE = 0x03
    TOUCHPAD = 0x04
    TRACKBALL = 0x05
    PRESENTER = 0x06
    RECEIVER = 0x07
    HEADSET = 0x08
    WEBCAM = 0x09
    STEERING_WHEEL = 0x0A
    JOYSTICK = 0x0B
    GAMEPAD = 0x0C
    DOCK = 0x0D
    SPEAKER = 0x0E
    MICROPHONE = 0x0F

    @property
    def label(self) -> str:
        return {
            DeviceType.KEYBOARD: "teclado",
            DeviceType.MOUSE: "mouse",
            DeviceType.TOUCHPAD: "touchpad",
            DeviceType.TRACKBALL: "trackball",
            DeviceType.RECEIVER: "receptor",
            DeviceType.HEADSET: "headset",
        }.get(self, self.name.lower())


def _read_string(
    feature: Feature, count_function: int, read_function: int, *, echo_bytes: int = 0
) -> str:
    """Lê uma string que o dispositivo entrega em pedaços de ~15 bytes.

    ``echo_bytes`` é quantos bytes do começo de cada resposta são o eco dos
    parâmetros da requisição, e portanto não fazem parte do texto. A feature
    0x0005 não ecoa nada; a 0x0007 devolve o offset pedido.
    """
    length = feature._call(count_function)[0]
    chunks: list[bytes] = []
    offset = 0
    while offset < length:
        response = feature._call(read_function, bytes([offset]))
        chunk = response[echo_bytes:]
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)[:length].decode("utf-8", errors="replace").rstrip("\x00")


class DeviceName(Feature):
    """Nome de modelo e tipo do dispositivo."""

    FEATURE_ID = int(FeatureID.DEVICE_NAME)

    def get_name(self) -> str:
        return _read_string(self, _GET_NAME_COUNT, _GET_NAME)

    def get_type(self) -> DeviceType:
        try:
            return DeviceType(self._call(_GET_DEVICE_TYPE)[0])
        except ValueError:
            return DeviceType.MOUSE


class DeviceFriendlyName(Feature):
    """Nome amigável, editável pelo usuário no software da Logitech."""

    FEATURE_ID = int(FeatureID.DEVICE_FRIENDLY_NAME)

    def get_name(self) -> str:
        return _read_string(
            self, _FRIENDLY_GET_COUNT, _FRIENDLY_GET_NAME, echo_bytes=1
        )
