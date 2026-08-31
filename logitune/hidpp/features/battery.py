"""Feature 0x1004 — UNIFIED BATTERY."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.features.base import Feature

_GET_CAPABILITIES = 0x00
_GET_STATUS = 0x01


class ChargingStatus(enum.IntEnum):
    DISCHARGING = 0x00
    CHARGING = 0x01
    CHARGING_SLOW = 0x02
    CHARGE_COMPLETE = 0x03
    CHARGING_ERROR = 0x04

    @property
    def label(self) -> str:
        return {
            ChargingStatus.DISCHARGING: "descarregando",
            ChargingStatus.CHARGING: "carregando",
            ChargingStatus.CHARGING_SLOW: "carregamento lento",
            ChargingStatus.CHARGE_COMPLETE: "carga completa",
            ChargingStatus.CHARGING_ERROR: "erro de carregamento",
        }[self]


class BatteryLevel(enum.IntFlag):
    """Níveis discretos que o dispositivo sabe reportar."""

    CRITICAL = 0x01
    LOW = 0x02
    GOOD = 0x04
    FULL = 0x08


@dataclass(frozen=True)
class BatteryStatus:
    """Estado atual da bateria."""

    #: Percentual de carga (0-100), ou ``None`` se o device só reporta níveis.
    percentage: int | None
    level: BatteryLevel
    charging: ChargingStatus
    external_power: bool

    @property
    def is_charging(self) -> bool:
        return self.charging in (
            ChargingStatus.CHARGING,
            ChargingStatus.CHARGING_SLOW,
        )

    @property
    def is_low(self) -> bool:
        if self.percentage is not None:
            return self.percentage <= 20 and not self.is_charging
        return bool(self.level & (BatteryLevel.LOW | BatteryLevel.CRITICAL))


@dataclass(frozen=True)
class BatteryCapabilities:
    supported_levels: BatteryLevel
    #: O dispositivo reporta percentual exato além dos níveis discretos.
    has_percentage: bool
    rechargeable: bool


class UnifiedBattery(Feature):
    """Leitura de carga da bateria."""

    FEATURE_ID = int(FeatureID.UNIFIED_BATTERY)

    def get_capabilities(self) -> BatteryCapabilities:
        response = self._call(_GET_CAPABILITIES)
        levels = BatteryLevel(response[0] & 0x0F)
        flags = response[1]
        return BatteryCapabilities(
            supported_levels=levels,
            has_percentage=bool(flags & 0x02),
            rechargeable=bool(flags & 0x01),
        )

    def get_status(self) -> BatteryStatus:
        response = self._call(_GET_STATUS)
        percentage: int | None = response[0]
        if percentage is not None and not 0 <= percentage <= 100:
            percentage = None

        try:
            charging = ChargingStatus(response[2])
        except ValueError:
            charging = ChargingStatus.DISCHARGING

        return BatteryStatus(
            percentage=percentage,
            level=BatteryLevel(response[1] & 0x0F),
            charging=charging,
            external_power=bool(response[3] & 0x01) if len(response) > 3 else False,
        )
