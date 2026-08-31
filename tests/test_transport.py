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
