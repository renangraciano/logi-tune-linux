"""Feature 0x2201 — ADJUSTABLE DPI (sensibilidade do ponteiro)."""

from __future__ import annotations

from dataclasses import dataclass

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.features.base import Feature

_GET_SENSOR_COUNT = 0x00
_GET_SENSOR_DPI_LIST = 0x01
_GET_SENSOR_DPI = 0x02
_SET_SENSOR_DPI = 0x03

#: Na lista de DPIs, um valor com este bit ligado não é um DPI: é o
#: incremento de uma faixa contínua (min, passo, max).
_RANGE_MARKER = 0xE000


@dataclass(frozen=True)
class DpiRange:
    """Os valores de DPI que o sensor aceita.

    O dispositivo descreve isso de duas formas: uma lista explícita de valores
    ou uma faixa contínua ``min..max`` com um passo. Normalizamos as duas em
    uma só estrutura.
    """

    minimum: int
    maximum: int
    step: int
    #: Valores discretos, quando o sensor lista em vez de dar uma faixa.
    values: tuple[int, ...] = ()

    @property
    def is_continuous(self) -> bool:
        return not self.values

    def clamp(self, dpi: int) -> int:
        """Ajusta um DPI para o valor válido mais próximo."""
        if self.values:
            return min(self.values, key=lambda value: abs(value - dpi))
        dpi = max(self.minimum, min(self.maximum, dpi))
        if self.step > 1:
            offset = round((dpi - self.minimum) / self.step)
            dpi = self.minimum + offset * self.step
        return min(self.maximum, dpi)

    def steps(self) -> list[int]:
        """Todos os valores selecionáveis, para alimentar um slider."""
        if self.values:
            return list(self.values)
        return list(range(self.minimum, self.maximum + 1, max(1, self.step)))


@dataclass(frozen=True)
class DpiState:
    sensor: int
    current: int
    default: int


class AdjustableDpi(Feature):
    """Leitura e ajuste de DPI."""

    FEATURE_ID = int(FeatureID.ADJUSTABLE_DPI)

    def get_sensor_count(self) -> int:
        return self._call(_GET_SENSOR_COUNT)[0]

    def get_range(self, sensor: int = 0) -> DpiRange:
        response = self._call(_GET_SENSOR_DPI_LIST, bytes([sensor]))
        # response[0] repete o índice do sensor; os pares seguintes são a lista.
        raw = [
            int.from_bytes(response[i : i + 2], "big")
            for i in range(1, len(response) - 1, 2)
        ]

        values: list[int] = []
        minimum = maximum = step = 0
        index = 0
        while index < len(raw):
            value = raw[index]
            if value == 0:
                break
            if value & _RANGE_MARKER == _RANGE_MARKER:
                # Faixa contínua: o valor anterior é o mínimo, o próximo o máximo.
                step = value & ~_RANGE_MARKER
                minimum = values.pop() if values else 0
                index += 1
                maximum = raw[index] if index < len(raw) else minimum
            else:
                values.append(value)
            index += 1

        if step:
            return DpiRange(minimum=minimum, maximum=maximum, step=step)

        if not values:
            return DpiRange(minimum=0, maximum=0, step=0)

        return DpiRange(
            minimum=min(values),
            maximum=max(values),
            step=0,
            values=tuple(sorted(values)),
        )

    def get_dpi(self, sensor: int = 0) -> DpiState:
        response = self._call(_GET_SENSOR_DPI, bytes([sensor]))
        return DpiState(
            sensor=response[0],
            current=int.from_bytes(response[1:3], "big"),
            default=int.from_bytes(response[3:5], "big"),
        )

    def set_dpi(self, dpi: int, sensor: int = 0) -> int:
        """Aplica um DPI, ajustando para o valor válido mais próximo.

        Devolve o DPI efetivamente aceito pelo dispositivo.
        """
        target = self.get_range(sensor).clamp(dpi)
        self._call(_SET_SENSOR_DPI, bytes([sensor]) + target.to_bytes(2, "big"))
        return self.get_dpi(sensor).current
