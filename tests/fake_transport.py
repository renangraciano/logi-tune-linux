# SPDX-License-Identifier: GPL-3.0-or-later
"""Um transporte falso que responde como um dispositivo HID++ 2.0.

Permite exercitar a stack inteira sem hardware: os testes descrevem quais
features o "dispositivo" tem e o que cada função devolve.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from logitune.hidpp.constants import (
    ERROR_FEATURE_INDEX,
    REPORT_SIZE,
    SOFTWARE_ID,
    Hidpp20Error,
    ReportType,
)

_ROOT_GET_FEATURE = 0x00
_FEATURESET_GET_COUNT = 0x00
_FEATURESET_GET_FEATURE_ID = 0x01


class FakeTransport:
    """Responde a requisições HID++ a partir de uma tabela declarativa.

    ``features`` mapeia feature ID para índice. ``responses`` mapeia
    ``(feature_id, função)`` para os bytes de resposta (sem o cabeçalho).
    """

    def __init__(
        self,
        features: dict[int, int],
        responses: dict[tuple[int, int], bytes] | None = None,
        *,
        device_index: int = 1,
        transient_failures: dict[tuple[int, int], tuple[int, int]] | None = None,
    ) -> None:
        self.path = Path("/dev/hidraw-fake")
        self.features = dict(features)
        self.responses = dict(responses or {})
        self.device_index = device_index
        #: Tudo que foi escrito, para os testes verificarem o que saiu.
        self.written: list[bytes] = []
        #: Simula um dispositivo ocupado: mapeia (feature, função) para
        #: (código de erro, quantas vezes falhar antes de responder direito).
        self.transient_failures = dict(transient_failures or {})
        self._pending: deque[bytes] = deque()
        self._index_to_feature = {index: fid for fid, index in self.features.items()}

    # -- interface usada por Hidpp20Device -----------------------------

    def open(self) -> None:  # pragma: no cover - nada a fazer
        pass

    def close(self) -> None:  # pragma: no cover - nada a fazer
        pass

    def write(self, data: bytes) -> None:
        self.written.append(data)
        self._pending.append(self._respond(data))

    def read(self, timeout: float = 0.5) -> bytes | None:
        return self._pending.popleft() if self._pending else None

    # -- simulação -----------------------------------------------------

    def _reply(self, request: bytes, payload: bytes) -> bytes:
        report = bytearray(REPORT_SIZE[ReportType.LONG])
        report[0] = int(ReportType.LONG)
        report[1] = request[1]
        report[2] = request[2]
        report[3] = request[3]
        report[4 : 4 + len(payload)] = payload[: len(report) - 4]
        return bytes(report)

    def _error(self, request: bytes, code: Hidpp20Error) -> bytes:
        report = bytearray(REPORT_SIZE[ReportType.LONG])
        report[0] = int(ReportType.LONG)
        report[1] = request[1]
        report[2] = ERROR_FEATURE_INDEX
        report[3] = request[2]
        report[4] = request[3]
        report[5] = int(code)
        return bytes(report)

    def _respond(self, request: bytes) -> bytes:
        feature_index = request[2]
        function = (request[3] & 0xF0) >> 4
        params = request[4:]

        if feature_index == 0x00 and function == _ROOT_GET_FEATURE:
            wanted = int.from_bytes(params[0:2], "big")
            return self._reply(request, bytes([self.features.get(wanted, 0)]))

        feature_id = self._index_to_feature.get(feature_index)
        if feature_id is None:
            return self._error(request, Hidpp20Error.INVALID_FEATURE_INDEX)

        if feature_id == 0x0001:  # FEATURE_SET
            if function == _FEATURESET_GET_COUNT:
                return self._reply(request, bytes([len(self.features) - 1]))
            if function == _FEATURESET_GET_FEATURE_ID:
                index = params[0]
                target = self._index_to_feature.get(index, 0)
                return self._reply(request, target.to_bytes(2, "big") + bytes([0x00, 0x00]))

        pendente = self.transient_failures.get((feature_id, function))
        if pendente and pendente[1] > 0:
            code, restantes = pendente
            self.transient_failures[(feature_id, function)] = (code, restantes - 1)
            return self._error(request, code)

        payload = self.responses.get((feature_id, function))
        if payload is None:
            return self._error(request, Hidpp20Error.INVALID_FUNCTION_ID)
        return self._reply(request, payload)
