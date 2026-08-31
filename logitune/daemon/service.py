# SPDX-License-Identifier: GPL-3.0-or-later
"""O daemon: aplica perfis conforme a janela em foco e trata botões desviados.

Um único laço cuida das duas fontes de evento. Tanto o X quanto o hidraw
expõem um descritor de arquivo, então ficamos bloqueados em ``select`` até que
um dos dois tenha algo — sem timers, sem polling, sem consumo em repouso.
"""

from __future__ import annotations

import logging
import select
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass

from logitune import config as config_module
from logitune.config import Config, Settings
from logitune.daemon.focus import FocusWatcher, Window
from logitune.device import LogitechDevice, close_devices, discover_devices
from logitune.hidpp.device import HidppError, NoResponse
from logitune.hidpp.features.scroll import WheelMode
from logitune.hidpp.notifications import NotificationListener

logger = logging.getLogger(__name__)


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
        #: Botões que desviamos e precisamos restaurar ao sair.
        self._diverted: list[int] = []
        #: CID para comando, do perfil ativo.
        self._actions: dict[int, str] = {}

    # -- ciclo de vida -------------------------------------------------

    def stop(self, *_args) -> None:
        self._running = False

    def _setup_actions(self, settings: Settings) -> None:
        """Desvia os botões que têm comando e libera os que não têm mais."""
        if self.device.controls is None:
            return

        desired = dict(settings.action_pairs())
        controls = {c.control_id: c for c in self.device.controls.list_controls()}

        for cid in list(self._diverted):
            if cid not in desired:
                try:
                    self.device.controls.set_reporting(cid, diverted=False)
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
            try:
                self.device.controls.set_reporting(cid, diverted=True)
            except (HidppError, NoResponse) as exc:
                logger.warning("não consegui desviar %s: %s", control.label, exc)
            else:
                self._diverted.append(cid)

        self._actions = desired

    def restore(self) -> None:
        """Devolve os botões desviados ao comportamento normal.

        Sem isso, um botão desviado continuaria mudo depois que o daemon saísse.
        """
        if self.device.controls is None:
            return
        for cid in self._diverted:
            try:
                self.device.controls.set_reporting(cid, diverted=False)
            except (HidppError, NoResponse) as exc:
                logger.error("o botão 0x%04X ficou desviado: %s", cid, exc)
        self._diverted.clear()

    # -- reações -------------------------------------------------------

    def _apply_for_window(self, window: Window | None) -> None:
        window_class = window.wm_class if window else ""
        window_title = window.title if window else ""
        name, settings = self.config.settings_for(window_class, window_title)

        if name == self.state.profile_name:
            return

        logger.info("perfil %r para %s", name, window or "(sem janela)")
        changes = apply_settings(self.device, settings)
        if changes:
            logger.info("  aplicado: %s", ", ".join(changes))
        self._setup_actions(settings)
        self.state.profile_name = name
        self.state.window = window

    def _run_command(self, command: str) -> None:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            logger.error("comando mal formado %r: %s", command, exc)
            return
        if not argv:
            return
        try:
            subprocess.Popen(  # noqa: S603 - o comando vem da config do usuário
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.error("não consegui executar %r: %s", command, exc)

    def _handle_device_event(self) -> None:
        notification = self.listener.poll(timeout=0)
        if notification is None:
            return
        event = self.listener.as_button_event(notification)
        if event is None:
            logger.debug("notificação: %s", notification)
            return
        for cid in event.just_pressed:
            command = self._actions.get(cid)
            if command:
                logger.info("botão 0x%04X → %s", cid, command)
                self._run_command(command)

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
                try:
                    ready, _, _ = select.select(watched, [], [], 1.0)
                except InterruptedError:
                    continue
                except OSError as exc:
                    logger.error("o dispositivo desapareceu: %s", exc)
                    return 1

                if focus_fd is not None and focus_fd in ready:
                    if self.focus.drain_events():
                        self._apply_for_window(self.focus.current())

                if device_fd in ready:
                    self._handle_device_event()
        finally:
            self.restore()
            self.focus.close()

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
