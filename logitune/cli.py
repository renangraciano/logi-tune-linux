"""Interface de linha de comando do logi-tune-linux."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from logitune.device import LogitechDevice, close_devices, discover_devices
from logitune.hidpp.device import HidppError, NoResponse
from logitune.hidpp.features.controls import CONTROL_LABELS
from logitune.hidpp.notifications import NotificationListener
from logitune.hidpp.features.haptic import MAX_WAVEFORM, MIN_WAVEFORM
from logitune.hidpp.features.scroll import WheelMode
from logitune.hidpp.transport import TransportError

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
                f"  Bateria      {_paint(_bar(status.percentage), color)} "
                f"{status.percentage}% ({status.charging.label})"
            )
        else:
            print(f"  Bateria      {status.level.name} ({status.charging.label})")

    if device.dpi:
        state = device.dpi.get_dpi()
        dpi_range = device.dpi.get_range()
        print(
            f"  Sensibilidade {state.current} DPI "
            f"{_paint(f'(padrão {state.default}, faixa {dpi_range.minimum}–{dpi_range.maximum})', _DIM)}"
        )

    if device.smartshift:
        state = device.smartshift.get_state()
        print(
            f"  SmartShift   modo {state.mode.label}, "
            f"ponto de virada {state.auto_disengage} "
            f"{_paint(f'(padrão {state.default_auto_disengage})', _DIM)}"
        )

    if device.wheel:
        state = device.wheel.get_state()
        detalhes = []
        detalhes.append("alta resolução" if state.high_resolution else "resolução normal")
        if state.inverted:
            detalhes.append("invertida")
        print(f"  Roda         {', '.join(detalhes)}")

    if device.thumbwheel:
        state = device.thumbwheel.get_state()
        print(
            f"  Roda polegar {'invertida' if state.inverted else 'normal'}"
            f"{', desviada' if state.diverted else ''}"
        )

    if device.hosts:
        hosts = device.hosts.list_hosts()
        atual = next((h for h in hosts if h.is_current), None)
        if atual:
            print(f"  Host ativo   canal {atual.channel} ({atual.bus_label})")

    return 0


def cmd_dpi(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.dpi is None:
        print("Este dispositivo não permite ajustar DPI.", file=sys.stderr)
        return 1

    dpi_range = device.dpi.get_range()
    if args.value is None:
        state = device.dpi.get_dpi()
        print(f"{state.current} DPI (padrão {state.default})")
        print(
            _paint(
                f"faixa aceita: {dpi_range.minimum}–{dpi_range.maximum} "
                f"em passos de {dpi_range.step or 'valores fixos'}",
                _DIM,
            )
        )
        return 0

    applied = device.dpi.set_dpi(args.value)
    if applied != args.value:
        print(f"DPI ajustado para {applied} (valor válido mais próximo de {args.value})")
    else:
        print(f"DPI definido em {applied}")
    return 0


def cmd_smartshift(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.smartshift is None:
        print("Este dispositivo não tem SmartShift.", file=sys.stderr)
        return 1

    mode = None
    if args.mode == "ratchet":
        mode = WheelMode.RATCHET
    elif args.mode == "livre":
        mode = WheelMode.FREESPIN

    if args.value is None and mode is None:
        state = device.smartshift.get_state()
        print(f"modo {state.mode.label}, ponto de virada {state.auto_disengage}")
        print(_paint(f"padrão de fábrica: {state.default_auto_disengage}", _DIM))
        return 0

    state = device.smartshift.set_state(mode=mode, auto_disengage=args.value)
    print(f"SmartShift: modo {state.mode.label}, ponto de virada {state.auto_disengage}")
    return 0


def cmd_scroll(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.wheel is None:
        print("Este dispositivo não expõe controle de rolagem.", file=sys.stderr)
        return 1

    changed = False
    if args.invert is not None:
        state = device.wheel.set_state(inverted=args.invert)
        print(f"Roda principal: {'invertida' if state.inverted else 'normal'}")
        changed = True
    if args.hires is not None:
        state = device.wheel.set_state(high_resolution=args.hires)
        print(f"Alta resolução: {'ligada' if state.high_resolution else 'desligada'}")
        changed = True
    if args.invert_thumb is not None:
        if device.thumbwheel is None:
            print("Este dispositivo não tem roda do polegar.", file=sys.stderr)
            return 1
        state = device.thumbwheel.set_state(inverted=args.invert_thumb)
        print(f"Roda do polegar: {'invertida' if state.inverted else 'normal'}")
        changed = True

    if not changed:
        state = device.wheel.get_state()
        print(
            f"roda principal: {'invertida' if state.inverted else 'normal'}, "
            f"{'alta resolução' if state.high_resolution else 'resolução normal'}"
        )
        if device.thumbwheel:
            thumb = device.thumbwheel.get_state()
            print(f"roda do polegar: {'invertida' if thumb.inverted else 'normal'}")
    return 0


def cmd_buttons(device: LogitechDevice, _args: argparse.Namespace) -> int:
    if device.controls is None:
        print("Este dispositivo não expõe botões reprogramáveis.", file=sys.stderr)
        return 1

    controls = device.controls.list_controls()
    by_id = {c.control_id: c for c in controls}
    print(_paint(f"{len(controls)} controles", _BOLD))
    for control in controls:
        marcas = []
        if control.is_remappable:
            marcas.append("remapeável")
        if control.is_divertable:
            marcas.append("desviável")
        sufixo = _paint(f"  [{', '.join(marcas)}]", _DIM) if marcas else ""

        atual = ""
        if control.is_remappable:
            reporting = device.controls.get_reporting(control.control_id)
            if reporting.is_remapped:
                alvo = by_id.get(reporting.remapped_to)
                nome = alvo.label if alvo else f"0x{reporting.remapped_to:04X}"
                atual = _paint(f"  → {nome}", _OK)
            if reporting.diverted:
                atual += _paint("  (desviado)", _WARN)

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
        print("Este dispositivo não expõe botões reprogramáveis.", file=sys.stderr)
        return 1

    controls = {c.control_id: c for c in device.controls.list_controls()}
    origem = controls.get(args.control)
    if origem is None:
        print(f"O dispositivo não tem o controle 0x{args.control:04X}.", file=sys.stderr)
        return 1

    if args.reset:
        device.controls.reset(args.control)
        print(f"{origem.label}: restaurado para o padrão")
        return 0

    if args.remap is not None:
        alvo = controls.get(args.remap)
        if alvo is None:
            print(f"O dispositivo não tem o controle 0x{args.remap:04X}.", file=sys.stderr)
            return 1
        if not origem.can_remap_to(alvo):
            print(
                f"{origem.label} não pode assumir o papel de {alvo.label} "
                f"(grupos incompatíveis).",
                file=sys.stderr,
            )
            return 1
        device.controls.set_reporting(args.control, remap_to=args.remap)
        print(f"{origem.label} → {alvo.label}")
        return 0

    if args.divert is not None:
        if not origem.is_divertable:
            print(f"{origem.label} não pode ser desviado.", file=sys.stderr)
            return 1
        state = device.controls.set_reporting(args.control, diverted=args.divert)
        print(f"{origem.label}: {'desviado' if state.diverted else 'normal'}")
        return 0

    reporting = device.controls.get_reporting(args.control)
    print(f"{origem.label}: remapeado para 0x{reporting.remapped_to:04X}, "
          f"desviado={reporting.diverted}")
    return 0


def cmd_hosts(device: LogitechDevice, _args: argparse.Namespace) -> int:
    if device.hosts is None:
        print("Este dispositivo não suporta múltiplos hosts.", file=sys.stderr)
        return 1
    for host in device.hosts.list_hosts():
        marca = _paint(" ← atual", _OK) if host.is_current else ""
        print(f"  canal {host.channel}: {host.label:28s} [{host.bus_label}]{marca}")
    return 0


def cmd_host(device: LogitechDevice, args: argparse.Namespace) -> int:
    if device.change_host is None:
        print("Este dispositivo não suporta troca de host.", file=sys.stderr)
        return 1
    hosts = device.hosts.list_hosts() if device.hosts else []
    alvo = args.channel - 1
    if hosts and not any(h.index == alvo for h in hosts):
        print(f"Canal {args.channel} não existe neste dispositivo.", file=sys.stderr)
        return 1
    print(f"Trocando para o canal {args.channel}… o mouse vai se desconectar daqui.")
    device.change_host.switch_to(alvo)
    return 0


def cmd_haptic(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Toca um padrão de vibração no motor háptico."""
    if device.haptic is None:
        print("Este dispositivo não tem motor háptico.", file=sys.stderr)
        return 1

    # --all vem antes da checagem do argumento posicional: ele dispensa o
    # número do padrão, e testar a ausência do número primeiro engoliria a
    # opção sem tocar nada.
    if args.all:
        for waveform in range(MIN_WAVEFORM, MAX_WAVEFORM + 1):
            print(f"  padrão {waveform}…", flush=True)
            device.haptic.play(waveform)
            time.sleep(args.delay)
        print("Tocou os 15 padrões.")
        return 0

    if args.waveform is None:
        print(f"capacidades (bytes crus): {device.haptic.get_capabilities()}")
        print(
            _paint(
                f"padrões disponíveis: {MIN_WAVEFORM}–{MAX_WAVEFORM} · "
                f"'logitune haptic <n>' toca um, 'logitune haptic --all' toca todos",
                _DIM,
            )
        )
        return 0

    try:
        played = device.haptic.play(args.waveform)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Tocou o padrão {played}.")
    return 0


def cmd_watch(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Desvia botões e mostra os eventos que o dispositivo manda.

    Serve tanto para conferir um mapeamento quanto para descobrir o que
    botões ainda não documentados reportam.
    """
    if device.controls is None:
        print("Este dispositivo não expõe botões reprogramáveis.", file=sys.stderr)
        return 1

    controls = {c.control_id: c for c in device.controls.list_controls()}
    if args.control:
        alvos = [cid for cid in args.control if cid in controls]
        faltando = [cid for cid in args.control if cid not in controls]
        for cid in faltando:
            print(f"Aviso: o dispositivo não tem o controle 0x{cid:04X}.", file=sys.stderr)
    else:
        alvos = [cid for cid, c in controls.items() if c.is_divertable]

    desviados: list[int] = []
    listener = NotificationListener(device.hidpp)

    try:
        for cid in alvos:
            if not controls[cid].is_divertable:
                continue
            device.controls.set_reporting(cid, diverted=True)
            desviados.append(cid)

        nomes = ", ".join(controls[c].label for c in desviados) or "nenhum"
        print(_paint(f"Escutando eventos. Botões desviados: {nomes}", _BOLD))
        print(_paint("Pressione os botões no mouse. Ctrl+C encerra.", _DIM))

        limite = time.monotonic() + args.seconds if args.seconds else None
        while limite is None or time.monotonic() < limite:
            notification = listener.poll(timeout=0.5)
            if notification is None:
                continue

            evento = listener.as_button_event(notification)
            if evento is None:
                print(f"  {_paint('evento', _DIM)} {notification}")
                continue

            for cid in sorted(evento.just_pressed):
                rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
                print(f"  {_paint('▼ pressionado', _OK)} {rotulo} (0x{cid:04X})")
            for cid in sorted(evento.just_released):
                rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
                print(f"  {_paint('▲ solto      ', _DIM)} {rotulo} (0x{cid:04X})")
    except KeyboardInterrupt:
        print()
    finally:
        # Um botão que continuasse desviado deixaria de funcionar depois que
        # o programa saísse. Restaurar aqui não é opcional.
        for cid in desviados:
            try:
                device.controls.set_reporting(cid, diverted=False)
            except (HidppError, NoResponse) as exc:
                print(f"Aviso: 0x{cid:04X} continuou desviado: {exc}", file=sys.stderr)
        if desviados:
            print(_paint("Botões restaurados.", _DIM))

    return 0


def cmd_features(device: LogitechDevice, _args: argparse.Namespace) -> int:
    """Despeja a tabela de features — usado para engenharia reversa."""
    table = device.hidpp.feature_table()
    print(_paint(f"{len(table)} features em {device.name}", _BOLD))
    for info in table:
        marcas = [f.name.lower() for f in type(info.flags) if f & info.flags]
        sufixo = _paint(f"  {', '.join(marcas)}", _DIM) if marcas else ""
        print(f"  {info.index:2d}  0x{info.feature_id:04X}  v{info.version}  {info.name}{sufixo}")
    return 0


# --- entrada ---------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logitune",
        description="Personalização de mouses Logitech no Linux.",
    )
    parser.add_argument("-d", "--device", help="filtra o dispositivo pelo nome")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra o tráfego HID++")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="resumo do dispositivo (padrão)").set_defaults(func=cmd_status)

    p = sub.add_parser("dpi", help="lê ou define a sensibilidade")
    p.add_argument("value", nargs="?", type=int, help="DPI desejado")
    p.set_defaults(func=cmd_dpi)

    p = sub.add_parser("smartshift", help="ponto de troca entre ratchet e roda livre")
    p.add_argument("value", nargs="?", type=int, help="ponto de virada (1–255)")
    p.add_argument("--mode", choices=("ratchet", "livre"), help="força um modo de roda")
    p.set_defaults(func=cmd_smartshift)

    p = sub.add_parser("scroll", help="direção e resolução da rolagem")
    p.add_argument("--invert", action=argparse.BooleanOptionalAction, help="inverte a roda principal")
    p.add_argument("--hires", action=argparse.BooleanOptionalAction, help="rolagem de alta resolução")
    p.add_argument(
        "--invert-thumb", action=argparse.BooleanOptionalAction, help="inverte a roda do polegar"
    )
    p.set_defaults(func=cmd_scroll)

    sub.add_parser("buttons", help="lista os botões e seus mapeamentos").set_defaults(
        func=cmd_buttons
    )

    p = sub.add_parser("button", help="configura um botão")
    p.add_argument("control", type=_parse_control, help="CID (0x0053) ou nome ('voltar')")
    p.add_argument("--remap", type=_parse_control, help="CID que o botão deve executar")
    p.add_argument("--divert", action=argparse.BooleanOptionalAction, help="desvia para o daemon")
    p.add_argument("--reset", action="store_true", help="restaura o padrão de fábrica")
    p.set_defaults(func=cmd_button)

    sub.add_parser("hosts", help="lista os computadores pareados").set_defaults(func=cmd_hosts)

    p = sub.add_parser("host", help="troca o mouse para outro computador")
    p.add_argument("channel", type=int, choices=(1, 2, 3), help="canal de destino")
    p.set_defaults(func=cmd_host)

    p = sub.add_parser("haptic", help="toca um padrão de vibração (MX Master 4)")
    p.add_argument(
        "waveform",
        nargs="?",
        type=int,
        help=f"padrão a tocar ({MIN_WAVEFORM}–{MAX_WAVEFORM}); sem valor, mostra as capacidades",
    )
    p.add_argument("--all", action="store_true", help="toca todos os padrões em sequência")
    p.add_argument("--delay", type=float, default=1.0, help="pausa entre padrões, em segundos")
    p.set_defaults(func=cmd_haptic)

    p = sub.add_parser("watch", help="desvia botões e mostra os eventos recebidos")
    p.add_argument(
        "control",
        nargs="*",
        type=_parse_control,
        help="controles a desviar (padrão: todos os desviáveis)",
    )
    p.add_argument(
        "--seconds", type=float, default=0, help="encerra sozinho após N segundos"
    )
    p.set_defaults(func=cmd_watch)

    sub.add_parser("features", help="despeja a tabela de features HID++").set_defaults(
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

    try:
        devices = discover_devices()
    except TransportError as exc:
        print(f"Erro de acesso ao dispositivo: {exc}", file=sys.stderr)
        return 2

    if not devices:
        print(
            "Nenhum mouse Logitech encontrado.\n"
            "Verifique se ele está ligado e se as regras udev foram instaladas.",
            file=sys.stderr,
        )
        return 2

    if args.device:
        needle = args.device.casefold()
        devices = [d for d in devices if needle in d.name.casefold()] or devices[:0]
        if not devices:
            print(f"Nenhum dispositivo com o nome {args.device!r}.", file=sys.stderr)
            return 2

    device = devices[0]
    try:
        return handler(device, args)
    except (HidppError, NoResponse) as exc:
        print(f"O dispositivo recusou a operação: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        close_devices(devices)


if __name__ == "__main__":
    sys.exit(main())
