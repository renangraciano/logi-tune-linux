# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface de linha de comando do logi-tune-linux."""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

from logitune.actions import Binding, Category, default_registry, resolve
from logitune.actions.spec import ActionError, UnknownAction
from logitune.device import LogitechDevice, close_devices, discover_devices
from logitune.hidpp.device import HidppError, NoResponse
from logitune.hidpp.features.controls import CONTROL_LABELS
from logitune.hidpp.notifications import NotificationListener
from logitune.hidpp.features.haptic import MAX_WAVEFORM, MIN_WAVEFORM
from logitune.hidpp.features.scroll import WheelMode
from logitune.hidpp.transport import TransportError, discover_nodes
from logitune.i18n import _

_OK = "\033[32m"
_WARN = "\033[33m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _supports_color() -> bool:
    return sys.stdout.isatty()


def _paint(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _supports_color() else text


def _bar(percentage: int, width: int = 20) -> str:
    filled = round(percentage / 100 * width)
    return "█" * filled + "░" * (width - filled)


# --- comandos --------------------------------------------------------


def cmd_status(device: LogitechDevice, _args: argparse.Namespace) -> int:
    identity = device.identity
    print(_paint(identity.name, _BOLD), _paint(f"({identity.connection})", _DIM))

    if device.battery:
        status = device.battery.get_status()
        if status.percentage is not None:
            color = _WARN if status.is_low else _OK
            print(
                _("  Battery      {} {}% ({})").format(
                    _paint(_bar(status.percentage), color),
                    status.percentage,
                    status.charging.label,
                )
            )
        else:
            print(_("  Battery      {} ({})").format(status.level.name, status.charging.label))

    if device.dpi:
        state = device.dpi.get_dpi()
        dpi_range = device.dpi.get_range()
        print(
            _("  Sensitivity  {} DPI ").format(state.current)
            + _paint(
                _("(default {}, range {}–{})").format(
                    state.default, dpi_range.minimum, dpi_range.maximum
                ),
                _DIM,
            )
        )

    if device.smartshift:
        state = device.smartshift.get_state()
        print(
            _("  SmartShift   {} mode, threshold {} ").format(
                state.mode.label, state.auto_disengage
            )
            + _paint(_("(default {})").format(state.default_auto_disengage), _DIM)
        )

    if device.wheel:
        state = device.wheel.get_state()
        detalhes = []
        detalhes.append(
            _("high resolution") if state.high_resolution else _("normal resolution")
        )
        if state.inverted:
            detalhes.append(_("inverted"))
        print(_("  Wheel        {}").format(", ".join(detalhes)))

    if device.thumbwheel:
        state = device.thumbwheel.get_state()
        linha = _("  Thumb wheel  {}").format(
            _("inverted") if state.inverted else _("normal")
        )
        if state.diverted:
            # Desviada, a roda para de rolar: ela manda notificações HID++ em
            # vez de eventos de rolagem, e hoje ninguém as consome.
            linha += _paint(
                _(
                    "  ⚠ diverted — will not scroll; fix with "
                    "'logitune scroll --no-thumb-divert'"
                ),
                _WARN,
            )
        print(linha)

    if device.hosts:
        hosts = device.hosts.list_hosts()
        atual = next((h for h in hosts if h.is_current), None)
        if atual:
            print(_("  Active host  channel {} ({})").format(atual.channel, atual.bus_label))

    return 0


def cmd_dpi(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.dpi is None:
        print(_("This device does not allow adjusting the DPI."), file=sys.stderr)
        return 1

    dpi_range = device.dpi.get_range()
    if args.value is None:
        state = device.dpi.get_dpi()
        print(_("{} DPI (default {})").format(state.current, state.default))
        print(
            _paint(
                _("accepted range: {}–{} in steps of {}").format(
                    dpi_range.minimum,
                    dpi_range.maximum,
                    dpi_range.step or _("fixed values"),
                ),
                _DIM,
            )
        )
        return 0

    applied = device.dpi.set_dpi(args.value)
    if applied != args.value:
        print(
            _("DPI adjusted to {} (nearest valid value to {})").format(
                applied, args.value
            )
        )
    else:
        print(_("DPI set to {}").format(applied))
    return 0


def cmd_smartshift(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.smartshift is None:
        print(_("This device has no SmartShift."), file=sys.stderr)
        return 1

    mode = None
    if args.mode == "ratchet":
        mode = WheelMode.RATCHET
    elif args.mode == "livre":
        mode = WheelMode.FREESPIN

    if args.value is None and mode is None:
        state = device.smartshift.get_state()
        print(_("{} mode, threshold {}").format(state.mode.label, state.auto_disengage))
        print(
            _paint(
                _("factory default: {}").format(state.default_auto_disengage), _DIM
            )
        )
        return 0

    state = device.smartshift.set_state(mode=mode, auto_disengage=args.value)
    print(
        _("SmartShift: {} mode, threshold {}").format(
            state.mode.label, state.auto_disengage
        )
    )
    return 0


def cmd_scroll(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.wheel is None:
        print(_("This device exposes no scroll control."), file=sys.stderr)
        return 1

    changed = False
    if args.invert is not None:
        state = device.wheel.set_state(inverted=args.invert)
        print(_("Main wheel: {}").format(_("inverted") if state.inverted else _("normal")))
        changed = True
    if args.hires is not None:
        state = device.wheel.set_state(high_resolution=args.hires)
        print(_("High resolution: {}").format(_("on") if state.high_resolution else _("off")))
        changed = True
    if args.invert_thumb is not None:
        if device.thumbwheel is None:
            print(_("This device has no thumb wheel."), file=sys.stderr)
            return 1
        state = device.thumbwheel.set_state(inverted=args.invert_thumb)
        print(_("Thumb wheel: {}").format(_("inverted") if state.inverted else _("normal")))
        changed = True
    if args.thumb_divert is not None:
        if device.thumbwheel is None:
            print(_("This device has no thumb wheel."), file=sys.stderr)
            return 1
        state = device.thumbwheel.set_state(diverted=args.thumb_divert)
        print(
            _("Thumb wheel: {}").format(
                _("diverted (will not scroll)")
                if state.diverted
                else _("scrolling normally")
            )
        )
        changed = True

    if not changed:
        state = device.wheel.get_state()
        print(
            _("main wheel: {}, {}").format(
                _("inverted") if state.inverted else _("normal"),
                _("high resolution") if state.high_resolution else _("normal resolution"),
            )
        )
        if device.thumbwheel:
            thumb = device.thumbwheel.get_state()
            print(
                _("thumb wheel: {}").format(_("inverted") if thumb.inverted else _("normal"))
                + (_(", diverted (will not scroll)") if thumb.diverted else "")
            )
    return 0


def cmd_buttons(device: LogitechDevice, _args: argparse.Namespace) -> int:
    if device.controls is None:
        print(_("This device exposes no reprogrammable buttons."), file=sys.stderr)
        return 1

    controls = device.controls.list_controls()
    by_id = {c.control_id: c for c in controls}
    print(_paint(_("{} controls").format(len(controls)), _BOLD))
    for control in controls:
        marcas = []
        if control.is_remappable:
            marcas.append(_("remappable"))
        if control.is_divertable:
            marcas.append(_("divertable"))
        sufixo = _paint(f"  [{', '.join(marcas)}]", _DIM) if marcas else ""

        atual = ""
        if control.is_remappable:
            reporting = device.controls.get_reporting(control.control_id)
            if reporting.is_remapped:
                alvo = by_id.get(reporting.remapped_to)
                nome = alvo.label if alvo else f"0x{reporting.remapped_to:04X}"
                atual = _paint(_("  → {}").format(nome), _OK)
            if reporting.diverted:
                atual += _paint(_("  (diverted)"), _WARN)

        print(f"  0x{control.control_id:04X}  {control.label:24s}{sufixo}{atual}")
    return 0


def _parse_control(text: str) -> int:
    """Aceita o CID em hexadecimal (0x0053) ou um nome ('voltar')."""
    try:
        return int(text, 0)
    except ValueError:
        pass
    needle = text.casefold()
    for control_id, label in CONTROL_LABELS.items():
        if needle in label.casefold():
            return int(control_id)
    raise argparse.ArgumentTypeError(f"controle desconhecido: {text}")


def cmd_button(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.controls is None:
        print(_("This device exposes no reprogrammable buttons."), file=sys.stderr)
        return 1

    controls = {c.control_id: c for c in device.controls.list_controls()}
    origem = controls.get(args.control)
    if origem is None:
        print(_("The device has no control 0x{:04X}.").format(args.control), file=sys.stderr)
        return 1

    if args.reset:
        device.controls.reset(args.control)
        print(_("{}: restored to default").format(origem.label))
        return 0

    if args.remap is not None:
        alvo = controls.get(args.remap)
        if alvo is None:
            print(
                _("The device has no control 0x{:04X}.").format(args.remap),
                file=sys.stderr,
            )
            return 1
        if not origem.can_remap_to(alvo):
            print(
                _("{} cannot take on the role of {} (incompatible groups).").format(
                    origem.label, alvo.label
                ),
                file=sys.stderr,
            )
            return 1
        device.controls.set_reporting(args.control, remap_to=args.remap)
        print(f"{origem.label} → {alvo.label}")
        return 0

    if args.divert is not None:
        if not origem.is_divertable:
            print(_("{} cannot be diverted.").format(origem.label), file=sys.stderr)
            return 1
        state = device.controls.set_reporting(args.control, diverted=args.divert)
        print(_("{}: {}").format(origem.label, _("diverted") if state.diverted else _("normal")))
        return 0

    reporting = device.controls.get_reporting(args.control)
    print(
        _("{}: remapped to 0x{:04X}, diverted={}").format(
            origem.label, reporting.remapped_to, reporting.diverted
        )
    )
    return 0


def cmd_hosts(device: LogitechDevice, _args: argparse.Namespace) -> int:
    if device.hosts is None:
        print(_("This device does not support multiple hosts."), file=sys.stderr)
        return 1
    for host in device.hosts.list_hosts():
        marca = _paint(_(" ← current"), _OK) if host.is_current else ""
        print(
            _("  channel {}: {:28s} [{}]{}").format(
                host.channel, host.label, host.bus_label, marca
            )
        )
    return 0


def cmd_host(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.change_host is None:
        print(_("This device does not support host switching."), file=sys.stderr)
        return 1
    hosts = device.hosts.list_hosts() if device.hosts else []
    alvo = args.channel - 1
    if hosts and not any(h.index == alvo for h in hosts):
        print(_("Channel {} does not exist on this device.").format(args.channel), file=sys.stderr)
        return 1
    print(
        _("Switching to channel {}… the mouse will disconnect from here.").format(
            args.channel
        )
    )
    device.change_host.switch_to(alvo)
    return 0


def _catalogar_waveforms(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Toca cada padrão e registra como ele é percebido.

    A sensação de um motor háptico não dá para medir por software: só quem
    está com a mão no mouse sabe se o padrão foi curto, longo, duplo ou forte.
    Este modo toca um de cada vez e monta a tabela em Markdown com o que for
    descrito.
    """
    if not sys.stdin.isatty():
        print(
            _(
                "The catalogue needs an interactive terminal to take descriptions."
            ),
            file=sys.stderr,
        )
        return 1

    print(_paint(_("Haptic pattern catalogue"), _BOLD))
    print(
        _paint(
            _(
                "Each pattern plays once. Describe what you felt and press Enter.\n"
                "  'r' replays · empty Enter skips · 'q' ends and saves what there is."
            ),
            _DIM,
        )
    )
    print()

    descricoes: dict[int, str] = {}
    for waveform in range(MIN_WAVEFORM, MAX_WAVEFORM + 1):
        while True:
            device.haptic.play(waveform)
            try:
                resposta = input(f"  padrão {waveform:2d} → ").strip()
            except EOFError:
                resposta = "q"
            if resposta.casefold() == "r":
                continue
            break
        if resposta.casefold() == "q":
            break
        if resposta:
            descricoes[waveform] = resposta

    if not descricoes:
        print(_("\nNothing described; the catalogue was not changed."))
        return 0

    linhas = [
        "| Pattern | Feel |",
        "| --- | --- |",
    ]
    for waveform in range(MIN_WAVEFORM, MAX_WAVEFORM + 1):
        linhas.append(f"| `{waveform}` | {descricoes.get(waveform, '—')} |")
    tabela = "\n".join(linhas)

    print()
    print(tabela)

    if args.output:
        destino = Path(args.output)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            "# MX Master 4 haptic waveforms\n\n"
            "HID++ feature `0x19B0`, function `0x04` (playWaveform). The "
            "firmware accepts indices 0 to 14.\n\n"
            "Catalogued by hand: a haptic motor cannot be characterised in "
            "software.\n\n"
            f"{tabela}\n"
        )
        print()
        print(_("Saved to {}").format(destino))

    return 0


def _diagnostico() -> list[tuple[bool, str, str]]:
    """Levanta o estado do que o logitune precisa para funcionar.

    Devolve triplas ``(ok, título, detalhe)``. Não abre o dispositivo: é
    chamado antes da descoberta, para que sirva justamente quando nada
    funciona.
    """
    import os
    import shutil

    itens: list[tuple[bool, str, str]] = []

    # -- regra udev --------------------------------------------------
    regra = Path("/etc/udev/rules.d/70-logitune.rules")
    itens.append(
        (
            regra.is_file(),
            _("udev rule"),
            str(regra) if regra.is_file() else _("missing — run sudo scripts/install-udev.sh"),
        )
    )

    # -- acesso ao dispositivo ---------------------------------------
    nodes = discover_nodes()
    if not nodes:
        itens.append((False, _("HID++ device"), _("no Logitech hidraw node found")))
    else:
        acessiveis = [n for n in nodes if os.access(n.path, os.R_OK | os.W_OK)]
        itens.append(
            (
                bool(acessiveis),
                _("hidraw access"),
                ", ".join(str(n.path) for n in acessiveis)
                if acessiveis
                else _("{} not permitted — reconnect the receiver").format(nodes[0].path),
            )
        )

    # -- síntese de teclas -------------------------------------------
    # find_spec responde "está instalado?" sem executar o módulo, que é
    # exatamente a pergunta — e evita importar algo só para descartar.
    tem_evdev = importlib.util.find_spec("evdev") is not None
    itens.append(
        (
            tem_evdev,
            _("evdev library"),
            _("python3-evdev available")
            if tem_evdev
            else _("missing — sudo apt install python3-evdev"),
        )
    )

    uinput = Path("/dev/uinput")
    if not uinput.exists():
        itens.append((False, _("uinput access"), _("/dev/uinput does not exist")))
    else:
        pode = os.access(uinput, os.W_OK)
        itens.append(
            (
                pode,
                _("uinput access"),
                _("writable without root")
                if pode
                else _("not permitted — install the udev rule and log out and back in"),
            )
        )

    # -- sessão gráfica ----------------------------------------------
    sessao = os.environ.get("XDG_SESSION_TYPE", _("unknown"))
    itens.append(
        (
            sessao != "wayland",
            _("graphical session"),
            f"{sessao}"
            + ("" if sessao != "wayland" else _(" — per-application profiles are disabled")),
        )
    )

    tem_xlib = importlib.util.find_spec("Xlib") is not None
    itens.append(
        (
            tem_xlib,
            "python-xlib",
            _("available (per-application profiles)")
            if tem_xlib
            else _("missing — sudo apt install python3-xlib"),
        )
    )

    # -- configuração ------------------------------------------------
    # Um JSON quebrado faz o daemon cair nos padrões em silêncio: os ajustes
    # param de valer e só o journal conta. Aqui conta na cara.
    from logitune import config as config_module

    erro = config_module.validate()
    if erro:
        itens.append((False, _("configuration"), erro))
    elif config_module.config_path().is_file():
        itens.append((True, _("configuration"), str(config_module.config_path())))

    # -- estado do dispositivo ---------------------------------------
    # A roda do polegar desviada é o legado clássico de quem usou o Solaar:
    # ele liga o desvio (thumb-scroll-mode) e, desinstalado sem restaurar,
    # deixa o flag gravado no firmware. A roda simplesmente para de rolar, e
    # nada na tela explica por quê — então explicamos aqui.
    try:
        from logitune.device import close_devices, discover_devices

        dispositivos = discover_devices()
    except (OSError, TransportError):
        dispositivos = []
    if dispositivos:
        try:
            roda = dispositivos[0].thumbwheel
            if roda is not None:
                desviada = roda.get_state().diverted
                itens.append(
                    (
                        not desviada,
                        _("thumb wheel"),
                        _("scrolling normally")
                        if not desviada
                        else _(
                            "diverted — will not scroll; fix with "
                            "'logitune scroll --no-thumb-divert'"
                        ),
                    )
                )
        except (HidppError, NoResponse, OSError):
            pass
        finally:
            close_devices(dispositivos)

    # -- daemon ------------------------------------------------------
    systemctl = shutil.which("systemctl")
    if systemctl:
        import subprocess

        estado = subprocess.run(
            [systemctl, "--user", "is-active", "logitune-daemon"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        itens.append((estado == "active", _("daemon"), estado or _("unknown")))

    return itens


def cmd_doctor(_device: LogitechDevice | None, _args: argparse.Namespace) -> int:
    """Mostra o que está pronto e o que falta para o logitune funcionar."""
    print(_paint(_("logi-tune-linux diagnosis"), _BOLD))
    print()
    problemas = 0
    for ok, titulo, detalhe in _diagnostico():
        marca = _paint("✓", _OK) if ok else _paint("✗", _WARN)
        if not ok:
            problemas += 1
        print(f"  {marca} {titulo:20s} {_paint(detalhe, _DIM)}")

    print()
    if problemas:
        print(_paint(_("{} item(s) need attention.").format(problemas), _WARN))
        return 1
    print(_paint(_("All set."), _OK))
    return 0


def cmd_haptic(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Toca um padrão de vibração no motor háptico."""
    if device.haptic is None:
        print(_("This device has no haptic motor."), file=sys.stderr)
        return 1

    if args.catalog:
        return _catalogar_waveforms(device, args)

    # --all vem antes da checagem do argumento posicional: ele dispensa o
    # número do padrão, e testar a ausência do número primeiro engoliria a
    # opção sem tocar nada.
    if args.all:
        for waveform in range(MIN_WAVEFORM, MAX_WAVEFORM + 1):
            print(_("  pattern {}…").format(waveform), flush=True)
            device.haptic.play(waveform)
            time.sleep(args.delay)
        print(_("Played all 15 patterns."))
        return 0

    if args.waveform is None:
        print(_("capabilities (raw bytes): {}").format(device.haptic.get_capabilities()))
        print(
            _paint(
                _(
                    "available patterns: {}–{} · 'logitune haptic <n>' plays one, "
                    "'logitune haptic --all' plays them all"
                ).format(MIN_WAVEFORM, MAX_WAVEFORM),
                _DIM,
            )
        )
        return 0

    try:
        played = device.haptic.play(args.waveform)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(_("Played pattern {}.").format(played))
    return 0


class _Pressionada:
    """Uma pressionada de botão sendo medida, do ▼ ao ▲."""

    def __init__(self, cid: int) -> None:
        self.cid = cid
        self.inicio = time.monotonic()
        self.dx = 0
        self.dy = 0
        self.amostras = 0
        #: Maior deslocamento instantâneo visto, útil para saber se o limiar
        #: precisa olhar velocidade além de distância.
        self.pico = 0

    def acumular(self, dx: int, dy: int) -> None:
        self.dx += dx
        self.dy += dy
        self.amostras += 1
        self.pico = max(self.pico, abs(dx), abs(dy))

    @property
    def ms(self) -> float:
        return (time.monotonic() - self.inicio) * 1000

    @property
    def distancia(self) -> float:
        return (self.dx * self.dx + self.dy * self.dy) ** 0.5

    @property
    def direcao(self) -> str:
        """O eixo dominante, que é como um arrasto vira uma direção."""
        if abs(self.dx) >= abs(self.dy):
            return "direita" if self.dx > 0 else "esquerda"
        return "baixo" if self.dy > 0 else "cima"


def _resumo_calibragem(medidas: dict[int, list[_Pressionada]], controls: dict) -> None:
    """Mostra a estatística que decide os limiares dos gestos.

    Os números do plano — limiar 50, hold 250 ms, duplo toque 300 ms — são
    chute informado. Estes são os seus.
    """
    if not medidas:
        return

    def faixa(valores: list[float], formato: str = "{:.0f}") -> str:
        ordenados = sorted(valores)
        mediana = ordenados[len(ordenados) // 2]
        return (
            _("min {}  median {}  max {}").format(
                formato.format(ordenados[0]),
                formato.format(mediana),
                formato.format(ordenados[-1]),
            )
        )

    print()
    print(_paint(_("Calibration"), _BOLD))
    for cid, lista in sorted(medidas.items()):
        rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
        print(_("  {} — {} press(es)").format(_paint(rotulo, _BOLD), len(lista)))
        print(_("    duration     {} ms").format(faixa([p.ms for p in lista])))
        print(_("    movement     {} units").format(faixa([p.distancia for p in lista])))
        print(
            _("    samples      {} per press").format(
                faixa([float(p.amostras) for p in lista])
            )
        )

    todas = [p for lista in medidas.values() for p in lista]
    paradas = [p for p in todas if p.distancia < 50]
    if paradas:
        limiar = max(p.distancia for p in paradas)
        print()
        print(
            _paint(
                _(
                    "Suggestion: a still click of yours moved at most {:.0f} units. "
                    "A comfortable threshold sits above that."
                ).format(limiar),
                _DIM,
            )
        )


def cmd_watch(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Desvia botões e mostra os eventos que o dispositivo manda.

    Serve tanto para conferir um mapeamento quanto para descobrir o que
    botões ainda não documentados reportam.
    """
    if device.controls is None:
        print(_("This device exposes no reprogrammable buttons."), file=sys.stderr)
        return 1

    controls = {c.control_id: c for c in device.controls.list_controls()}
    if args.control:
        alvos = [cid for cid in args.control if cid in controls]
        faltando = [cid for cid in args.control if cid not in controls]
        for cid in faltando:
            print(_("Warning: the device has no control 0x{:04X}.").format(cid), file=sys.stderr)
    else:
        alvos = [cid for cid, c in controls.items() if c.is_divertable]

    desviados: list[int] = []
    listener = NotificationListener(device.hidpp)

    try:
        if args.passive:
            # Não mexe no desvio: serve para observar o que o daemon já
            # configurou, sem brigar com ele pelo estado do dispositivo.
            ja_desviados = [
                cid for cid in alvos if device.controls.get_reporting(cid).diverted
            ]
            nomes = ", ".join(controls[c].label for c in ja_desviados) or _("none")
            print(_paint(_("Listening (passive). Already diverted: {}").format(nomes), _BOLD))
            if not ja_desviados:
                print(
                    _paint(
                        _(
                            "No button is diverted, so nothing will be reported. "
                            "Run without --passive to divert temporarily."
                        ),
                        _WARN,
                    )
                )
        else:
            for cid in alvos:
                if not controls[cid].is_divertable:
                    continue
                device.controls.set_reporting(cid, diverted=True, raw_xy=args.raw_xy or None)
                desviados.append(cid)

            nomes = ", ".join(controls[c].label for c in desviados) or _("none")
            print(_paint(_("Listening for events. Diverted buttons: {}").format(nomes), _BOLD))
            if args.raw_xy:
                print(
                    _paint(
                        _("Raw movement on: hold a button and drag to measure."),
                        _DIM,
                    )
                )
        print(_paint(_("Press the buttons on the mouse. Ctrl+C exits."), _DIM))

        #: Pressionadas em andamento e o histórico do que já foi solto.
        em_curso: dict[int, _Pressionada] = {}
        medidas: dict[int, list[_Pressionada]] = {}

        limite = time.monotonic() + args.seconds if args.seconds else None
        while limite is None or time.monotonic() < limite:
            notification = listener.poll(timeout=0.5)
            if notification is None:
                continue

            movimento = listener.as_raw_movement(notification)
            if movimento is not None:
                # O evento de movimento não diz de qual botão ele é: só existe
                # enquanto algum está preso. Atribuímos a todos os que estão.
                for pressionada in em_curso.values():
                    pressionada.acumular(movimento.dx, movimento.dy)
                continue

            evento = listener.as_button_event(notification)
            if evento is None:
                print(f"  {_paint(_('event'), _DIM)} {notification}")
                continue

            for cid in sorted(evento.just_pressed):
                rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
                print(f"  {_paint(_('▼ pressed '), _OK)} {rotulo} (0x{cid:04X})")
                em_curso[cid] = _Pressionada(cid)
            for cid in sorted(evento.just_released):
                rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
                pressionada = em_curso.pop(cid, None)
                if pressionada is None:
                    print(f"  {_paint(_('▲ released'), _DIM)} {rotulo} (0x{cid:04X})")
                    continue
                medidas.setdefault(cid, []).append(pressionada)
                detalhe = (
                    f"{pressionada.ms:.0f} ms, "
                    f"Δ({pressionada.dx:+d}, {pressionada.dy:+d}) "
                    f"= {pressionada.distancia:.0f} un, "
                    f"{pressionada.amostras} amostras"
                )
                if pressionada.distancia >= 20:
                    detalhe += f", {_paint(pressionada.direcao, _OK)}"
                print(f"  {_paint('▲ solto      ', _DIM)} {rotulo}  {detalhe}")
    except KeyboardInterrupt:
        print()
    finally:
        # Um botão que continuasse desviado deixaria de funcionar depois que
        # o programa saísse. Restaurar aqui não é opcional.
        for cid in desviados:
            try:
                # O raw_xy também precisa cair: deixá-lo ligado faria o mouse
                # continuar mandando movimento para ninguém.
                device.controls.set_reporting(cid, diverted=False, raw_xy=False)
            except (HidppError, NoResponse) as exc:
                print(_("Warning: 0x{:04X} stayed diverted: {}").format(cid, exc), file=sys.stderr)
        if desviados:
            print(_paint(_("Buttons restored."), _DIM))
        if args.raw_xy:
            _resumo_calibragem(medidas, controls)

    return 0


def _parse_param(texto: str) -> tuple[str, object]:
    """Lê ``chave=valor`` da linha de comando.

    Números viram inteiros e listas separadas por vírgula viram listas, que é
    o que ``mouse.dpi_cycle values=1600,2800,4000`` precisa.
    """
    chave, sep, valor = texto.partition("=")
    if not sep:
        raise ValueError(_("parameter without a value: {!r} (use key=value)").format(texto))

    def converter(bruto: str) -> object:
        try:
            return int(bruto, 0)
        except ValueError:
            return bruto

    if "," in valor:
        return chave.strip(), [converter(p.strip()) for p in valor.split(",") if p.strip()]
    return chave.strip(), converter(valor)


def cmd_actions(device: LogitechDevice | None, args: argparse.Namespace) -> int:
    """Lista o catálogo de ações, ou executa uma para testar."""
    registry = default_registry()

    if args.run:
        try:
            params = dict(_parse_param(p) for p in args.param)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        try:
            acao = resolve(Binding(action=args.run, params=params))
        except UnknownAction as exc:
            print(str(exc), file=sys.stderr)
            # Um id errado quase sempre acerta a categoria e erra o verbo
            # ("browser.voltar"), então vale procurar de novo só pelo prefixo.
            similares = registry.search(args.run) or registry.search(args.run.split(".")[0])
            if similares:
                ids = ", ".join(s.id for s in similares[:5])
                print(_("Did you mean: {}?").format(ids), file=sys.stderr)
            return 1

        disponivel = acao.available()
        if not disponivel.ok:
            print(_paint(f"{acao.label}: {disponivel.reason}", _WARN), file=sys.stderr)
            return 1
        try:
            acao.run(device)
        except ActionError as exc:
            print(_("The action failed: {}").format(exc), file=sys.stderr)
            return 1
        print(_("Ran {}.").format(_paint(acao.label, _BOLD)))
        return 0

    if args.filter:
        encontradas = registry.search(args.filter)
        if not encontradas:
            print(_("No action matches {!r}.").format(args.filter), file=sys.stderr)
            return 1
        grupos: dict[Category, list] = {}
        for spec in encontradas:
            grupos.setdefault(spec.category, []).append(spec)
        grupos = {c: grupos[c] for c in sorted(grupos, key=lambda c: c.order)}
    else:
        grupos = registry.by_category()

    destacadas = {spec.id for spec in registry.recommended()}
    indisponiveis = 0

    for categoria, specs in grupos.items():
        print()
        print(_paint(categoria.label, _BOLD))
        for spec in specs:
            disponivel = spec.available()
            if not disponivel.ok:
                indisponiveis += 1
            marca = _paint("✓", _OK) if disponivel.ok else _paint("✗", _WARN)
            estrela = _paint("★", _OK) if spec.id in destacadas else " "
            linha = f"  {marca} {estrela} {spec.id:26s} {spec.label}"
            if spec.shortcut:
                linha += _paint(f"  [{spec.shortcut}]", _DIM)
            if spec.parameters:
                nomes = ", ".join(p.name for p in spec.parameters)
                linha += _paint(f"  ({nomes})", _DIM)
            print(linha)
            if not disponivel.ok:
                print(f"        {_paint(disponivel.reason, _WARN)}")

    print()
    total = sum(len(s) for s in grupos.values())
    resumo = _("{} actions").format(total)
    if indisponiveis:
        resumo += _(", {} unavailable in this session").format(indisponiveis)
    print(_paint(resumo + _("  ·  ★ recommended"), _DIM))
    print(
        _paint(
            _(
                "Assign with \"bindings\" in ~/.config/logitune/config.json; "
                "try one with 'logitune actions --run <id>'."
            ),
            _DIM,
        )
    )
    return 0


def cmd_features(device: LogitechDevice, _args: argparse.Namespace) -> int:
    """Despeja a tabela de features — usado para engenharia reversa."""
    table = device.hidpp.feature_table()
    print(_paint(_("{} features on {}").format(len(table), device.name), _BOLD))
    for info in table:
        marcas = [f.name.lower() for f in type(info.flags) if f & info.flags]
        sufixo = _paint(f"  {', '.join(marcas)}", _DIM) if marcas else ""
        print(f"  {info.index:2d}  0x{info.feature_id:04X}  v{info.version}  {info.name}{sufixo}")
    return 0


# --- entrada ---------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logitune",
        description=_("Customise Logitech mice on Linux."),
    )
    parser.add_argument("-d", "--device", help=_("filter the device by name"))
    parser.add_argument("-v", "--verbose", action="store_true", help=_("show HID++ traffic"))
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help=_("device summary (default)")).set_defaults(func=cmd_status)

    p = sub.add_parser("dpi", help=_("read or set the sensitivity"))
    p.add_argument("value", nargs="?", type=int, help=_("desired DPI"))
    p.set_defaults(func=cmd_dpi)

    p = sub.add_parser("smartshift", help=_("switch point between ratchet and freewheel"))
    p.add_argument("value", nargs="?", type=int, help=_("threshold (1–255)"))
    p.add_argument("--mode", choices=("ratchet", "livre"), help=_("force a wheel mode"))
    p.set_defaults(func=cmd_smartshift)

    p = sub.add_parser("scroll", help=_("scroll direction and resolution"))
    p.add_argument("--invert", action=argparse.BooleanOptionalAction, help=_("invert the main wheel"))
    p.add_argument("--hires", action=argparse.BooleanOptionalAction, help=_("high-resolution scrolling"))
    p.add_argument(
        "--invert-thumb", action=argparse.BooleanOptionalAction, help=_("invert the thumb wheel")
    )
    p.add_argument(
        "--thumb-divert",
        action=argparse.BooleanOptionalAction,
        help=_("divert the thumb wheel to software; --no-thumb-divert gives scrolling back"),
    )
    p.set_defaults(func=cmd_scroll)

    sub.add_parser("buttons", help=_("list the buttons and their mappings")).set_defaults(
        func=cmd_buttons
    )

    p = sub.add_parser("button", help=_("configure a button"))
    p.add_argument("control", type=_parse_control, help=_("CID (0x0053) or name ('back')"))
    p.add_argument("--remap", type=_parse_control, help=_("CID the button should perform"))
    p.add_argument("--divert", action=argparse.BooleanOptionalAction, help=_("divert to the daemon"))
    p.add_argument("--reset", action="store_true", help=_("restore the factory default"))
    p.set_defaults(func=cmd_button)

    sub.add_parser("hosts", help=_("list the paired computers")).set_defaults(func=cmd_hosts)

    p = sub.add_parser("host", help=_("move the mouse to another computer"))
    p.add_argument("channel", type=int, choices=(1, 2, 3), help=_("target channel"))
    p.set_defaults(func=cmd_host)

    p = sub.add_parser("haptic", help=_("play a vibration pattern (MX Master 4)"))
    p.add_argument(
        "waveform",
        nargs="?",
        type=int,
        help=_("pattern to play ({}–{}); without a value, shows the capabilities").format(
            MIN_WAVEFORM, MAX_WAVEFORM
        ),
    )
    p.add_argument("--all", action="store_true", help=_("play every pattern in sequence"))
    p.add_argument(
        "--catalog",
        action="store_true",
        help=_("play each pattern and ask what it feels like, building a table"),
    )
    p.add_argument(
        "-o",
        "--output",
        help=_("file to save the catalogue in (use with --catalog)"),
    )
    p.add_argument("--delay", type=float, default=1.0, help=_("pause between patterns, in seconds"))
    p.set_defaults(func=cmd_haptic)

    p = sub.add_parser("watch", help=_("divert buttons and show the events received"))
    p.add_argument(
        "control",
        nargs="*",
        type=_parse_control,
        help=_("controls to divert (default: every divertable one)"),
    )
    p.add_argument(
        "--seconds", type=float, default=0, help=_("stop on its own after N seconds")
    )
    p.add_argument(
        "--passive",
        action="store_true",
        help=_("listen only, without diverting or restoring (coexists with the daemon)"),
    )
    p.add_argument(
        "--raw-xy",
        action="store_true",
        help=_("measure movement while a button is held, to calibrate gestures"),
    )
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("actions", help=_("list the catalogue of button actions"))
    p.add_argument("filter", nargs="?", help=_("show only the actions matching the text"))
    p.add_argument("--run", metavar="ID", help=_("run an action to try it"))
    p.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="CHAVE=VALOR",
        help=_("action parameter; may repeat"),
    )
    p.set_defaults(func=cmd_actions)

    sub.add_parser(
        "doctor", help=_("check permissions, dependencies and the daemon's state")
    ).set_defaults(func=cmd_doctor)

    sub.add_parser("features", help=_("dump the HID++ feature table")).set_defaults(
        func=cmd_features
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    handler = getattr(args, "func", cmd_status)

    # O diagnóstico existe justamente para quando o dispositivo não aparece,
    # então ele roda antes da descoberta e não depende dela. Listar o catálogo
    # também não depende: só executar uma ação é que pode precisar do mouse.
    if handler is cmd_doctor:
        return cmd_doctor(None, args)
    if handler is cmd_actions and not args.run:
        return cmd_actions(None, args)

    try:
        devices = discover_devices()
    except TransportError as exc:
        print(_("Device access error: {}").format(exc), file=sys.stderr)
        return 2

    if not devices:
        print(
            _(
                "No Logitech mouse found.\n"
                "Check that it is switched on and the udev rules are installed."
            ),
            file=sys.stderr,
        )
        return 2

    if args.device:
        needle = args.device.casefold()
        devices = [d for d in devices if needle in d.name.casefold()] or devices[:0]
        if not devices:
            print(_("No device named {!r}.").format(args.device), file=sys.stderr)
            return 2

    device = devices[0]
    try:
        return handler(device, args)
    except (HidppError, NoResponse) as exc:
        print(_("The device refused the operation: {}").format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        close_devices(devices)


if __name__ == "__main__":
    sys.exit(main())
