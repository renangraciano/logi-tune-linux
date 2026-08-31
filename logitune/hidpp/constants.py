"""Constantes do protocolo HID++ (1.0 e 2.0) da Logitech.

Referências: especificação pública HID++ 2.0 da Logitech e o trabalho de
engenharia reversa do projeto Solaar. Os nomes seguem a nomenclatura oficial
da Logitech para facilitar a comparação com a documentação.
"""

from __future__ import annotations

import enum


class ReportType(enum.IntEnum):
    """Report IDs HID++ e o tamanho total de cada um, em bytes."""

    SHORT = 0x10
    LONG = 0x11
    VERY_LONG = 0x12


#: Tamanho total (incluindo o byte de report ID) de cada tipo de report.
REPORT_SIZE = {
    ReportType.SHORT: 7,
    ReportType.LONG: 20,
    ReportType.VERY_LONG: 64,
}

#: Índice de dispositivo usado quando falamos direto com o periférico
#: (USB cabeado ou Bluetooth), sem receiver no meio.
DEVICE_INDEX_DIRECT = 0xFF

#: Índice de dispositivo do próprio receiver.
DEVICE_INDEX_RECEIVER = 0xFF

#: Software ID (4 bits, 1..15) que carimbamos nas requisições. O dispositivo
#: devolve o mesmo valor na resposta, o que nos deixa distinguir as nossas
#: respostas das de outro processo falando com o mesmo device (Solaar, por
#: exemplo). 0x0A é o do Solaar; usamos outro para não haver ambiguidade.
SOFTWARE_ID = 0x0D

#: Índice da feature raiz (0x0000 ROOT), que é sempre 0 e é por onde
#: descobrimos o índice de todas as outras.
ROOT_FEATURE_INDEX = 0x00

#: Marcador de erro HID++ 2.0: vem no lugar do índice de feature.
ERROR_FEATURE_INDEX = 0xFF

#: Sub ID de erro no HID++ 1.0.
ERROR_SUB_ID_HIDPP10 = 0x8F


class FeatureID(enum.IntEnum):
    """Features HID++ 2.0 relevantes para mouses Logitech.

    Os valores marcados como *não documentados* foram observados no
    MX Master 4 (WPID B042) e ainda estão sob engenharia reversa.
    """

    ROOT = 0x0000
    FEATURE_SET = 0x0001
    DEVICE_FW_VERSION = 0x0003
    DEVICE_NAME = 0x0005
    DEVICE_FRIENDLY_NAME = 0x0007
    UNIFIED_BATTERY = 0x1004
    REPROG_CONTROLS_V4 = 0x1B04
    CHANGE_HOST = 0x1814
    HOSTS_INFO = 0x1815
    SMART_SHIFT_ENHANCED = 0x2111
    HIRES_WHEEL = 0x2121
    THUMB_WHEEL = 0x2150
    ADJUSTABLE_DPI = 0x2201
    XY_STATS = 0x2250
    WHEEL_STATS = 0x2251

    # --- Não documentadas, presentes no MX Master 4 ---
    #: Suspeita: relacionada ao Actions Ring / haptics.
    MX4_UNKNOWN_19B0 = 0x19B0
    #: Suspeita: relacionada ao Actions Ring / haptics.
    MX4_UNKNOWN_19C0 = 0x19C0
    MX4_UNKNOWN_1701 = 0x1701
    MX4_UNKNOWN_00D1 = 0x00D1
    MX4_UNKNOWN_1602 = 0x1602


class Hidpp20Error(enum.IntEnum):
    """Códigos de erro do HID++ 2.0 (ErrorCode)."""

    NO_ERROR = 0x00
    UNKNOWN = 0x01
    INVALID_ARGUMENT = 0x02
    OUT_OF_RANGE = 0x03
    HARDWARE_ERROR = 0x04
    LOGITECH_INTERNAL = 0x05
    INVALID_FEATURE_INDEX = 0x06
    INVALID_FUNCTION_ID = 0x07
    BUSY = 0x08
    UNSUPPORTED = 0x09


class FeatureFlag(enum.IntFlag):
    """Flags devolvidas por ROOT.getFeature / FEATURE_SET.getFeatureID."""

    OBSOLETE = 0x80
    HIDDEN = 0x40
    ENGINEERING = 0x20
    MANUFACTURING = 0x10
    COMPLIANCE = 0x08


#: Vendor ID da Logitech.
LOGITECH_VENDOR_ID = 0x046D
