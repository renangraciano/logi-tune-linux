# SPDX-License-Identifier: GPL-3.0-or-later
"""Diálogo HID++ 2.0 com um dispositivo Logitech.

Um :class:`Hidpp20Device` representa um periférico alcançável por um nó
hidraw — seja diretamente (USB/Bluetooth) ou através de um receiver, caso em
que o ``device_index`` identifica qual dos dispositivos pareados queremos.

O ciclo é sempre o mesmo: traduzir um *feature ID* (0x2201) para o *índice de
feature* daquele dispositivo específico (que varia de modelo para modelo),
montar o report e casar a resposta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from logitune.hidpp.constants import (
    ERROR_FEATURE_INDEX,
    ERROR_SUB_ID_HIDPP10,
    REPORT_SIZE,
    ROOT_FEATURE_INDEX,
    SOFTWARE_ID,
    FeatureFlag,
    FeatureID,
    Hidpp20Error,
    ReportType,
)
from logitune.hidpp.transport import HidrawTransport

logger = logging.getLogger(__name__)

#: Função getFeature da feature ROOT.
_ROOT_GET_FEATURE = 0x00
#: Função getCount da feature FEATURE_SET.
_FEATURESET_GET_COUNT = 0x00
#: Função getFeatureID da feature FEATURE_SET.
_FEATURESET_GET_FEATURE_ID = 0x01


class HidppError(Exception):
    """Erro devolvido pelo dispositivo em resposta a uma requisição."""

    def __init__(self, code: int, feature_id: int | None = None, function: int | None = None):
        self.code = code
        self.feature_id = feature_id
        self.function = function
        try:
            name = Hidpp20Error(code).name
        except ValueError:
            name = f"0x{code:02X}"
        where = ""
        if feature_id is not None:
            where = f" (feature 0x{feature_id:04X}, função 0x{function or 0:02X})"
        super().__init__(f"O dispositivo respondeu com o erro {name}{where}")


class FeatureNotSupported(HidppError):
    """O dispositivo não implementa a feature pedida."""

    def __init__(self, feature_id: int):
        self.feature_id = feature_id
        Exception.__init__(
            self, f"O dispositivo não suporta a feature 0x{feature_id:04X}"
        )
        self.code = int(Hidpp20Error.UNSUPPORTED)
        self.function = None


class NoResponse(TimeoutError):
    """O dispositivo não respondeu dentro do tempo previsto."""


@dataclass(frozen=True)
class FeatureInfo:
    """Uma entrada da tabela de features do dispositivo."""

    index: int
    feature_id: int
    flags: FeatureFlag
    version: int

    @property
    def name(self) -> str:
        try:
            return FeatureID(self.feature_id).name
        except ValueError:
            return f"UNKNOWN_{self.feature_id:04X}"

    @property
    def is_hidden(self) -> bool:
        return bool(self.flags & FeatureFlag.HIDDEN)


class Hidpp20Device:
    """Um dispositivo que fala HID++ 2.0."""

    def __init__(
        self,
        transport: HidrawTransport,
        device_index: int,
        *,
        timeout: float = 1.0,
        retries: int = 2,
    ) -> None:
        self.transport = transport
        self.device_index = device_index
        self.timeout = timeout
        self.retries = retries
        self._feature_index: dict[int, int | None] = {int(FeatureID.ROOT): ROOT_FEATURE_INDEX}
        self._feature_table: list[FeatureInfo] | None = None

    # -- requisições ---------------------------------------------------

    def _build_report(
        self, report_type: ReportType, feature_index: int, function: int, params: bytes
    ) -> bytes:
        size = REPORT_SIZE[report_type]
        payload = bytearray(size)
        payload[0] = int(report_type)
        payload[1] = self.device_index
        payload[2] = feature_index
        payload[3] = ((function & 0x0F) << 4) | SOFTWARE_ID
        payload[4 : 4 + len(params)] = params
        return bytes(payload)

    def _matches(self, response: bytes, feature_index: int, function: int) -> bool:
        """A resposta é para *esta* requisição?

        Descarta notificações e o tráfego de outros processos falando com o
        mesmo dispositivo, casando índice do dispositivo, feature e o par
        função+software ID.
        """
        if len(response) < 4 or response[1] != self.device_index:
            return False

        expected_addr = ((function & 0x0F) << 4) | SOFTWARE_ID

        # Erro HID++ 2.0: o índice de feature vem como 0xFF e os dois bytes
        # seguintes repetem a requisição que falhou.
        if response[0] == ReportType.LONG and response[2] == ERROR_FEATURE_INDEX:
            return len(response) >= 5 and response[3] == feature_index and response[4] == expected_addr

        # Erro HID++ 1.0.
        if response[0] == ReportType.SHORT and response[2] == ERROR_SUB_ID_HIDPP10:
            return len(response) >= 5 and response[3] == feature_index and response[4] == expected_addr

        return response[2] == feature_index and response[3] == expected_addr

    def _raise_if_error(self, response: bytes, feature_id: int | None, function: int) -> None:
        if response[0] == ReportType.LONG and response[2] == ERROR_FEATURE_INDEX:
            raise HidppError(response[5], feature_id, function)
        if response[0] == ReportType.SHORT and response[2] == ERROR_SUB_ID_HIDPP10:
            raise HidppError(response[5], feature_id, function)

    def request(
        self,
        feature_index: int,
        function: int,
        params: bytes = b"",
        *,
        feature_id: int | None = None,
        report_type: ReportType = ReportType.LONG,
    ) -> bytes:
        """Chama uma função de feature pelo índice e devolve os parâmetros da resposta."""
        request = self._build_report(report_type, feature_index, function, params)

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self.transport.write(request)

            deadline_reads = 0
            while deadline_reads < 32:
                response = self.transport.read(self.timeout)
                if response is None:
                    break
                deadline_reads += 1
                if not self._matches(response, feature_index, function):
                    continue
                self._raise_if_error(response, feature_id, function)
                return response[4:]

            last_error = NoResponse(
                f"Sem resposta para a feature 0x{(feature_id or 0):04X} "
                f"função 0x{function:02X} (tentativa {attempt + 1})"
            )
            logger.debug("%s", last_error)

        raise last_error or NoResponse("Sem resposta do dispositivo")

    def call(
        self,
        feature_id: int,
        function: int,
        params: bytes = b"",
        *,
        report_type: ReportType = ReportType.LONG,
    ) -> bytes:
        """Chama uma função pelo *feature ID*, resolvendo o índice antes."""
        index = self.feature_index(feature_id)
        if index is None:
            raise FeatureNotSupported(feature_id)
        return self.request(
            index, function, params, feature_id=feature_id, report_type=report_type
        )

    # -- descoberta de features ----------------------------------------

    def feature_index(self, feature_id: int) -> int | None:
        """Índice da feature neste dispositivo, ou ``None`` se não houver."""
        if feature_id in self._feature_index:
            return self._feature_index[feature_id]

        response = self.request(
            ROOT_FEATURE_INDEX,
            _ROOT_GET_FEATURE,
            feature_id.to_bytes(2, "big"),
            feature_id=int(FeatureID.ROOT),
        )
        index = response[0] if response else 0
        # ROOT.getFeature devolve índice 0 para features ausentes.
        resolved = index if index else None
        self._feature_index[feature_id] = resolved
        return resolved

    def supports(self, feature_id: int) -> bool:
        return self.feature_index(feature_id) is not None

    def feature_table(self, *, refresh: bool = False) -> list[FeatureInfo]:
        """Enumera todas as features do dispositivo via FEATURE_SET (0x0001)."""
        if self._feature_table is not None and not refresh:
            return self._feature_table

        featureset_index = self.feature_index(int(FeatureID.FEATURE_SET))
        if featureset_index is None:
            self._feature_table = []
            return self._feature_table

        count = self.request(
            featureset_index, _FEATURESET_GET_COUNT, feature_id=int(FeatureID.FEATURE_SET)
        )[0]

        table: list[FeatureInfo] = []
        for index in range(count + 1):  # +1: a feature ROOT ocupa o índice 0
            response = self.request(
                featureset_index,
                _FEATURESET_GET_FEATURE_ID,
                bytes([index]),
                feature_id=int(FeatureID.FEATURE_SET),
            )
            feature_id = int.from_bytes(response[0:2], "big")
            flags = FeatureFlag(response[2] & 0xF8) if len(response) > 2 else FeatureFlag(0)
            version = response[3] if len(response) > 3 else 0
            table.append(
                FeatureInfo(index=index, feature_id=feature_id, flags=flags, version=version)
            )
            self._feature_index.setdefault(feature_id, index)

        self._feature_table = table
        return table
