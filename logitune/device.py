"""Fachada de alto nível: um mouse Logitech e tudo que dá para ajustar nele.

A camada ``logitune.hidpp`` fala protocolo. Esta aqui fala em termos de
produto: "qual o DPI", "quais botões existem", "qual a bateria" — sem que o
chamador precise saber que isso são as features 0x2201, 0x1B04 e 0x1004.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from logitune.hidpp.constants import FeatureID
from logitune.hidpp.device import Hidpp20Device, HidppError, NoResponse
from logitune.hidpp.features.battery import UnifiedBattery
from logitune.hidpp.features.controls import ReprogControls
from logitune.hidpp.features.dpi import AdjustableDpi
from logitune.hidpp.features.hosts import ChangeHost, HostsInfo
from logitune.hidpp.features.info import DeviceFriendlyName, DeviceName, DeviceType
from logitune.hidpp.features.scroll import HiResWheel, SmartShift, ThumbWheel
from logitune.hidpp.transport import HidrawTransport, HidrawNode, discover_nodes

logger = logging.getLogger(__name__)

#: Índices de dispositivo que um receiver pode ter pareados.
_RECEIVER_INDEXES = range(1, 7)
#: Índice usado quando o periférico está ligado direto (USB ou Bluetooth).
_DIRECT_INDEX = 0xFF


@dataclass(frozen=True)
class DeviceIdentity:
    """Quem é este dispositivo."""

    name: str
    friendly_name: str
    kind: DeviceType
    node: Path
    device_index: int

    @property
    def is_mouse(self) -> bool:
        return self.kind in (DeviceType.MOUSE, DeviceType.TRACKBALL, DeviceType.TOUCHPAD)

    @property
    def connection(self) -> str:
        return "receptor" if self.device_index != _DIRECT_INDEX else "direta"


class LogitechDevice:
    """Um dispositivo Logitech pronto para uso.

    As features são criadas sob demanda e cacheadas; consultar uma feature que
    o dispositivo não tem devolve ``None`` em vez de estourar, para que a
    interface possa simplesmente esconder o controle correspondente.
    """

    def __init__(self, transport: HidrawTransport, device_index: int) -> None:
        self.transport = transport
        self.hidpp = Hidpp20Device(transport, device_index)
        self.device_index = device_index

    # -- identidade ----------------------------------------------------

    @cached_property
    def identity(self) -> DeviceIdentity:
        names = DeviceName(self.hidpp)
        friendly = DeviceFriendlyName(self.hidpp)
        return DeviceIdentity(
            name=names.get_name(),
            friendly_name=friendly.get_name() if friendly.available else "",
            kind=names.get_type(),
            node=self.transport.path,
            device_index=self.device_index,
        )

    @property
    def name(self) -> str:
        return self.identity.name

    # -- features ------------------------------------------------------

    def _feature(self, cls):
        """Instancia um wrapper de feature, ou ``None`` se não houver suporte."""
        instance = cls(self.hidpp)
        return instance if instance.available else None

    @cached_property
    def battery(self) -> UnifiedBattery | None:
        return self._feature(UnifiedBattery)

    @cached_property
    def dpi(self) -> AdjustableDpi | None:
        return self._feature(AdjustableDpi)

    @cached_property
    def smartshift(self) -> SmartShift | None:
        return self._feature(SmartShift)

    @cached_property
    def wheel(self) -> HiResWheel | None:
        return self._feature(HiResWheel)

    @cached_property
    def thumbwheel(self) -> ThumbWheel | None:
        return self._feature(ThumbWheel)

    @cached_property
    def controls(self) -> ReprogControls | None:
        return self._feature(ReprogControls)

    @cached_property
    def hosts(self) -> HostsInfo | None:
        return self._feature(HostsInfo)

    @cached_property
    def change_host(self) -> ChangeHost | None:
        return self._feature(ChangeHost)

    def feature_ids(self) -> list[int]:
        """IDs de todas as features anunciadas pelo dispositivo."""
        return [info.feature_id for info in self.hidpp.feature_table()]

    def __repr__(self) -> str:
        return f"<LogitechDevice {self.name!r} idx={self.device_index}>"


def _probe(transport: HidrawTransport, device_index: int) -> LogitechDevice | None:
    """Existe um dispositivo respondendo neste índice?"""
    device = LogitechDevice(transport, device_index)
    try:
        # ROOT.getFeature é a pergunta mais barata que prova que há alguém
        # do outro lado falando HID++ 2.0.
        if device.hidpp.feature_index(int(FeatureID.DEVICE_NAME)) is None:
            return None
        _ = device.identity
    except (NoResponse, OSError) as exc:
        logger.debug("índice %s não respondeu: %s", device_index, exc)
        return None
    except HidppError as exc:
        # Um slot vazio do receptor não fica em silêncio: ele responde com
        # erro. Isso é ausência de dispositivo, não falha.
        logger.debug("índice %s sem dispositivo pareado: %s", device_index, exc)
        return None
    return device


def discover_devices(*, mice_only: bool = True) -> list[LogitechDevice]:
    """Encontra os dispositivos Logitech acessíveis nesta máquina.

    Varre os nós hidraw que falam HID++ e, em cada um, pergunta pelos índices
    que um receptor pode ter pareado, além do índice de conexão direta.

    O transporte fica aberto nos dispositivos devolvidos — feche-os com
    :func:`close_devices` quando terminar.
    """
    devices: list[LogitechDevice] = []

    for node in discover_nodes():
        transport = HidrawTransport(node.path)
        try:
            transport.open()
        except OSError as exc:
            logger.warning("não foi possível abrir %s: %s", node.path, exc)
            continue

        found_here: list[LogitechDevice] = []
        for index in (*_RECEIVER_INDEXES, _DIRECT_INDEX):
            device = _probe(transport, index)
            if device is None:
                continue
            if mice_only and not device.identity.is_mouse:
                continue
            found_here.append(device)

        if found_here:
            devices.extend(found_here)
        else:
            transport.close()

    return devices


def close_devices(devices: list[LogitechDevice]) -> None:
    """Fecha os transportes abertos por :func:`discover_devices`."""
    for transport in {device.transport for device in devices}:
        transport.close()


def find_device(name_fragment: str | None = None) -> LogitechDevice | None:
    """Devolve o primeiro mouse encontrado, opcionalmente filtrando por nome."""
    devices = discover_devices()
    if not devices:
        return None
    if name_fragment is None:
        chosen = devices[0]
    else:
        needle = name_fragment.casefold()
        chosen = next(
            (d for d in devices if needle in d.name.casefold()),
            None,
        )
        if chosen is None:
            close_devices(devices)
            return None
    close_devices([d for d in devices if d.transport is not chosen.transport])
    return chosen
