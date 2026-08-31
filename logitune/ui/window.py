# SPDX-License-Identifier: GPL-3.0-or-later
"""Janela principal do logi-tune-linux."""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from logitune.device import LogitechDevice, close_devices, discover_devices  # noqa: E402
from logitune.hidpp.device import HidppError, NoResponse  # noqa: E402
from logitune.hidpp.features.scroll import WheelMode  # noqa: E402

logger = logging.getLogger(__name__)

#: Espera antes de mandar um valor de slider ao dispositivo, para não gerar
#: uma escrita HID++ por pixel arrastado.
_DEBOUNCE_MS = 250
#: Intervalo de atualização da bateria.
_BATTERY_REFRESH_S = 60


class LogituneWindow(Adw.ApplicationWindow):
    """Janela que espelha os ajustes do dispositivo conectado."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title("Logi Tune Linux")
        self.set_default_size(560, 760)

        self._device: LogitechDevice | None = None
        self._open_devices: list[LogitechDevice] = []
        #: Suprime os handlers enquanto preenchemos os widgets com o estado
        #: lido do dispositivo — senão cada carga viraria uma escrita.
        self._loading = False
        self._debounce_ids: dict[str, int] = {}

        self._toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text("Procurar dispositivos novamente")
        refresh.connect("clicked", lambda _b: self.reload())
        header.pack_end(refresh)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toasts)
        self.set_content(toolbar)

        self._show_searching()
        self.reload()

    # -- estados da janela ---------------------------------------------

    def _show_searching(self) -> None:
        status = Adw.StatusPage(
            title="Procurando o mouse…",
            description="Verificando os dispositivos Logitech conectados.",
            icon_name="input-mouse-symbolic",
        )
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        status.set_child(spinner)
        self._toasts.set_child(status)

    def _show_not_found(self, detail: str = "") -> None:
        status = Adw.StatusPage(
            title="Nenhum mouse Logitech encontrado",
            description=detail
            or "Ligue o mouse e confira se as regras udev do logi-tune-linux "
            "estão instaladas.",
            icon_name="dialog-question-symbolic",
        )
        button = Gtk.Button(label="Procurar de novo", halign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b: self.reload())
        status.set_child(button)
        self._toasts.set_child(status)

    def _toast(self, message: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=message, timeout=4))

    # -- carga ---------------------------------------------------------

    def reload(self) -> None:
        """Procura dispositivos numa thread para não travar a interface."""
        self._show_searching()
        close_devices(self._open_devices)
        self._open_devices = []
        self._device = None

        def worker() -> None:
            try:
                devices = discover_devices()
            except Exception as exc:  # noqa: BLE001 - reportado na interface
                logger.exception("falha ao procurar dispositivos")
                GLib.idle_add(self._show_not_found, str(exc))
                return
            GLib.idle_add(self._on_devices_found, devices)

        threading.Thread(target=worker, daemon=True).start()

    def _on_devices_found(self, devices: list[LogitechDevice]) -> bool:
        self._open_devices = devices
        if not devices:
            self._show_not_found()
            return False
        self._device = devices[0]
        try:
            self._build_page()
        except Exception as exc:  # noqa: BLE001 - a janela não pode ficar presa
            # Sem isto, uma falha aqui deixaria a tela de "procurando" para
            # sempre: o GLib engole a exceção e nada troca o conteúdo.
            logger.exception("falha ao montar a interface")
            self._show_not_found(f"O dispositivo foi encontrado, mas a leitura falhou: {exc}")
            return False

        # O título só muda depois que a página existe, para que a janela nunca
        # anuncie um dispositivo que ela não conseguiu mostrar.
        self.set_title(self._device.name)
        GLib.timeout_add_seconds(_BATTERY_REFRESH_S, self._refresh_battery)
        return False

    # -- construção da página ------------------------------------------

    def _build_page(self) -> None:
        """Monta a página a partir do estado do dispositivo.

        Cada seção é montada de forma independente: outro processo pode estar
        falando com o mouse ao mesmo tempo (o nosso daemon, o Solaar) e uma
        leitura pode falhar. Uma seção que falha é omitida, e o resto da
        janela continua utilizável — travar tudo por causa de um botão seria
        desproporcional.
        """
        device = self._device
        assert device is not None

        page = Adw.PreferencesPage()
        falhas: list[str] = []

        secoes = (
            ("dispositivo", self._add_device_group),
            ("ponteiro", self._add_pointer_group),
            ("rolagem", self._add_scroll_group),
            ("botões", self._add_buttons_group),
            ("computadores", self._add_hosts_group),
        )

        self._loading = True
        try:
            for nome, montar in secoes:
                try:
                    montar(page, device)
                except (HidppError, NoResponse, OSError) as exc:
                    logger.warning("não consegui montar a seção %s: %s", nome, exc)
                    falhas.append(nome)
        finally:
            self._loading = False

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(page)
        self._toasts.set_child(scroller)

        if falhas:
            self._toast(
                f"Não foi possível ler: {', '.join(falhas)}. "
                f"Atualize para tentar de novo."
            )

    def _add_device_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        group = Adw.PreferencesGroup(title="Dispositivo")
        self._battery_row = None

        row = Adw.ActionRow(
            title=device.name,
            subtitle=f"conexão {device.identity.connection}",
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        group.add(row)

        if device.battery:
            self._battery_row = Adw.ActionRow(title="Bateria")
            self._battery_bar = Gtk.LevelBar(
                min_value=0, max_value=100, width_request=140, valign=Gtk.Align.CENTER
            )
            self._battery_row.add_suffix(self._battery_bar)
            group.add(self._battery_row)
            self._refresh_battery()

        page.add(group)

    def _add_pointer_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        if device.dpi is None:
            return
        group = Adw.PreferencesGroup(
            title="Ponteiro",
            description="Quantos pontos por polegada o sensor reporta.",
        )

        dpi_range = device.dpi.get_range()
        state = device.dpi.get_dpi()
        step = dpi_range.step or 50

        row = Adw.SpinRow.new_with_range(dpi_range.minimum, dpi_range.maximum, step)
        row.set_title("Sensibilidade (DPI)")
        row.set_subtitle(f"padrão de fábrica: {state.default}")
        row.set_value(state.current)
        row.connect("notify::value", self._on_dpi_changed)
        group.add(row)
        page.add(group)

    def _add_scroll_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        group = Adw.PreferencesGroup(title="Rolagem")
        added = False

        if device.smartshift:
            state = device.smartshift.get_state()

            ratchet = Adw.SwitchRow(
                title="Roda travada (ratchet)",
                subtitle="Desligado, a roda gira livre por inércia",
            )
            ratchet.set_active(state.mode is WheelMode.RATCHET)
            ratchet.connect("notify::active", self._on_ratchet_toggled)
            group.add(ratchet)

            point = Adw.SpinRow.new_with_range(1, 255, 1)
            point.set_title("Ponto de virada do SmartShift")
            point.set_subtitle(
                f"velocidade que solta o ratchet · padrão {state.default_auto_disengage}"
            )
            point.set_value(state.auto_disengage)
            point.connect("notify::value", self._on_smartshift_changed)
            group.add(point)
            added = True

        if device.wheel:
            wheel_state = device.wheel.get_state()

            hires = Adw.SwitchRow(
                title="Rolagem de alta resolução",
                subtitle="Rolagem suave, pixel a pixel",
            )
            hires.set_active(wheel_state.high_resolution)
            hires.connect("notify::active", self._on_hires_toggled)
            group.add(hires)

            invert = Adw.SwitchRow(title="Inverter direção da roda")
            invert.set_active(wheel_state.inverted)
            invert.connect("notify::active", self._on_invert_toggled)
            group.add(invert)
            added = True

        if device.thumbwheel:
            thumb_state = device.thumbwheel.get_state()
            thumb = Adw.SwitchRow(
                title="Inverter roda do polegar",
                subtitle="Rolagem horizontal",
            )
            thumb.set_active(thumb_state.inverted)
            thumb.connect("notify::active", self._on_thumb_toggled)
            group.add(thumb)
            added = True

        if added:
            page.add(group)

    def _add_buttons_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        if device.controls is None:
            return

        controls = device.controls.list_controls()
        remappable = [c for c in controls if c.is_remappable]
        if not remappable:
            return

        group = Adw.PreferencesGroup(
            title="Botões",
            description="Escolha o que cada botão programável deve fazer.",
        )

        for control in remappable:
            alvos = [c for c in controls if control.can_remap_to(c)]
            if not alvos:
                continue

            row = Adw.ComboRow(title=control.label)
            model = Gtk.StringList()
            for alvo in alvos:
                model.append(
                    "Padrão do botão" if alvo.control_id == control.control_id else alvo.label
                )
            row.set_model(model)

            reporting = device.controls.get_reporting(control.control_id)
            atual = reporting.remapped_to or control.control_id
            posicao = next(
                (i for i, a in enumerate(alvos) if a.control_id == atual),
                0,
            )
            row.set_selected(posicao)
            # Guardamos a tabela de alvos no próprio widget para o handler.
            row._control = control  # noqa: SLF001
            row._targets = alvos  # noqa: SLF001
            row.connect("notify::selected", self._on_button_remapped)
            group.add(row)

        page.add(group)

    def _add_hosts_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        if device.hosts is None or device.change_host is None:
            return

        hosts = device.hosts.list_hosts()

        group = Adw.PreferencesGroup(
            title="Computadores",
            description="O mouse guarda três pareamentos e alterna entre eles.",
        )

        for host in hosts:
            row = Adw.ActionRow(title=host.label, subtitle=host.bus_label)
            if host.is_current:
                badge = Gtk.Label(label="conectado")
                badge.add_css_class("success")
                badge.add_css_class("caption")
                row.add_suffix(badge)
            else:
                button = Gtk.Button(label="Trocar", valign=Gtk.Align.CENTER)
                button.connect("clicked", self._on_host_switch, host.index)
                row.add_suffix(button)
            group.add(row)

        page.add(group)

    # -- ações ---------------------------------------------------------

    def _guarded(self, action, description: str) -> None:
        """Executa uma escrita, transformando falha em aviso na interface."""
        if self._loading or self._device is None:
            return
        try:
            action()
        except (HidppError, NoResponse, OSError) as exc:
            logger.warning("%s falhou: %s", description, exc)
            self._toast(f"Não foi possível {description}.")

    def _debounce(self, key: str, delay_ms: int, action) -> None:
        """Adia uma escrita, cancelando a anterior ainda pendente."""
        if self._loading:
            return
        existing = self._debounce_ids.pop(key, None)
        if existing:
            GLib.source_remove(existing)

        def fire() -> bool:
            self._debounce_ids.pop(key, None)
            action()
            return False

        self._debounce_ids[key] = GLib.timeout_add(delay_ms, fire)

    def _on_dpi_changed(self, row: Adw.SpinRow, _param) -> None:
        value = int(row.get_value())
        self._debounce(
            "dpi",
            _DEBOUNCE_MS,
            lambda: self._guarded(
                lambda: self._device.dpi.set_dpi(value), "aplicar o DPI"
            ),
        )

    def _on_smartshift_changed(self, row: Adw.SpinRow, _param) -> None:
        value = int(row.get_value())
        self._debounce(
            "smartshift",
            _DEBOUNCE_MS,
            lambda: self._guarded(
                lambda: self._device.smartshift.set_state(auto_disengage=value),
                "ajustar o SmartShift",
            ),
        )

    def _on_ratchet_toggled(self, row: Adw.SwitchRow, _param) -> None:
        mode = WheelMode.RATCHET if row.get_active() else WheelMode.FREESPIN
        self._guarded(
            lambda: self._device.smartshift.set_state(mode=mode), "mudar o modo da roda"
        )

    def _on_hires_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._guarded(
            lambda: self._device.wheel.set_state(high_resolution=active),
            "mudar a resolução da rolagem",
        )

    def _on_invert_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._guarded(
            lambda: self._device.wheel.set_state(inverted=active), "inverter a roda"
        )

    def _on_thumb_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._guarded(
            lambda: self._device.thumbwheel.set_state(inverted=active),
            "inverter a roda do polegar",
        )

    def _on_button_remapped(self, row: Adw.ComboRow, _param) -> None:
        control = row._control  # noqa: SLF001
        targets = row._targets  # noqa: SLF001
        index = row.get_selected()
        if index >= len(targets):
            return
        target = targets[index]
        self._guarded(
            lambda: self._device.controls.set_reporting(
                control.control_id, remap_to=target.control_id
            ),
            f"remapear {control.label}",
        )

    def _on_host_switch(self, _button: Gtk.Button, host_index: int) -> None:
        if self._device is None or self._device.change_host is None:
            return
        self._toast("Trocando de computador… o mouse vai se desconectar daqui.")
        self._guarded(
            lambda: self._device.change_host.switch_to(host_index),
            "trocar de computador",
        )

    # -- atualização periódica -----------------------------------------

    def _refresh_battery(self) -> bool:
        device = self._device
        if device is None or device.battery is None:
            return False
        if getattr(self, "_battery_row", None) is None:
            return False
        try:
            status = device.battery.get_status()
        except (HidppError, NoResponse, OSError):
            return True  # tenta de novo no próximo ciclo

        if status.percentage is None:
            self._battery_row.set_subtitle(f"{status.level.name} · {status.charging.label}")
            return True

        self._battery_bar.set_value(status.percentage)
        self._battery_row.set_subtitle(f"{status.percentage}% · {status.charging.label}")
        return True

    def do_close_request(self) -> bool:
        close_devices(self._open_devices)
        return False
