"""Base comum para os wrappers de feature HID++."""

from __future__ import annotations

from logitune.hidpp.device import Hidpp20Device
from logitune.hidpp.constants import ReportType


class Feature:
    """Envelopa uma feature HID++ 2.0 de um dispositivo.

    Subclasses declaram ``FEATURE_ID`` e expõem métodos com nomes de domínio
    (``get_dpi``, ``set_dpi``) em vez de números de função.
    """

    FEATURE_ID: int

    def __init__(self, device: Hidpp20Device) -> None:
        self.device = device

    @property
    def available(self) -> bool:
        """O dispositivo implementa esta feature?"""
        return self.device.supports(self.FEATURE_ID)

    @property
    def version(self) -> int:
        """Versão da feature neste dispositivo (0 se ausente)."""
        for info in self.device.feature_table():
            if info.feature_id == self.FEATURE_ID:
                return info.version
        return 0

    def _call(
        self,
        function: int,
        params: bytes = b"",
        *,
        report_type: ReportType = ReportType.LONG,
    ) -> bytes:
        return self.device.call(self.FEATURE_ID, function, params, report_type=report_type)
