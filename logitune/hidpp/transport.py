# SPDX-License-Identifier: GPL-3.0-or-later
"""Transporte HID++ sobre `/dev/hidraw`.

Esta camada não sabe nada sobre features: ela só descobre quais nós hidraw
falam HID++, abre o descritor e move bytes de um lado para o outro.

Um ponto importante do hidraw: cada `open()` recebe a sua própria fila de
reports vindos do dispositivo. Isso significa que podemos ler em paralelo com
o Solaar sem "roubar" pacotes dele — mas também que vamos ver o tráfego que
ele gera. É por isso que toda requisição carrega um software ID
(:data:`~logitune.hidpp.constants.SOFTWARE_ID`) que nos deixa filtrar as
respostas que são de fato nossas.
"""

from __future__ import annotations

import errno
import logging
import os
import select
import time
from dataclasses import dataclass
from pathlib import Path

from logitune.hidpp.constants import (
    LOGITECH_VENDOR_ID,
    REPORT_SIZE,
    ReportType,
)

logger = logging.getLogger(__name__)

_HIDRAW_CLASS = Path("/sys/class/hidraw")


class TransportError(OSError):
    """Falha ao abrir, ler ou escrever no nó hidraw."""


@dataclass(frozen=True)
class HidrawNode:
    """Um nó `/dev/hidrawN` que fala HID++, com o que sabemos dele."""

    path: Path
    vendor_id: int
    product_id: int
    name: str
    phys: str
    #: Report IDs HID++ declarados no report descriptor (0x10, 0x11, 0x12).
    report_ids: frozenset[int]

    @property
    def supports_long(self) -> bool:
        return int(ReportType.LONG) in self.report_ids

    @property
    def supports_very_long(self) -> bool:
        return int(ReportType.VERY_LONG) in self.report_ids

    def __str__(self) -> str:
        return f"{self.path} ({self.vendor_id:04X}:{self.product_id:04X} {self.name})"


def _parse_uevent(uevent: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in uevent.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key] = value
    return values


def _hidpp_report_ids(descriptor: bytes) -> frozenset[int]:
    """Extrai os report IDs HID++ de um report descriptor HID.

    Procuramos por uma coleção de vendor usage page (0xFF00..0xFFFF) que
    declare Report IDs 0x10/0x11/0x12 — a assinatura das interfaces HID++.
    O parser é deliberadamente raso: percorre os itens *short* do descritor
    e registra qual foi a última usage page antes de cada Report ID.
    """
    found: set[int] = set()
    page: int | None = None
    index = 0
    length = len(descriptor)

    while index < length:
        prefix = descriptor[index]
        if prefix == 0xFE:  # item longo: 0xFE, tamanho, tag, dados...
            if index + 1 >= length:
                break
            index += 3 + descriptor[index + 1]
            continue

        size = prefix & 0x03
        size = 4 if size == 3 else size
        tag = prefix & 0xFC
        data = descriptor[index + 1 : index + 1 + size]
        value = int.from_bytes(data, "little") if data else 0

        if tag == 0x04:  # Usage Page (global)
            page = value
        elif tag == 0x84:  # Report ID (global)
            if page is not None and 0xFF00 <= page <= 0xFFFF:
                if value in REPORT_SIZE:
                    found.add(value)

        index += 1 + size

    return frozenset(found)


def discover_nodes(vendor_id: int = LOGITECH_VENDOR_ID) -> list[HidrawNode]:
    """Lista os nós hidraw do fabricante indicado que falam HID++.

    Devolve apenas nós cujo report descriptor declara os reports HID++, o que
    descarta as interfaces de mouse/teclado comuns do mesmo receiver.
    """
    nodes: list[HidrawNode] = []

    if not _HIDRAW_CLASS.is_dir():
        return nodes

    for entry in sorted(_HIDRAW_CLASS.iterdir()):
        device = entry / "device"
        try:
            uevent = _parse_uevent((device / "uevent").read_text())
        except OSError:
            continue

        hid_id = uevent.get("HID_ID", "")
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        try:
            node_vendor = int(parts[1], 16)
            node_product = int(parts[2], 16)
        except ValueError:
            continue

        if node_vendor != vendor_id:
            continue

        try:
            descriptor = (device / "report_descriptor").read_bytes()
        except OSError:
            continue

        report_ids = _hidpp_report_ids(descriptor)
        if not report_ids:
            continue

        nodes.append(
            HidrawNode(
                path=Path("/dev") / entry.name,
                vendor_id=node_vendor,
                product_id=node_product,
                name=uevent.get("HID_NAME", ""),
                phys=uevent.get("HID_PHYS", ""),
                report_ids=report_ids,
            )
        )

    return nodes


class HidrawTransport:
    """Leitura e escrita de reports HID++ em um nó hidraw."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    # -- ciclo de vida -------------------------------------------------

    def open(self) -> None:
        if self._fd is not None:
            return
        try:
            self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno == errno.EACCES:
                raise TransportError(
                    exc.errno,
                    f"Sem permissão para abrir {self.path}. Instale a regra udev do "
                    f"logi-tune-linux e reconecte o dispositivo.",
                ) from exc
            raise TransportError(exc.errno, f"Não foi possível abrir {self.path}: {exc}") from exc

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> HidrawTransport:
        self.open()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @property
    def fileno(self) -> int:
        if self._fd is None:
            raise TransportError(errno.EBADF, f"{self.path} não está aberto")
        return self._fd

    # -- E/S -----------------------------------------------------------

    def write(self, data: bytes) -> None:
        """Envia um report já montado (o primeiro byte é o report ID)."""
        fd = self.fileno
        try:
            written = os.write(fd, data)
        except OSError as exc:
            raise TransportError(exc.errno, f"Falha ao escrever em {self.path}: {exc}") from exc
        if written != len(data):
            raise TransportError(
                errno.EIO, f"Escrita parcial em {self.path}: {written}/{len(data)} bytes"
            )
        logger.debug("-> %s", data.hex(" "))

    def read(self, timeout: float = 0.5) -> bytes | None:
        """Lê o próximo report, ou devolve ``None`` se estourar o tempo."""
        fd = self.fileno
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None

            try:
                data = os.read(fd, 64)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise TransportError(exc.errno, f"Falha ao ler de {self.path}: {exc}") from exc

            if data:
                logger.debug("<- %s", data.hex(" "))
                return data
