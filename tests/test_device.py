"""Testes do diálogo HID++: descoberta de features, erros e filtragem."""

from __future__ import annotations

import pytest

from logitune.hidpp.constants import SOFTWARE_ID
from logitune.hidpp.device import (
    FeatureNotSupported,
    Hidpp20Device,
    HidppError,
    NoResponse,
)
from tests.fake_transport import FakeTransport


def _device(**kwargs) -> tuple[Hidpp20Device, FakeTransport]:
    # Índices contíguos, como um dispositivo real os enumera via FEATURE_SET.
    transport = FakeTransport(
        features={0x0000: 0, 0x0001: 1, 0x1004: 2, 0x2201: 3},
        responses={(0x1004, 0x01): bytes([55, 0x08, 0x00, 0x00])},
        **kwargs,
    )
    return Hidpp20Device(transport, device_index=1), transport


def test_resolve_indice_de_feature():
    device, _ = _device()
    assert device.feature_index(0x2201) == 3
    assert device.feature_index(0x1004) == 2


def test_feature_ausente_devolve_none():
    device, _ = _device()
    assert device.feature_index(0x9999) is None
    assert not device.supports(0x9999)


def test_chamar_feature_ausente_levanta():
    device, _ = _device()
    with pytest.raises(FeatureNotSupported):
        device.call(0x9999, 0x00)


def test_requisicao_carrega_o_software_id():
    device, transport = _device()
    device.call(0x1004, 0x01)
    requisicao = transport.written[-1]
    assert requisicao[1] == 1  # índice do dispositivo
    assert requisicao[2] == 2  # índice da feature 0x1004
    assert requisicao[3] & 0x0F == SOFTWARE_ID
    assert requisicao[3] >> 4 == 0x01  # número da função


def test_indice_de_feature_e_cacheado():
    device, transport = _device()
    device.feature_index(0x2201)
    escritas = len(transport.written)
    device.feature_index(0x2201)
    assert len(transport.written) == escritas


def test_erro_do_dispositivo_vira_excecao():
    device, _ = _device()
    with pytest.raises(HidppError) as exc:
        device.call(0x1004, 0x07)  # função que o dispositivo não tem
    assert "INVALID_FUNCTION_ID" in str(exc.value)


def test_resposta_de_outro_software_id_e_ignorada():
    """Tráfego de outro processo no mesmo hidraw não pode virar nossa resposta."""
    device, transport = _device()

    original = transport._respond

    def responder_com_swid_alheio(request: bytes) -> bytes:
        resposta = bytearray(original(request))
        resposta[3] = (resposta[3] & 0xF0) | 0x0A  # software ID do Solaar
        return bytes(resposta)

    transport._respond = responder_com_swid_alheio
    device.retries = 0
    with pytest.raises(NoResponse):
        device.call(0x1004, 0x01)


def test_tabela_de_features_enumera_tudo():
    device, _ = _device()
    tabela = device.feature_table()
    ids = {info.feature_id for info in tabela}
    assert {0x0000, 0x0001, 0x1004, 0x2201} <= ids
