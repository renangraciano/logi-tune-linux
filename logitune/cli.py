# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface de linha de comando do logi-tune-linux."""

from __future__ import annotations

import argparse
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
        linha = f"  Roda polegar {'invertida' if state.inverted else 'normal'}"
        if state.diverted:
            # Desviada, a roda para de rolar: ela manda notificações HID++ em
            # vez de eventos de rolagem, e hoje ninguém as consome.
            linha += _paint(
                "  ⚠ desviada — não rola; conserte com "
                "'logitune scroll --no-thumb-divert'",
                _WARN,
            )
        print(linha)

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
    if args.thumb_divert is not None:
        if device.thumbwheel is None:
            print("Este dispositivo não tem roda do polegar.", file=sys.stderr)
            return 1
        state = device.thumbwheel.set_state(diverted=args.thumb_divert)
        print(
            f"Roda do polegar: {'desviada (não rola)' if state.diverted else 'rolagem normal'}"
        )
        changed = True

    if not changed:
        state = device.wheel.get_state()
        print(
            f"roda principal: {'invertida' if state.inverted else 'normal'}, "
            f"{'alta resolução' if state.high_resolution else 'resolução normal'}"
        )
        if device.thumbwheel:
            thumb = device.thumbwheel.get_state()
            print(
                f"roda do polegar: {'invertida' if thumb.inverted else 'normal'}"
                f"{', desviada (não rola)' if thumb.diverted else ''}"
            )
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


def _catalogar_waveforms(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Toca cada padrão e registra como ele é percebido.

    A sensação de um motor háptico não dá para medir por software: só quem
    está com a mão no mouse sabe se o padrão foi curto, longo, duplo ou forte.
    Este modo toca um de cada vez e monta a tabela em Markdown com o que for
    descrito.
    """
    if not sys.stdin.isatty():
        print(
            "O catálogo precisa de um terminal interativo para receber as "
            "descrições.",
            file=sys.stderr,
        )
        return 1

    print(_paint("Catálogo de padrões hápticos", _BOLD))
    print(
        _paint(
            "Cada padrão é tocado uma vez. Descreva o que sentiu e tecle Enter.\n"
            "  'r' toca de novo · Enter vazio pula · 'q' encerra e salva o que houver.",
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
        print("\nNada descrito; o catálogo não foi alterado.")
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
        print(f"Salvo em {destino}")

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
            "Regra udev",
            str(regra) if regra.is_file() else "ausente — rode sudo scripts/install-udev.sh",
        )
    )

    # -- acesso ao dispositivo ---------------------------------------
    nodes = discover_nodes()
    if not nodes:
        itens.append((False, "Dispositivo HID++", "nenhum nó hidraw da Logitech encontrado"))
    else:
        acessiveis = [n for n in nodes if os.access(n.path, os.R_OK | os.W_OK)]
        itens.append(
            (
                bool(acessiveis),
                "Acesso ao hidraw",
                ", ".join(str(n.path) for n in acessiveis)
                if acessiveis
                else f"{nodes[0].path} sem permissão — reconecte o receptor",
            )
        )

    # -- síntese de teclas -------------------------------------------
    try:
        import evdev  # noqa: F401

        tem_evdev = True
        detalhe_evdev = "python3-evdev disponível"
    except ImportError:
        tem_evdev = False
        detalhe_evdev = "ausente — sudo apt install python3-evdev"
    itens.append((tem_evdev, "Biblioteca evdev", detalhe_evdev))

    uinput = Path("/dev/uinput")
    if not uinput.exists():
        itens.append((False, "Acesso ao uinput", "/dev/uinput não existe"))
    else:
        pode = os.access(uinput, os.W_OK)
        itens.append(
            (
                pode,
                "Acesso ao uinput",
                "gravável sem root"
                if pode
                else "sem permissão — instale a regra udev e faça logout/login",
            )
        )

    # -- sessão gráfica ----------------------------------------------
    sessao = os.environ.get("XDG_SESSION_TYPE", "desconhecida")
    itens.append(
        (
            sessao != "wayland",
            "Sessão gráfica",
            f"{sessao}"
            + ("" if sessao != "wayland" else " — perfis por aplicação ficam desativados"),
        )
    )

    try:
        import Xlib  # noqa: F401

        itens.append((True, "python-xlib", "disponível (perfis por aplicação)"))
    except ImportError:
        itens.append((False, "python-xlib", "ausente — sudo apt install python3-xlib"))

    # -- configuração ------------------------------------------------
    # Um JSON quebrado faz o daemon cair nos padrões em silêncio: os ajustes
    # param de valer e só o journal conta. Aqui conta na cara.
    from logitune import config as config_module

    erro = config_module.validate()
    if erro:
        itens.append((False, "Configuração", erro))
    elif config_module.config_path().is_file():
        itens.append((True, "Configuração", str(config_module.config_path())))

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
                        "Roda do polegar",
                        "rolagem normal"
                        if not desviada
                        else "desviada — não rola; "
                        "corrija com 'logitune scroll --no-thumb-divert'",
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
        itens.append((estado == "active", "Daemon", estado or "desconhecido"))

    return itens


def cmd_doctor(_device: LogitechDevice | None, _args: argparse.Namespace) -> int:
    """Mostra o que está pronto e o que falta para o logitune funcionar."""
    print(_paint("Diagnóstico do logi-tune-linux", _BOLD))
    print()
    problemas = 0
    for ok, titulo, detalhe in _diagnostico():
        marca = _paint("✓", _OK) if ok else _paint("✗", _WARN)
        if not ok:
            problemas += 1
        print(f"  {marca} {titulo:20s} {_paint(detalhe, _DIM)}")

    print()
    if problemas:
        print(_paint(f"{problemas} item(ns) precisam de atenção.", _WARN))
        return 1
    print(_paint("Tudo pronto.", _OK))
    return 0


def cmd_haptic(device: LogitechDevice, args: argparse.Namespace) -> int:
    """Toca um padrão de vibração no motor háptico."""
    if device.haptic is None:
        print("Este dispositivo não tem motor háptico.", file=sys.stderr)
        return 1

    if args.catalog:
        return _catalogar_waveforms(device, args)

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
            f"mín {formato.format(ordenados[0])}  "
            f"mediana {formato.format(mediana)}  "
            f"máx {formato.format(ordenados[-1])}"
        )

    print()
    print(_paint("Calibragem", _BOLD))
    for cid, lista in sorted(medidas.items()):
        rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
        print(f"  {_paint(rotulo, _BOLD)} — {len(lista)} pressionada(s)")
        print(f"    duração      {faixa([p.ms for p in lista])} ms")
        print(f"    deslocamento {faixa([p.distancia for p in lista])} unidades")
        print(f"    amostras     {faixa([float(p.amostras) for p in lista])} por pressionada")

    todas = [p for lista in medidas.values() for p in lista]
    paradas = [p for p in todas if p.distancia < 50]
    if paradas:
        limiar = max(p.distancia for p in paradas)
        print()
        print(
            _paint(
                f"Sugestão: um clique parado seu deslocou no máximo "
                f"{limiar:.0f} unidades. Um limiar confortável fica acima disso.",
                _DIM,
            )
        )


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
        if args.passive:
            # Não mexe no desvio: serve para observar o que o daemon já
            # configurou, sem brigar com ele pelo estado do dispositivo.
            ja_desviados = [
                cid for cid in alvos if device.controls.get_reporting(cid).diverted
            ]
            nomes = ", ".join(controls[c].label for c in ja_desviados) or "nenhum"
            print(_paint(f"Escutando (modo passivo). Já desviados: {nomes}", _BOLD))
            if not ja_desviados:
                print(
                    _paint(
                        "Nenhum botão está desviado, então nada será reportado. "
                        "Rode sem --passive para desviar temporariamente.",
                        _WARN,
                    )
                )
        else:
            for cid in alvos:
                if not controls[cid].is_divertable:
                    continue
                device.controls.set_reporting(cid, diverted=True, raw_xy=args.raw_xy or None)
                desviados.append(cid)

            nomes = ", ".join(controls[c].label for c in desviados) or "nenhum"
            print(_paint(f"Escutando eventos. Botões desviados: {nomes}", _BOLD))
            if args.raw_xy:
                print(
                    _paint(
                        "Movimento bruto ligado: segure um botão e arraste para medir.",
                        _DIM,
                    )
                )
        print(_paint("Pressione os botões no mouse. Ctrl+C encerra.", _DIM))

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
                print(f"  {_paint('evento', _DIM)} {notification}")
                continue

            for cid in sorted(evento.just_pressed):
                rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
                print(f"  {_paint('▼ pressionado', _OK)} {rotulo} (0x{cid:04X})")
                em_curso[cid] = _Pressionada(cid)
            for cid in sorted(evento.just_released):
                rotulo = controls[cid].label if cid in controls else f"0x{cid:04X}"
                pressionada = em_curso.pop(cid, None)
                if pressionada is None:
                    print(f"  {_paint('▲ solto      ', _DIM)} {rotulo} (0x{cid:04X})")
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
                print(f"Aviso: 0x{cid:04X} continuou desviado: {exc}", file=sys.stderr)
        if desviados:
            print(_paint("Botões restaurados.", _DIM))
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
        raise ValueError(f"parâmetro sem valor: {texto!r} (use chave=valor)")

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
                print(f"Você quis dizer: {ids}?", file=sys.stderr)
            return 1

        disponivel = acao.available()
        if not disponivel.ok:
            print(_paint(f"{acao.label}: {disponivel.reason}", _WARN), file=sys.stderr)
            return 1
        try:
            acao.run(device)
        except ActionError as exc:
            print(f"A ação falhou: {exc}", file=sys.stderr)
            return 1
        print(f"Executou {_paint(acao.label, _BOLD)}.")
        return 0

    if args.filter:
        encontradas = registry.search(args.filter)
        if not encontradas:
            print(f"Nenhuma ação casa com {args.filter!r}.", file=sys.stderr)
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
    resumo = f"{total} ações"
    if indisponiveis:
        resumo += f", {indisponiveis} indisponível(is) nesta sessão"
    print(_paint(resumo + "  ·  ★ recomendadas", _DIM))
    print(
        _paint(
            "Atribua com \"bindings\" em ~/.config/logitune/config.json; "
            "teste com 'logitune actions --run <id>'.",
            _DIM,
        )
    )
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
    p.add_argument(
        "--thumb-divert",
        action=argparse.BooleanOptionalAction,
        help="desvia a roda do polegar para o software; --no-thumb-divert devolve a rolagem",
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
    p.add_argument(
        "--catalog",
        action="store_true",
        help="toca cada padrão e pergunta como ele é, gerando uma tabela",
    )
    p.add_argument(
        "-o",
        "--output",
        help="arquivo onde salvar o catálogo (use com --catalog)",
    )
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
    p.add_argument(
        "--passive",
        action="store_true",
        help="só escuta, sem desviar nem restaurar (convive com o daemon)",
    )
    p.add_argument(
        "--raw-xy",
        action="store_true",
        help="mede o movimento com o botão preso, para calibrar os gestos",
    )
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("actions", help="lista o catálogo de ações dos botões")
    p.add_argument("filter", nargs="?", help="mostra só as ações que casam com o trecho")
    p.add_argument("--run", metavar="ID", help="executa uma ação para testá-la")
    p.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="CHAVE=VALOR",
        help="parâmetro da ação; pode repetir",
    )
    p.set_defaults(func=cmd_actions)

    sub.add_parser(
        "doctor", help="verifica permissões, dependências e estado do daemon"
    ).set_defaults(func=cmd_doctor)

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
