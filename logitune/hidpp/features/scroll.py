# SPDX-License-Identifier: GPL-3.0-or-later
"""Features de rolagem: 0x2111 SmartShift, 0x2121 HiRes Wheel, 0x2150 Thumb Wheel."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.features.base import Feature
from logitune.i18n import _

# --- 0x2111 SMART SHIFT ENHANCED -------------------------------------

_SS_GET_CAPABILITIES = 0x00
_SS_GET_RATCHET_MODE = 0x01
_SS_SET_RATCHET_MODE = 0x02


class WheelMode(enum.IntEnum):
    """Modo da roda principal."""

    #: Não altera o modo (usado em escritas parciais).
    UNCHANGED = 0x00
    #: Roda livre: gira sem resistência, rolagem por inércia.
    FREESPIN = 0x01
    #: Ratchet: roda travada, com os "cliques" mecânicos.
    RATCHET = 0x02

    @property
    def label(self) -> str:
        return {
            WheelMode.UNCHANGED: _("unchanged"),
            WheelMode.FREESPIN: _("freewheel"),
            WheelMode.RATCHET: _("ratchet"),
        }[self]


@dataclass(frozen=True)
class SmartShiftState:
    """Estado do SmartShift.

    ``auto_disengage`` é o ponto de virada: com que velocidade de rolagem a
    roda solta o ratchet e entra em roda livre. Valores baixos soltam fácil;
    o máximo (:data:`SmartShift.NEVER_DISENGAGE`) mantém o ratchet sempre.
    """

    mode: WheelMode
    auto_disengage: int
    default_auto_disengage: int

    @property
    def smartshift_enabled(self) -> bool:
        return self.auto_disengage < SmartShift.NEVER_DISENGAGE


class SmartShift(Feature):
    """Controle do ponto de troca entre ratchet e roda livre."""

    FEATURE_ID = int(FeatureID.SMART_SHIFT_ENHANCED)

    #: Valor máximo do ponto de virada. No máximo, o ratchet nunca é
    #: solto automaticamente. O MX Master 4 vem de fábrica em 70, acima do
    #: limite de 50 que ferramentas antigas assumiam para a feature 0x2110.
    NEVER_DISENGAGE = 255

    def get_state(self) -> SmartShiftState:
        response = self._call(_SS_GET_RATCHET_MODE)
        try:
            mode = WheelMode(response[0])
        except ValueError:
            mode = WheelMode.UNCHANGED
        return SmartShiftState(
            mode=mode,
            auto_disengage=response[1],
            default_auto_disengage=response[2],
        )

    def set_state(
        self,
        *,
        mode: WheelMode | None = None,
        auto_disengage: int | None = None,
    ) -> SmartShiftState:
        """Altera modo e/ou ponto de virada, preservando o que não for passado."""
        current = self.get_state()
        target_mode = current.mode if mode is None else mode
        target_point = (
            current.auto_disengage
            if auto_disengage is None
            else max(1, min(self.NEVER_DISENGAGE, auto_disengage))
        )
        self._call(
            _SS_SET_RATCHET_MODE,
            bytes([int(target_mode), target_point, current.default_auto_disengage]),
        )
        return self.get_state()


# --- 0x2121 HIRES WHEEL ----------------------------------------------

_HW_GET_CAPABILITY = 0x00
_HW_GET_MODE = 0x01
_HW_SET_MODE = 0x02
_HW_GET_RATCHET_STATE = 0x03

_MODE_DIVERTED = 0x01
_MODE_HIGH_RESOLUTION = 0x02
_MODE_INVERTED = 0x04


@dataclass(frozen=True)
class HiResWheelState:
    #: Eventos vão para o HID++ (nós) em vez do driver de mouse do kernel.
    diverted: bool
    high_resolution: bool
    inverted: bool


class HiResWheel(Feature):
    """Rolagem de alta resolução e inversão de direção da roda principal."""

    FEATURE_ID = int(FeatureID.HIRES_WHEEL)

    def get_multiplier(self) -> int:
        """Quantos ticks de alta resolução equivalem a um clique de ratchet."""
        return self._call(_HW_GET_CAPABILITY)[0]

    def get_state(self) -> HiResWheelState:
        flags = self._call(_HW_GET_MODE)[0]
        return HiResWheelState(
            diverted=bool(flags & _MODE_DIVERTED),
            high_resolution=bool(flags & _MODE_HIGH_RESOLUTION),
            inverted=bool(flags & _MODE_INVERTED),
        )

    def set_state(
        self,
        *,
        diverted: bool | None = None,
        high_resolution: bool | None = None,
        inverted: bool | None = None,
    ) -> HiResWheelState:
        current = self.get_state()
        flags = 0
        if current.diverted if diverted is None else diverted:
            flags |= _MODE_DIVERTED
        if current.high_resolution if high_resolution is None else high_resolution:
            flags |= _MODE_HIGH_RESOLUTION
        if current.inverted if inverted is None else inverted:
            flags |= _MODE_INVERTED
        self._call(_HW_SET_MODE, bytes([flags]))
        return self.get_state()

    def get_ratchet_engaged(self) -> bool:
        """A roda está em ratchet agora (``True``) ou em roda livre?"""
        return bool(self._call(_HW_GET_RATCHET_STATE)[0])


# --- 0x2150 THUMB WHEEL ----------------------------------------------

_TW_GET_INFO = 0x00
_TW_GET_STATUS = 0x01
_TW_SET_REPORTING = 0x02


@dataclass(frozen=True)
class ThumbWheelState:
    diverted: bool
    inverted: bool


@dataclass(frozen=True)
class ThumbWheelInfo:
    native_resolution: int
    diverted_resolution: int
    #: A roda do polegar sabe reportar toque (proximidade) além de rotação.
    has_touch: bool
    has_proximity: bool


class ThumbWheel(Feature):
    """Roda lateral do polegar (rolagem horizontal)."""

    FEATURE_ID = int(FeatureID.THUMB_WHEEL)

    def get_info(self) -> ThumbWheelInfo:
        response = self._call(_TW_GET_INFO)
        capabilities = response[4] if len(response) > 4 else 0
        return ThumbWheelInfo(
            native_resolution=int.from_bytes(response[0:2], "big"),
            diverted_resolution=int.from_bytes(response[2:4], "big"),
            has_touch=bool(capabilities & 0x01),
            has_proximity=bool(capabilities & 0x02),
        )

    def get_state(self) -> ThumbWheelState:
        response = self._call(_TW_GET_STATUS)
        return ThumbWheelState(
            diverted=bool(response[0]),
            inverted=bool(response[1]),
        )

    def set_state(
        self, *, diverted: bool | None = None, inverted: bool | None = None
    ) -> ThumbWheelState:
        current = self.get_state()
        target_diverted = current.diverted if diverted is None else diverted
        target_inverted = current.inverted if inverted is None else inverted
        self._call(_TW_SET_REPORTING, bytes([int(target_diverted), int(target_inverted)]))
        return self.get_state()
