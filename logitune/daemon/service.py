# SPDX-License-Identifier: GPL-3.0-or-later
"""O daemon: aplica perfis conforme a janela em foco e trata botões desviados.

Um único laço cuida das duas fontes de evento. Tanto o X quanto o hidraw
expõem um descritor de arquivo, então ficamos bloqueados em ``select`` até que
um dos dois tenha algo — sem timers, sem polling, sem consumo em repouso.
"""

from __future__ import annotations

import logging
import select
import signal
import sys
from dataclasses import dataclass

from logitune import config as config_module
from logitune.actions import ActionError, ResolvedAction, UnknownAction, resolve
from logitune.actions.backends import keys as keys_backend
from logitune.actions.gestures import Feedback, Gesture, GestureRecognizer
from logitune.actions.switcher import AppSwitcher, DetentCounter
from logitune.hidpp.features.haptic import Waveform
from logitune.hidpp.notifications import ThumbWheelStatus
from logitune.config import Config, Settings
from logitune.daemon.focus import FocusWatcher, Window
from logitune.device import LogitechDevice, close_devices, discover_devices
from logitune.hidpp.device import HidppError, NoResponse
from logitune.hidpp.features.scroll import WheelMode
from logitune.hidpp.notifications import NotificationListener

logger = logging.getLogger(__name__)

#: Teto de relatórios processados por acordada do ``select``. Existe para que
#: um dispositivo com muito tráfego não impeça o laço de olhar o foco.
_MAX_REPORTS_PER_CYCLE = 256


def apply_settings(device: LogitechDevice, settings: Settings) -> list[str]:
    """Aplica o que o perfil pede. Devolve a lista do que mudou de fato."""
    changes: list[str] = []

    def attempt(description: str, action) -> None:
        try:
            action()
        except (HidppError, NoResponse, OSError) as exc:
            logger.warning("não consegui %s: %s", description, exc)
        else:
            changes.append(description)

    if settings.dpi is not None and device.dpi:
        if device.dpi.get_dpi().current != settings.dpi:
            attempt(f"DPI {settings.dpi}", lambda: device.dpi.set_dpi(settings.dpi))

    if device.smartshift:
        state = device.smartshift.get_state()
        if settings.smartshift is not None and state.auto_disengage != settings.smartshift:
            attempt(
                f"SmartShift {settings.smartshift}",
                lambda: device.smartshift.set_state(auto_disengage=settings.smartshift),
            )
        if settings.ratchet is not None:
            desired = WheelMode.RATCHET if settings.ratchet else WheelMode.FREESPIN
            if state.mode is not desired:
                attempt(
                    f"roda {desired.label}",
                    lambda: device.smartshift.set_state(mode=desired),
                )

    if device.wheel:
        state = device.wheel.get_state()
        if settings.invert_scroll is not None and state.inverted != settings.invert_scroll:
            attempt(
                f"roda {'invertida' if settings.invert_scroll else 'normal'}",
                lambda: device.wheel.set_state(inverted=settings.invert_scroll),
            )
        if settings.hires_scroll is not None and state.high_resolution != settings.hires_scroll:
            attempt(
                f"alta resolução {'on' if settings.hires_scroll else 'off'}",
                lambda: device.wheel.set_state(high_resolution=settings.hires_scroll),
            )

    if device.thumbwheel and settings.invert_thumb is not None:
        if device.thumbwheel.get_state().inverted != settings.invert_thumb:
            attempt(
                f"polegar {'invertido' if settings.invert_thumb else 'normal'}",
                lambda: device.thumbwheel.set_state(inverted=settings.invert_thumb),
            )

    if device.controls:
        for source, target in settings.button_pairs():
            current = device.controls.get_reporting(source)
            if current.remapped_to != target:
                attempt(
                    f"botão 0x{source:04X}→0x{target:04X}",
                    lambda s=source, t=target: device.controls.set_reporting(s, remap_to=t),
                )

    return changes


@dataclass
class DaemonState:
    profile_name: str = ""
    window: Window | None = None


class Daemon:
    """Laço principal do serviço."""

    def __init__(self, config: Config, device: LogitechDevice) -> None:
        self.config = config
        self.device = device
        self.focus = FocusWatcher()
        self.listener = NotificationListener(device.hidpp)
        self.state = DaemonState()
        self._running = True
        #: Marcado pelo SIGHUP; o laço recarrega na volta do select.
        self._reload_requested = False
        #: Botões que desviamos e precisamos restaurar ao sair.
        self._diverted: list[int] = []
        #: Botões que disparam no clique, sem gesto: CID para ação.
        self._actions: dict[int, ResolvedAction] = {}
        #: Botões com gestos: CID para gesto para ação.
        self._gestures: dict[int, dict[Gesture, ResolvedAction]] = {}
        #: O que a roda do polegar faz no perfil ativo.
        self._wheel = None
        self._wheel_diverted = False
        self._switcher = AppSwitcher(idle_ms=config.switcher_idle_ms)
        #: Junta as unidades de giro em detents; a proporção sai do
        #: próprio dispositivo em _setup_wheel.
        self._detents = DetentCounter()
        self._recognizer = GestureRecognizer(
            config.gesture_thresholds(),
            bound=lambda cid: self._gestures.get(cid, {}).keys(),
            feedback=self._haptic_feedback,
        )

    # -- ciclo de vida -------------------------------------------------

    def stop(self, *_args) -> None:
        self._running = False

    def request_reload(self, *_args) -> None:
        """Anota que a configuração mudou. Chamado de dentro do SIGHUP.

        Um handler de sinal roda em cima de qualquer ponto do programa, então
        aqui só se marca uma flag: reler o arquivo e falar com o dispositivo
        acontece no laço, onde o estado é consistente.
        """
        self._reload_requested = True

    def _reload_config(self) -> None:
        """Relê a configuração e reaplica o perfil ativo."""
        self._reload_requested = False
        try:
            self.config = config_module.load()
        except Exception as exc:  # noqa: BLE001 - config ruim não derruba o daemon
            logger.error("não consegui recarregar a configuração: %s", exc)
            return

        logger.info("configuração recarregada")
        self._recognizer.thresholds = self.config.gesture_thresholds()
        self._switcher.idle_ms = self.config.switcher_idle_ms
        # Forçar a reavaliação: sem isto o perfil de mesmo nome seria
        # considerado já aplicado e nada mudaria.
        self.state.profile_name = ""
        self._apply_for_window(self.focus.current())

    def _resolve_bindings(
        self, settings: Settings
    ) -> tuple[dict[int, ResolvedAction], dict[int, dict[Gesture, ResolvedAction]]]:
        """Traduz a configuração em ações prontas para rodar.

        O que não resolve fica de fora, e o botão mantém a função de fábrica.
        Essa é a escolha deliberada: um botão desviado cuja ação falha não faz
        nada e não avisa, o que é pior do que um botão que continua clicando.
        """
        cliques: dict[int, ResolvedAction] = {}
        gestos: dict[int, dict[Gesture, ResolvedAction]] = {}

        def preparar(cid: int, binding, gesto: Gesture | None) -> ResolvedAction | None:
            onde = f"botão 0x{cid:04X}" + (f" ({gesto.label})" if gesto else "")
            try:
                acao = resolve(binding)
            except UnknownAction as exc:
                logger.warning("%s: %s", onde, exc)
                return None

            disponivel = acao.available()
            if not disponivel.usable:
                logger.warning(
                    "%s segue de fábrica: %s não roda aqui (%s)",
                    onde, acao.label, disponivel.reason,
                )
                return None
            if not disponivel.ok:
                logger.info("%s → %s (%s)", onde, acao.label, disponivel.reason)
            return acao

        gestos_ligados = self.config.gestures_enabled

        for cid, binding in settings.binding_pairs():
            if binding.gestures:
                if not gestos_ligados:
                    # Desligado quer dizer desligado: o botão volta à função
                    # de fábrica em vez de disparar um gesto pela metade.
                    logger.info(
                        "botão 0x%04X tem gestos, mas eles estão desligados", cid
                    )
                    continue
                # Um botão com gestos precisa do reconhecedor, então o clique
                # direto não se aplica nem quando há um "press" configurado.
                preparadas = {
                    gesto: acao
                    for gesto, acao in (
                        (g, preparar(cid, b, g)) for g, b in binding.gestures.items()
                    )
                    if acao is not None
                }
                if preparadas:
                    gestos[cid] = preparadas
                continue

            if binding.press is None:
                continue
            acao = preparar(cid, binding.press, None)
            if acao is not None:
                cliques[cid] = acao

        return cliques, gestos

    def _setup_actions(self, settings: Settings) -> None:
        """Desvia os botões que têm ação e libera os que não têm mais."""
        if self.device.controls is None:
            return

        cliques, gestos = self._resolve_bindings(settings)
        desired = {**cliques, **gestos}
        controls = {c.control_id: c for c in self.device.controls.list_controls()}

        for cid in list(self._diverted):
            if cid not in desired:
                try:
                    # O raw_xy cai junto: deixá-lo ligado faria o mouse
                    # continuar mandando movimento para ninguém.
                    self.device.controls.set_reporting(cid, diverted=False, raw_xy=False)
                except (HidppError, NoResponse):
                    logger.warning("não consegui liberar o botão 0x%04X", cid)
                else:
                    self._diverted.remove(cid)

        for cid in desired:
            control = controls.get(cid)
            if control is None:
                logger.warning("o dispositivo não tem o controle 0x%04X", cid)
                continue
            if not control.is_divertable:
                logger.warning("o controle %s não pode ser desviado", control.label)
                continue
            if cid in self._diverted:
                continue
            # Só os botões com gestos pedem movimento: ligar raw_xy num botão
            # de clique seria tráfego e latência sem uso.
            quer_movimento = cid in gestos
            try:
                self.device.controls.set_reporting(
                    cid, diverted=True, raw_xy=quer_movimento
                )
            except (HidppError, NoResponse) as exc:
                logger.warning("não consegui desviar %s: %s", control.label, exc)
            else:
                self._diverted.append(cid)

        self._actions = cliques
        self._gestures = gestos
        # Uma troca de perfil invalida qualquer pressionada em andamento.
        self._recognizer.reset()
        self._setup_wheel(settings)

    def _setup_wheel(self, settings: Settings) -> None:
        """Desvia a roda do polegar quando ela tem ação, e devolve quando não.

        Desviada, a roda para de gerar rolagem horizontal e passa a reportar
        por HID++. Só vale desviá-la se houver quem leia — senão a pessoa
        perde a rolagem e não ganha nada.
        """
        if self.device.thumbwheel is None:
            return

        desejado = settings.wheel_binding()
        if desejado.is_empty:
            self._wheel = None
            self._switcher.cancel()
            if self._wheel_diverted:
                self._divert_wheel(False)
            return

        self._wheel = desejado
        if not self._wheel_diverted:
            self._divert_wheel(True)
            self._detents = DetentCounter(self._units_per_detent())

    def _units_per_detent(self) -> int:
        """Quantas unidades desviadas cabem num clique da roda.

        Vem do dispositivo, não de constante: é a razão entre a resolução
        desviada e a nativa, e ela muda de modelo para modelo.
        """
        try:
            info = self.device.thumbwheel.get_info()
        except (HidppError, NoResponse) as exc:
            logger.warning("não consegui ler a resolução da roda: %s", exc)
            return 1
        if not info.native_resolution:
            return 1
        return max(1, round(info.diverted_resolution / info.native_resolution))

    def _divert_wheel(self, diverted: bool) -> None:
        try:
            self.device.thumbwheel.set_state(diverted=diverted)
        except (HidppError, NoResponse) as exc:
            logger.warning("não consegui mexer no desvio da roda do polegar: %s", exc)
            return
        self._wheel_diverted = diverted
        logger.info(
            "roda do polegar %s", "desviada" if diverted else "de volta à rolagem"
        )

    def _handle_wheel(self, event) -> None:
        """Um evento de giro da roda do polegar."""
        if self._wheel is None:
            return
        if event.status is ThumbWheelStatus.STOP:
            # O giro acabou: o que sobrou não vira detent no próximo.
            self._detents.reset()
            return

        detents = self._detents.feed(event.delta)
        if detents == 0:
            return

        if self._wheel.stateful == "window.switch_apps":
            for _ in range(min(abs(detents), 16)):
                self._switcher.step(1 if detents > 0 else -1)
            return

        binding = self._wheel.for_direction(detents)
        if binding is None:
            return
        try:
            acao = resolve(binding)
        except UnknownAction as exc:
            logger.warning("roda do polegar: %s", exc)
            return
        # Um giro rápido fecha vários detents de uma vez, e repetir a ação por
        # detent é o que faz o volume acompanhar a mão.
        for _ in range(min(abs(detents), 8)):
            self._run(acao)

    def restore(self) -> None:
        """Devolve os botões desviados ao comportamento normal.

        Sem isso, um botão desviado continuaria mudo depois que o daemon saísse.
        """
        if self.device.controls is None:
            return
        for cid in self._diverted:
            try:
                self.device.controls.set_reporting(cid, diverted=False, raw_xy=False)
            except (HidppError, NoResponse) as exc:
                logger.error("o botão 0x%04X ficou desviado: %s", cid, exc)
        self._diverted.clear()

        # A roda e o teclado virtual também precisam voltar: uma roda desviada
        # deixa de rolar, e uma tecla segurada sobrevive a quem a segurou.
        self._switcher.cancel()
        if self._wheel_diverted:
            self._divert_wheel(False)

    # -- reações -------------------------------------------------------

    def _apply_for_window(self, window: Window | None) -> None:
        window_class = window.wm_class if window else ""
        window_title = window.title if window else ""
        name, settings = self.config.settings_for(window_class, window_title)

        if name == self.state.profile_name:
            return

        logger.info("perfil %r para %s", name, window or "(sem janela)")
        if window is not None:
            # O título só aparece em depuração, ligada de propósito por quem
            # está investigando algo.
            logger.debug("janela em foco: %s", window.detailed)
        changes = apply_settings(self.device, settings)
        if changes:
            logger.info("  aplicado: %s", ", ".join(changes))
        self._setup_actions(settings)
        self.state.profile_name = name
        self.state.window = window

    def _haptic_feedback(self, kind: Feedback, gesture: Gesture) -> None:
        """Vibra para confirmar um gesto.

        É o que torna o gesto usável sem olhar para a tela: um toque curto
        quando a direção é reconhecida, e outro quando a ação dispara.
        """
        if self.device.haptic is None:
            return
        waveform = Waveform.TICK if kind is Feedback.CROSSED else Waveform.CLICK
        try:
            self.device.haptic.play(int(waveform))
        except (HidppError, NoResponse, OSError, ValueError) as exc:
            logger.debug("não consegui vibrar: %s", exc)

    def _dispatch_gestures(self, reconhecidos) -> None:
        for reconhecido in reconhecidos:
            acao = self._gestures.get(reconhecido.cid, {}).get(reconhecido.gesture)
            if acao is None:
                logger.debug(
                    "0x%04X: %s sem ação", reconhecido.cid, reconhecido.gesture.label
                )
                continue
            logger.info(
                "botão 0x%04X %s → %s",
                reconhecido.cid, reconhecido.gesture.label, acao.label,
            )
            self._run(acao)

    def _fire(self, cid: int, action: ResolvedAction) -> None:
        """Executa a ação de um botão de clique."""
        logger.info("botão 0x%04X → %s", cid, action.label)
        self._run(action)

    def _run(self, action: ResolvedAction) -> None:
        """Executa uma ação sem deixar que ela derrube o daemon."""
        try:
            action.run(self.device)
        except ActionError as exc:
            logger.error("a ação %s falhou: %s", action.spec.id, exc)
        except Exception:  # noqa: BLE001 - um backend novo não pode matar o laço
            logger.exception("erro inesperado na ação %s", action.spec.id)

    def _handle_device_event(self) -> None:
        """Processa tudo que o dispositivo enfileirou desde a última acordada.

        Um relatório por ciclo não basta. A fila do hidraw é limitada e, ao
        transbordar, o kernel descarta o relatório mais antigo — que pode ser
        justamente o que avisa que o botão foi solto, deixando o estado preso
        em "pressionado". O limite por ciclo evita que um dispositivo tagarela
        monopolize o laço e atrase a leitura do foco de janela.
        """
        for _ in range(_MAX_REPORTS_PER_CYCLE):
            notification = self.listener.poll(timeout=0)
            if notification is None:
                return

            giro = self.listener.as_thumbwheel_event(notification)
            if giro is not None:
                self._handle_wheel(giro)
                continue

            movement = self.listener.as_raw_movement(notification)
            if movement is not None:
                self._dispatch_gestures(
                    self._recognizer.movement(movement.dx, movement.dy)
                )
                continue

            event = self.listener.as_button_event(notification)
            if event is None:
                logger.debug("notificação: %s", notification)
                continue

            for cid in event.just_pressed:
                if cid in self._gestures:
                    self._recognizer.press(cid)
                    continue
                action = self._actions.get(cid)
                if action is not None:
                    self._fire(cid, action)

            for cid in event.just_released:
                if cid in self._gestures:
                    self._dispatch_gestures(self._recognizer.release(cid))

        logger.debug("limite de relatórios por ciclo atingido")

    # -- laço ----------------------------------------------------------

    def run(self) -> int:
        has_focus = self.focus.open()
        if has_focus:
            self._apply_for_window(self.focus.current())
        else:
            # Sem observação de foco ainda faz sentido aplicar o padrão.
            self._apply_for_window(None)

        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        # SIGHUP recarrega: é como a interface avisa que a configuração mudou,
        # sem precisar derrubar o serviço e perder o estado dos botões.
        signal.signal(signal.SIGHUP, self.request_reload)
        # As ações que abrem programas são disparadas e esquecidas: nunca
        # esperamos por elas. O módulo subprocess recolhe os filhos anteriores
        # só quando um novo Popen é criado, então sem isto o último comando
        # executado fica como defunct até que outro botão seja acionado. Passar
        # SIGCHLD para SIG_IGN entrega a colheita ao kernel, que a faz na hora.
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)

        device_fd = self.device.transport.fileno
        focus_fd = self.focus.fileno

        logger.info(
            "daemon ativo em %s%s",
            self.device.name,
            "" if has_focus else " (sem perfis por aplicação)",
        )

        try:
            while self._running:
                watched = [device_fd] + ([focus_fd] if focus_fd is not None else [])
                # Um gesto que depende do tempo — o hold, a janela do duplo
                # toque — nunca chegaria na hora se o laço dormisse o segundo
                # inteiro esperando um descritor falar.
                prazos = [
                    p
                    for p in (
                        self._recognizer.next_deadline(),
                        self._switcher.next_deadline(),
                    )
                    if p is not None
                ]
                espera = min([1.0, *prazos])
                try:
                    ready, _, _ = select.select(watched, [], [], espera)
                except InterruptedError:
                    continue
                except OSError as exc:
                    logger.error("o dispositivo desapareceu: %s", exc)
                    return 1

                if self._reload_requested:
                    self._reload_config()

                self._dispatch_gestures(self._recognizer.tick())
                # Confirma a escolha do alternador quando a roda para.
                self._switcher.tick()

                if focus_fd is not None and focus_fd in ready:
                    if self.focus.drain_events():
                        self._apply_for_window(self.focus.current())

                if device_fd in ready:
                    self._handle_device_event()
        finally:
            self.restore()
            self.focus.close()
            keys_backend.close()

        logger.info("daemon encerrado")
        return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="logitune-daemon",
        description="Aplica perfis do logi-tune-linux conforme a janela em foco.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra o tráfego HID++")
    parser.add_argument(
        "--write-example",
        action="store_true",
        help="escreve uma configuração de exemplo e sai",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.write_example:
        path = config_module.example_config().save()
        print(f"Configuração de exemplo escrita em {path}")
        return 0

    aviso = config_module.check_permissions()
    if aviso:
        logger.warning("%s", aviso)

    config = config_module.load()

    devices = discover_devices()
    if not devices:
        logger.error("nenhum mouse Logitech encontrado")
        return 2

    daemon = Daemon(config, devices[0])
    try:
        return daemon.run()
    finally:
        close_devices(devices)


if __name__ == "__main__":
    sys.exit(main())
