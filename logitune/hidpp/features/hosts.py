# SPDX-License-Identifier: GPL-3.0-or-later
"""Features de múltiplos hosts: 0x1815 HOSTS INFO e 0x1814 CHANGE HOST.

É o Easy-Switch: o mouse guarda até três computadores pareados e alterna
entre eles. Saber quais são e trocar por software é a base para reproduzir
o Logitech Flow no Linux.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.device import NoResponse
from logitune.hidpp.features.base import Feature

_HI_GET_FEATURE_INFO = 0x00
_HI_GET_HOST_INFO = 0x01
#: A função 0x02 devolve o identificador do host, não o nome. O nome
#: amigável fica na 0x03, confirmado por sondagem no MX Master 4.
_HI_GET_HOST_ID = 0x02
_HI_GET_FRIENDLY_NAME = 0x03

_CH_GET_HOST_INFO = 0x00
_CH_SET_CURRENT_HOST = 0x01


class HostStatus(enum.IntEnum):
    EMPTY = 0x00
    PAIRED = 0x01

    @property
    def label(self) -> str:
        return "pareado" if self is HostStatus.PAIRED else "vazio"


#: Rótulos de tipo de barramento por valor bruto.
#:
#: A Logitech não publica esse enum. Os valores abaixo foram confirmados no
#: MX Master 4: o canal ligado ao receptor Bolt reporta 0x05 e os canais
#: Bluetooth reportam 0x04. Valores fora da tabela são exibidos como
#: desconhecidos em vez de adivinhados.
BUS_TYPE_LABELS: dict[int, str] = {
    0x04: "Bluetooth",
    0x05: "receptor Bolt",
}


@dataclass(frozen=True)
class Host:
    """Um dos slots de host (os canais 1, 2, 3 do mouse)."""

    index: int
    status: HostStatus
    #: Valor bruto do tipo de barramento (ver :data:`BUS_TYPE_LABELS`).
    bus_type: int
    name: str
    is_current: bool

    @property
    def bus_label(self) -> str:
        return BUS_TYPE_LABELS.get(self.bus_type, f"barramento 0x{self.bus_type:02X}")

    @property
    def channel(self) -> int:
        """Número do canal como aparece no mouse (1-based)."""
        return self.index + 1

    @property
    def label(self) -> str:
        if self.status is not HostStatus.PAIRED:
            return f"Canal {self.channel} (livre)"
        return self.name or f"Canal {self.channel}"


class HostsInfo(Feature):
    """Consulta os hosts pareados."""

    FEATURE_ID = int(FeatureID.HOSTS_INFO)

    def get_host_count(self) -> tuple[int, int]:
        """Devolve ``(quantidade de slots, índice do host atual)``.

        Os dois primeiros bytes da resposta são a máscara de capacidades.
        """
        response = self._call(_HI_GET_FEATURE_INFO)
        return response[2], response[3]

    def _get_friendly_name(self, host_index: int, name_length: int) -> str:
        chunks: list[bytes] = []
        offset = 0
        while offset < name_length:
            response = self._call(_HI_GET_FRIENDLY_NAME, bytes([host_index, offset]))
            # Os dois primeiros bytes repetem host e offset pedidos.
            chunk = response[2:]
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        return b"".join(chunks)[:name_length].decode("utf-8", errors="replace").rstrip("\x00")

    def list_hosts(self) -> list[Host]:
        count, current = self.get_host_count()
        hosts: list[Host] = []
        for index in range(count):
            response = self._call(_HI_GET_HOST_INFO, bytes([index]))
            try:
                status = HostStatus(response[1])
            except ValueError:
                status = HostStatus.EMPTY
            bus_type = response[2]
            name_length = response[4]
            name = (
                self._get_friendly_name(index, name_length)
                if status is HostStatus.PAIRED and name_length
                else ""
            )
            hosts.append(
                Host(
                    index=index,
                    status=status,
                    bus_type=bus_type,
                    name=name,
                    is_current=index == current,
                )
            )
        return hosts


class ChangeHost(Feature):
    """Troca o host ativo (Easy-Switch por software)."""

    FEATURE_ID = int(FeatureID.CHANGE_HOST)

    def get_current_host(self) -> int:
        return self._call(_CH_GET_HOST_INFO)[1]

    def switch_to(self, host_index: int) -> None:
        """Move o mouse para outro computador.

        O dispositivo se desconecta imediatamente, então a resposta pode
        nunca chegar. Um timeout aqui é o resultado esperado, não uma falha.
        """
        try:
            self._call(_CH_SET_CURRENT_HOST, bytes([host_index]))
        except NoResponse:
            pass
