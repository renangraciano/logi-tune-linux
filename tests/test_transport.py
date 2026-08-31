# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do parser de report descriptor HID."""

from __future__ import annotations

from logitune.hidpp.transport import _hidpp_report_ids


def _descriptor(*items: int) -> bytes:
    return bytes(items)


def test_encontra_reports_hidpp_em_vendor_page():
    # Usage Page (0xFF00, vendor), Report ID 0x10, Report ID 0x11.
    descriptor = _descriptor(0x06, 0x00, 0xFF, 0x85, 0x10, 0x85, 0x11)
    assert _hidpp_report_ids(descriptor) == {0x10, 0x11}


def test_ignora_reports_fora_da_vendor_page():
    # Usage Page (0x01, Generic Desktop) — um mouse comum, não HID++.
    descriptor = _descriptor(0x05, 0x01, 0x85, 0x10)
    assert _hidpp_report_ids(descriptor) == frozenset()


def test_ignora_report_id_desconhecido_na_vendor_page():
    descriptor = _descriptor(0x06, 0x00, 0xFF, 0x85, 0x42)
    assert _hidpp_report_ids(descriptor) == frozenset()


def test_pula_itens_longos_sem_travar():
    # Item longo (0xFE, tamanho 2) seguido de vendor page com report 0x11.
    descriptor = _descriptor(0xFE, 0x02, 0x00, 0xAA, 0xBB, 0x06, 0x00, 0xFF, 0x85, 0x11)
    assert _hidpp_report_ids(descriptor) == {0x11}


class TestLeituraNaoBloqueante:
    """`timeout=0` significa "veja se há algo agora", não "desista na hora".

    Regressão: o prazo restante já estava vencido no instante em que era
    conferido, então a leitura devolvia None mesmo com um report na fila. Como
    o daemon usa exatamente `poll(timeout=0)`, as ações de botão desviado nunca
    chegavam a disparar.

    Os testes usam um par de sockets de datagrama porque, como o hidraw, ele
    preserva a fronteira de cada report — um `pipe` juntaria tudo num fluxo só
    e não representaria o dispositivo.
    """

    @staticmethod
    def _transporte():
        import socket

        from logitune.hidpp.transport import HidrawTransport

        nosso, dispositivo = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        nosso.setblocking(False)
        transporte = HidrawTransport("/dev/null")
        transporte._fd = nosso.fileno()
        return transporte, nosso, dispositivo

    def test_timeout_zero_devolve_report_enfileirado(self):
        transporte, nosso, dispositivo = self._transporte()
        try:
            esperado = bytes.fromhex("1101090037080000")
            dispositivo.send(esperado)
            assert transporte.read(0.0) == esperado
        finally:
            nosso.close()
            dispositivo.close()

    def test_timeout_zero_com_fila_vazia_devolve_none(self):
        transporte, nosso, dispositivo = self._transporte()
        try:
            assert transporte.read(0.0) is None
        finally:
            nosso.close()
            dispositivo.close()

    def test_leituras_sucessivas_esvaziam_a_fila(self):
        # É disto que o daemon depende para drenar uma rajada de eventos.
        transporte, nosso, dispositivo = self._transporte()
        try:
            dispositivo.send(b"\x11\x01\x02\x00")
            dispositivo.send(b"\x11\x01\x03\x00")
            assert transporte.read(0.0) == b"\x11\x01\x02\x00"
            assert transporte.read(0.0) == b"\x11\x01\x03\x00"
            assert transporte.read(0.0) is None
        finally:
            nosso.close()
            dispositivo.close()
