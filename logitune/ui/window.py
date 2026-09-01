# SPDX-License-Identifier: GPL-3.0-or-later
"""Janela principal do logi-tune-linux."""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from logitune.actions import ButtonBinding, UnknownAction, resolve  # noqa: E402
from logitune.config import Match, Profile, Settings  # noqa: E402
from logitune.i18n import _  # noqa: E402
from logitune.ui.app_picker import AppPicker  # noqa: E402
from logitune.ui.button_dialog import ButtonDialog  # noqa: E402
from logitune.ui.mouse_view import MouseHotspotView  # noqa: E402
from logitune.ui.state import ConfigStore  # noqa: E402
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
        self._store = ConfigStore()
        #: Linhas de botão por CID, para atualizar sem remontar a página.
        self._button_rows: dict[int, Adw.ActionRow] = {}
        self._button_controls: dict[int, object] = {}
        #: Perfil em edição: ``None`` é o global, senão o índice em profiles.
        self._profile_index: int | None = None

        self._toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text(_("Search for devices again"))
        refresh.connect("clicked", lambda _b: self.reload())
        header.pack_end(refresh)

        self._profile_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=12, margin_end=12, margin_top=6, margin_bottom=6,
            visible=False,
        )

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._profile_bar)
        toolbar.set_content(self._toasts)
        self.set_content(toolbar)

        self._show_searching()
        self.reload()

    # -- estados da janela ---------------------------------------------

    def _show_searching(self) -> None:
        status = Adw.StatusPage(
            title=_("Looking for the mouse…"),
            description=_("Checking the connected Logitech devices."),
            icon_name="input-mouse-symbolic",
        )
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        status.set_child(spinner)
        self._toasts.set_child(status)

    def _show_not_found(self, detail: str = "") -> None:
        status = Adw.StatusPage(
            title=_("No Logitech mouse found"),
            description=detail
            or _(
                "Switch the mouse on and check that the logi-tune-linux udev rules "
                "are installed."
            ),
            icon_name="dialog-question-symbolic",
        )
        button = Gtk.Button(label=_("Search again"), halign=Gtk.Align.CENTER)
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
            self._show_not_found(_("The device was found, but reading it failed: {}").format(exc))
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
            ("gestos", self._add_gestures_group),
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
        self._rebuild_profile_bar()

        if falhas:
            self._toast(
                _("Could not read: {}. Refresh to try again.").format(", ".join(falhas))
            )

    def _add_device_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        group = Adw.PreferencesGroup(title=_("Device"))
        self._battery_row = None

        row = Adw.ActionRow(
            title=device.name,
            subtitle=_("connection: {}").format(device.identity.connection),
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        group.add(row)

        if device.battery:
            self._battery_row = Adw.ActionRow(title=_("Battery"))
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
            title=_("Pointer"),
            description=_("How many dots per inch the sensor reports."),
        )

        dpi_range = device.dpi.get_range()
        state = device.dpi.get_dpi()
        step = dpi_range.step or 50

        row = Adw.SpinRow.new_with_range(dpi_range.minimum, dpi_range.maximum, step)
        row.set_title(_("Sensitivity (DPI)"))
        row.set_subtitle(_("factory default: {}").format(state.default))
        row.set_value(state.current)
        row.connect("notify::value", self._on_dpi_changed)
        group.add(row)
        page.add(group)

    def _add_scroll_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        group = Adw.PreferencesGroup(title=_("Scrolling"))
        added = False

        if device.smartshift:
            state = device.smartshift.get_state()

            ratchet = Adw.SwitchRow(
                title=_("Wheel locked (ratchet)"),
                subtitle=_("Off, the wheel spins freely"),
            )
            ratchet.set_active(state.mode is WheelMode.RATCHET)
            ratchet.connect("notify::active", self._on_ratchet_toggled)
            group.add(ratchet)

            point = Adw.SpinRow.new_with_range(1, 255, 1)
            point.set_title(_("SmartShift threshold"))
            point.set_subtitle(
                _("speed that releases the ratchet · default {}").format(
                    state.default_auto_disengage
                )
            )
            point.set_value(state.auto_disengage)
            point.connect("notify::value", self._on_smartshift_changed)
            group.add(point)
            added = True

        if device.wheel:
            wheel_state = device.wheel.get_state()

            hires = Adw.SwitchRow(
                title=_("High-resolution scrolling"),
                subtitle=_("Smooth, pixel-by-pixel scrolling"),
            )
            hires.set_active(wheel_state.high_resolution)
            hires.connect("notify::active", self._on_hires_toggled)
            group.add(hires)

            invert = Adw.SwitchRow(title=_("Invert wheel direction"))
            invert.set_active(wheel_state.inverted)
            invert.connect("notify::active", self._on_invert_toggled)
            group.add(invert)
            added = True

        if device.thumbwheel:
            thumb_state = device.thumbwheel.get_state()
            thumb = Adw.SwitchRow(
                title=_("Invert the thumb wheel"),
                subtitle=_("Horizontal scrolling"),
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
        divertable = [c for c in controls if c.is_divertable]
        if not divertable and not remappable:
            return

        group = Adw.PreferencesGroup(
            title=_("Buttons"),
            description=_("Click a button on the mouse, or pick one from the list."),
        )

        self._button_rows = {}
        self._button_controls = {}

        self._mouse_view = MouseHotspotView(
            controls=divertable,
            model_name=device.name,
            binding_for=self._binding_for,
            describe_binding=self._describe_binding,
            on_configure=self._pick_action,
            on_clear=self._clear_binding,
        )
        if self._mouse_view.available:
            group.add(self._mouse_view)
        else:
            self._mouse_view = None

        # A lista fica junto do desenho, não no lugar dele. O desenho é para
        # reconhecer o botão pela posição; a lista é o que garante que nenhum
        # botão fique inalcançável — nem os que não têm lugar no desenho, como
        # o gesto virtual — e é o único caminho por teclado e leitor de tela.
        for control in divertable:
            self._button_controls[control.control_id] = control
            group.add(self._make_button_row(control))

        if not self._store.daemon_running():
            # Um vínculo sem daemon fica gravado e não acontece. Melhor dizer
            # isso agora do que deixar a pessoa achar que o botão quebrou.
            group.add(
                Adw.ActionRow(
                    title=_("The service is not running"),
                    subtitle=(
                        _(
                            "Button actions are applied by the daemon. Start it with: "
                            "systemctl --user enable --now logitune-daemon"
                        )
                    ),
                )
            )

        page.add(group)
        if remappable:
            self._add_remap_group(page, device, controls, remappable)

    # -- perfis --------------------------------------------------------

    def _edited_settings(self, config) -> Settings:
        """Os ajustes do perfil em edição.

        O global é o ``default`` da configuração; ele também é a base sobre a
        qual os outros se aplicam, e é por isso que um perfil pode deixar um
        botão em branco e ainda assim ele funcionar.
        """
        if self._profile_index is None:
            return config.default
        try:
            return config.profiles[self._profile_index].settings
        except IndexError:
            # O perfil sumiu do arquivo entre uma leitura e outra.
            self._profile_index = None
            return config.default

    def _profile_label(self, config) -> str:
        if self._profile_index is None:
            return _("Global")
        try:
            return config.profiles[self._profile_index].name
        except IndexError:
            return _("Global")

    def _rebuild_profile_bar(self) -> None:
        """Monta as abas: o global, um por aplicativo, e o botão de somar."""
        filho = self._profile_bar.get_first_child()
        while filho is not None:
            proximo = filho.get_next_sibling()
            self._profile_bar.remove(filho)
            filho = proximo

        config = self._store.load()
        abas = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        abas.add_css_class("linked")

        grupo: Gtk.ToggleButton | None = None
        for indice in [None, *range(len(config.profiles))]:
            rotulo = _("Global") if indice is None else config.profiles[indice].name
            botao = Gtk.ToggleButton(label=rotulo)
            botao.set_active(indice == self._profile_index)
            if grupo is None:
                grupo = botao
            else:
                botao.set_group(grupo)
            botao.connect("toggled", self._on_profile_toggled, indice)
            abas.append(botao)

        scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True, propagate_natural_width=True
        )
        scroller.set_child(abas)
        self._profile_bar.append(scroller)

        adicionar = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Profile for an application"))
        adicionar.add_css_class("flat")
        adicionar.connect("clicked", lambda _b: self._add_profile())
        self._profile_bar.append(adicionar)

        if self._profile_index is not None:
            remover = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Remove this profile"))
            remover.add_css_class("flat")
            remover.connect("clicked", lambda _b: self._remove_profile())
            self._profile_bar.append(remover)

        self._profile_bar.set_visible(True)

    def _on_profile_toggled(self, botao: Gtk.ToggleButton, indice) -> None:
        if not botao.get_active() or self._profile_index == indice:
            return
        self._profile_index = indice
        self._refresh_all_button_rows()

    def _add_profile(self) -> None:
        config = self._store.load()
        existentes = {c for p in config.profiles for c in p.match.wm_class}

        def escolhido(app) -> None:
            def acrescentar(cfg) -> None:
                cfg.profiles.append(
                    Profile(
                        name=app.name,
                        match=Match(wm_class=[app.wm_class]),
                        settings=Settings(),
                    )
                )

            self._store.update(acrescentar)
            # Já entra no perfil recém-criado: quem o criou quer configurá-lo.
            self._profile_index = len(self._store.load().profiles) - 1
            self._rebuild_profile_bar()
            self._refresh_all_button_rows()
            self._toast(_("Profile created for {}.").format(app.name))

        AppPicker(escolhido, existing=existentes).present(self)

    def _remove_profile(self) -> None:
        if self._profile_index is None:
            return
        indice = self._profile_index
        config = self._store.load()
        try:
            nome = config.profiles[indice].name
        except IndexError:
            return

        dialogo = Adw.AlertDialog(
            heading=_("Remove the profile {}?").format(GLib.markup_escape_text(nome)),
            body=_("That application's buttons go back to following Global."),
        )
        dialogo.add_response("cancelar", _("Cancel"))
        dialogo.add_response("remover", _("Remove"))
        dialogo.set_response_appearance("remover", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_default_response("cancelar")

        def respondeu(_d, resposta: str) -> None:
            if resposta != "remover":
                return
            self._store.update(lambda c: c.profiles.pop(indice))
            self._profile_index = None
            self._rebuild_profile_bar()
            self._refresh_all_button_rows()
            self._toast(_("Profile {} removed.").format(nome))

        dialogo.connect("response", respondeu)
        dialogo.present(self)

    def _refresh_all_button_rows(self) -> None:
        mouse_view = getattr(self, "_mouse_view", None)
        if mouse_view is not None:
            mouse_view.refresh_all()
        for cid in list(self._button_rows):
            self._refresh_button_row_by_cid(cid)

    def _describe_binding(self, binding: ButtonBinding | None) -> str:
        """Como a linha do botão descreve o que ele faz hoje."""
        if binding is None or binding.is_empty:
            return _("Button default")
        if binding.gestures:
            nomes = ", ".join(g.label for g in binding.gestures)
            return _("{} gestures: {}").format(len(binding.gestures), nomes)
        try:
            return resolve(binding.press).label
        except UnknownAction:
            # A configuração pode citar uma ação que não existe mais.
            return _("Unknown action: {}").format(binding.press.action)

    def _binding_for(self, cid: int) -> tuple[ButtonBinding | None, bool]:
        """O vínculo em vigor para este botão e se ele é herdado.

        Um perfil de aplicativo que não diz nada sobre um botão não o desliga:
        ele deixa valer o global. Mostrar isso é o que evita a pergunta "por
        que esse botão faz algo se eu não configurei nada aqui".
        """
        config = self._store.load()
        proprio = dict(self._edited_settings(config).binding_pairs()).get(cid)
        if proprio is not None and not proprio.is_empty:
            return proprio, False
        if self._profile_index is None:
            return None, False
        herdado = dict(config.default.binding_pairs()).get(cid)
        return herdado, herdado is not None

    def _make_button_row(self, control) -> Adw.ActionRow:
        row = Adw.ActionRow(title=control.label, activatable=True)

        limpar = Gtk.Button(
            icon_name="edit-clear-symbolic",
            valign=Gtk.Align.CENTER,
        )
        limpar.add_css_class("flat")
        limpar.connect("clicked", lambda _b, c=control: self._clear_binding(c))
        row.add_suffix(limpar)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        # O botão de limpar acompanha a linha, para ligar e desligar sem
        # remontar nada.
        row._clear_button = limpar  # noqa: SLF001

        row.connect("activated", lambda _r, c=control: self._pick_action(c))
        self._button_rows[control.control_id] = row
        self._refresh_button_row_by_cid(control.control_id)
        return row

    def _refresh_button_row_by_cid(self, cid: int) -> None:
        """Atualiza só a linha que mudou.

        Remontar a página inteira relê o dispositivo, e essa leitura falha
        quando o daemon está falando com o mouse ao mesmo tempo — a seção
        inteira desaparecia logo depois de atribuir uma ação.
        """
        # Hotspots da visualização do mouse.
        mouse_view = getattr(self, "_mouse_view", None)
        if mouse_view is not None:
            mouse_view.refresh_hotspot(cid)

        # Linhas de botão legadas (remap group usa-as via _button_rows).
        row = self._button_rows.get(cid)
        if row is None:
            return
        vinculo, herdado = self._binding_for(cid)
        descricao = self._describe_binding(vinculo)
        row.set_subtitle(
            _("{}  ·  inherited from Global").format(descricao) if herdado else descricao
        )

        proprio = vinculo is not None and not vinculo.is_empty and not herdado
        limpar = row._clear_button  # noqa: SLF001
        limpar.set_sensitive(proprio)
        limpar.set_tooltip_text(
            _("Go back to following Global")
            if self._profile_index is not None
            else _("Back to the button default")
        )

    def _pick_action(self, control) -> None:
        """Abre o editor do botão: uma ação, ou um gesto por movimento."""
        chave = f"0x{control.control_id:04X}"
        cid = control.control_id

        def ler() -> ButtonBinding | None:
            config = self._store.load()
            return dict(self._edited_settings(config).binding_pairs()).get(cid)

        def gravar(vinculo: ButtonBinding | None) -> None:
            def aplicar(config) -> None:
                ajustes = self._edited_settings(config)
                if vinculo is None or vinculo.is_empty:
                    ajustes.bindings.pop(chave, None)
                    # A chave antiga também precisa sair, senão o comando shell
                    # dela continuaria valendo.
                    ajustes.actions.pop(chave, None)
                else:
                    ajustes.bindings[chave] = vinculo.to_json()

            self._store.update(aplicar)
            self._refresh_button_row_by_cid(cid)

        ButtonDialog(
            control.label,
            ler,
            gravar,
            gestures_enabled=self._store.load().gestures_enabled,
        ).present(self)

    def _clear_binding(self, control) -> None:
        chave = f"0x{control.control_id:04X}"

        def remover(config) -> None:
            ajustes = self._edited_settings(config)
            ajustes.bindings.pop(chave, None)
            # A chave antiga também precisa sair, senão o comando shell dela
            # continuaria valendo e o botão não voltaria ao padrão.
            ajustes.actions.pop(chave, None)

        self._store.update(remover)
        self._refresh_button_row_by_cid(control.control_id)
        self._toast(_("{} is back to its default.").format(control.label))

    def _add_remap_group(self, page, device, controls, remappable) -> None:
        """Remapeamento no firmware, que é outra coisa e vale separar.

        Ao contrário de uma ação, isto é gravado no mouse e vale mesmo sem o
        daemon rodando — mas só sabe trocar um botão por outro.
        """
        group = Adw.PreferencesGroup(
            title=_("Swap buttons with each other"),
            description=(
                _(
                    "Written to the mouse itself: works without the service, but only "
                    "swaps one button for another button's behaviour."
                )
            ),
        )
        alguma = False
        for control in remappable:
            alvos = [c for c in controls if control.can_remap_to(c)]
            if len(alvos) < 2:
                continue

            row = Adw.ComboRow(title=control.label)
            model = Gtk.StringList()
            for alvo in alvos:
                model.append(
                    _("Button default")
                    if alvo.control_id == control.control_id
                    else alvo.label
                )
            row.set_model(model)

            reporting = device.controls.get_reporting(control.control_id)
            atual = reporting.remapped_to or control.control_id
            row.set_selected(next((i for i, a in enumerate(alvos) if a.control_id == atual), 0))
            # Guardamos a tabela de alvos no próprio widget para o handler.
            row._control = control  # noqa: SLF001
            row._targets = alvos  # noqa: SLF001
            row.connect("notify::selected", self._on_button_remapped)
            group.add(row)
            alguma = True

        if alguma:
            page.add(group)

    def _add_gestures_group(
        self, page: Adw.PreferencesPage, device: LogitechDevice
    ) -> None:
        """Interruptor dos gestos.

        Diferente das outras seções, esta não fala com o mouse: gesto é
        decisão do daemon, e mora no ``config.json``. É a primeira coisa que a
        interface grava em arquivo em vez de escrever no dispositivo.
        """
        config = self._store.load()

        group = Adw.PreferencesGroup(
            title=_("Gestures"),
            description=(
                _(
                    "A button can carry up to seven functions: tap, double tap, hold "
                    "and drag in four directions. Since nothing on screen shows which "
                    "direction does what, leave this off if you prefer one function "
                    "per button."
                )
            ),
        )

        switch = Adw.SwitchRow(
            title=_("Recognise gestures"),
            subtitle=_("Applies to buttons that have gestures configured"),
            active=config.gestures_enabled,
        )
        switch.connect("notify::active", self._on_gestures_toggled)
        group.add(switch)

        configurados = sum(
            1 for _, b in config.default.binding_pairs() if b.gestures
        )
        if not configurados:
            group.add(
                Adw.ActionRow(
                    title=_("No button has gestures"),
                    subtitle=(
                        _(
                            "Open a button above to set them up; "
                            "'logitune actions' lists what can be assigned."
                        )
                    ),
                )
            )

        page.add(group)

    def _on_gestures_toggled(self, row: Adw.SwitchRow, _param) -> None:
        if self._loading:
            return
        ligado = row.get_active()

        def aplicar() -> None:
            self._store.update(
                lambda c: c.gestures.__setitem__("enabled", ligado)
            )

        self._guarded(
            aplicar, _("switch gestures on") if ligado else _("switch gestures off")
        )

    def _add_hosts_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        if device.hosts is None or device.change_host is None:
            return

        hosts = device.hosts.list_hosts()

        group = Adw.PreferencesGroup(
            title=_("Computers"),
            description=_("The mouse stores three pairings and switches between them."),
        )

        for host in hosts:
            row = Adw.ActionRow(title=host.label, subtitle=host.bus_label)
            if host.is_current:
                badge = Gtk.Label(label=_("connected"))
                badge.add_css_class("success")
                badge.add_css_class("caption")
                row.add_suffix(badge)
            else:
                button = Gtk.Button(label=_("Switch"), valign=Gtk.Align.CENTER)
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
            self._toast(_("Could not {}.").format(description))

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
                lambda: self._device.dpi.set_dpi(value), _("apply the DPI")
            ),
        )

    def _on_smartshift_changed(self, row: Adw.SpinRow, _param) -> None:
        value = int(row.get_value())
        self._debounce(
            "smartshift",
            _DEBOUNCE_MS,
            lambda: self._guarded(
                lambda: self._device.smartshift.set_state(auto_disengage=value),
                _("adjust SmartShift"),
            ),
        )

    def _on_ratchet_toggled(self, row: Adw.SwitchRow, _param) -> None:
        mode = WheelMode.RATCHET if row.get_active() else WheelMode.FREESPIN
        self._guarded(
            lambda: self._device.smartshift.set_state(mode=mode), _("change the wheel mode")
        )

    def _on_hires_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._guarded(
            lambda: self._device.wheel.set_state(high_resolution=active),
            _("change the scroll resolution"),
        )

    def _on_invert_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._guarded(
            lambda: self._device.wheel.set_state(inverted=active), _("invert the wheel")
        )

    def _on_thumb_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._guarded(
            lambda: self._device.thumbwheel.set_state(inverted=active),
            _("invert the thumb wheel"),
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
        self._toast(_("Switching computer… the mouse will disconnect from here."))
        self._guarded(
            lambda: self._device.change_host.switch_to(host_index),
            _("switch computer"),
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
