# SPDX-License-Identifier: GPL-3.0-or-later
"""Ações que o próprio mouse executa.

Trocar o DPI, travar a roda, pular para outro computador: o dispositivo já
sabe fazer tudo isso, e é a nossa própria pilha HID++ que fala com ele. A
diferença para os outros backends é que estas ações precisam do mouse aberto,
o que só quem tem um :class:`~logitune.device.LogitechDevice` na mão consegue
oferecer — o daemon sempre tem.
"""

from __future__ import annotations

import logging

from logitune.actions.spec import ActionContext, ActionError
from logitune.hidpp.device import HidppError, NoResponse
from logitune.hidpp.features.haptic import MAX_WAVEFORM, MIN_WAVEFORM, Waveform
from logitune.hidpp.features.hosts import HostStatus
from logitune.hidpp.features.scroll import WheelMode

logger = logging.getLogger(__name__)


def _feature(context: ActionContext, name: str):
    device = context.require_device()
    feature = getattr(device, name, None)
    if feature is None:
        raise ActionError(f"{device.name} não tem {name}")
    return feature


def toggle_ratchet(context: ActionContext) -> None:
    """Alterna entre a roda travada em catraca e a roda livre."""
    smartshift = _feature(context, "smartshift")
    try:
        atual = smartshift.get_state().mode
        desejado = WheelMode.FREESPIN if atual is WheelMode.RATCHET else WheelMode.RATCHET
        smartshift.set_state(mode=desejado)
    except (HidppError, NoResponse) as exc:
        raise ActionError(f"não consegui trocar o modo da roda: {exc}") from exc
    logger.debug("roda → %s", desejado.label)


def cycle_dpi(context: ActionContext) -> None:
    """Passa para o próximo DPI da lista configurada.

    Sem lista, alterna entre o DPI atual e a metade dele — o "modo mira" que o
    Options+ oferece, e que é o motivo de quase todo mundo querer isto.
    """
    dpi = _feature(context, "dpi")
    valores = context.get("values") or []
    try:
        atual = dpi.get_dpi().current
        if not valores:
            alvo = atual * 2 if atual <= _sniper_threshold(dpi) else atual // 2
        else:
            valores = [int(v) for v in valores]
            # O DPI de verdade pode não bater exatamente com nenhum da lista
            # (o sensor arredonda), então procuramos o mais próximo.
            indice = min(range(len(valores)), key=lambda i: abs(valores[i] - atual))
            alvo = valores[(indice + 1) % len(valores)]
        aplicado = dpi.set_dpi(alvo)
    except (HidppError, NoResponse, ValueError) as exc:
        raise ActionError(f"não consegui trocar o DPI: {exc}") from exc
    logger.debug("DPI %s → %s", atual, aplicado)


def _sniper_threshold(dpi) -> int:
    """Abaixo disto consideramos que já estamos no modo mira."""
    faixa = dpi.get_range()
    return max(faixa.minimum, (faixa.minimum + faixa.maximum) // 4)


def next_host(context: ActionContext) -> None:
    """Passa o mouse para o próximo computador pareado.

    A conexão com esta máquina cai no ato — é exatamente o que se pediu, mas
    vale saber que a ação não tem como confirmar que deu certo.
    """
    device = context.require_device()
    if device.hosts is None or device.change_host is None:
        raise ActionError(f"{device.name} não faz Easy-Switch")
    try:
        hosts = device.hosts.list_hosts()
        atual = device.change_host.get_current_host()
    except (HidppError, NoResponse) as exc:
        raise ActionError(f"não consegui ler os computadores pareados: {exc}") from exc

    if not hosts:
        raise ActionError("o dispositivo não reportou nenhum canal")

    # Damos a volta a partir do canal atual e paramos no primeiro pareado.
    total = len(hosts)
    ocupados = {h.index: h for h in hosts if h.status is HostStatus.PAIRED}
    proximo = next(
        (
            ocupados[(atual + passo) % total]
            for passo in range(1, total)
            if (atual + passo) % total in ocupados
        ),
        None,
    )
    if proximo is None:
        raise ActionError("não há outro computador pareado")

    try:
        device.change_host.switch_to(proximo.index)
    except (HidppError, NoResponse) as exc:
        raise ActionError(f"não consegui trocar de computador: {exc}") from exc
    logger.debug("host %s → %s", atual, proximo.label)


def play_haptic(context: ActionContext) -> None:
    """Toca um padrão de vibração."""
    haptic = _feature(context, "haptic")
    bruto = context.get("waveform", int(Waveform.CLICK))
    try:
        waveform = int(bruto)
    except (TypeError, ValueError) as exc:
        raise ActionError(f"padrão háptico inválido: {bruto!r}") from exc
    if not MIN_WAVEFORM <= waveform <= MAX_WAVEFORM:
        raise ActionError(
            f"padrão háptico fora da faixa ({MIN_WAVEFORM}–{MAX_WAVEFORM}): {waveform}"
        )
    try:
        haptic.play(waveform)
    except (HidppError, NoResponse, ValueError) as exc:
        raise ActionError(f"não consegui vibrar: {exc}") from exc
