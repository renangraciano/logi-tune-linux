# SPDX-License-Identifier: GPL-3.0-or-later
"""Janela principal do logi-tune-linux."""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from logitune.actions import Binding, ButtonBinding, UnknownAction, resolve  # noqa: E402
from logitune.actions.binding import STATEFUL_WHEEL_ACTIONS  # noqa: E402
from logitune.config import Match, Profile, Settings  # noqa: E402
from logitune.i18n import _  # noqa: E402
from logitune.ui.app_picker import AppPicker  # noqa: E402
from logitune.ui.button_dialog import ButtonDialog  # noqa: E402
from logitune.ui.desktop import ACCEL_PROFILES, DesktopMouseSettings  # noqa: E402
from logitune.ui.wheel_dialog import WheelDialog, mode_label  # noqa: E402
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
        #: Linhas ligadas a um campo de ``Settings``, por nome do campo, com a
        #: legenda que a linha mostra quando o valor é próprio do perfil.
        self._setting_rows: dict[str, tuple[Adw.PreferencesRow, str]] = {}
        #: O que o mouse relatou ao montar a página. É o que a linha mostra
        #: quando nem o perfil nem o global dizem nada sobre o campo.
        self._device_defaults: dict[str, object] = {}
        #: Grupos e o escopo de cada um: ``(grupo, descrição, segue_o_perfil)``.
        #: A página mistura o que muda por aplicativo com o que vale sempre, e
        #: sem dizer qual é qual as abas de perfil no topo parecem governar a
        #: página inteira — que era a maior fonte de confusão.
        self._scoped_groups: list[tuple[Adw.PreferencesGroup, str, bool]] = []
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
        # A página é remontada inteira; os registros da anterior apontariam
        # para widgets que já saíram.
        self._scoped_groups = []
        self._setting_rows = {}
        self._device_defaults = {}

        secoes = (
            ("dispositivo", self._add_device_group),
            ("ponteiro", self._add_pointer_group),
            ("rolagem", self._add_scroll_group),
            ("botões", self._add_buttons_group),
            ("gestos", self._add_gestures_group),
            ("roda do polegar", self._add_wheel_group),
            ("computadores", self._add_hosts_group),
            ("sistema", self._add_system_group),
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

        # A primeira linha focável ganhava o foco sozinha, e o rolador ia
        # atrás dela: a janela abria no meio da página, com uma linha
        # destacada como se estivesse sendo editada. Começar do topo, sem
        # nada em foco, é o que se espera de uma tela de ajustes.
        self.set_focus(None)
        GLib.idle_add(lambda: (scroller.get_vadjustment().set_value(0), False)[1])

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

        row = self._slider_row(
            _("Pointer speed (DPI)"), dpi_range.minimum, dpi_range.maximum, step
        )
        row.set_tooltip_text(
            _(
                "How far the pointer travels for the same hand movement. "
                "Higher is faster and less precise. The mouse leaves the "
                "factory at {}."
            ).format(state.default)
        )
        self._register_setting_row(
            "dpi", row, state.current, _("factory default: {}").format(state.default)
        )
        row._scale.connect("value-changed", self._on_dpi_changed)  # noqa: SLF001
        group.add(row)
        self._register_group(group, per_profile=True)
        page.add(group)

    def _add_scroll_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        group = Adw.PreferencesGroup(title=_("Scrolling"))
        added = False

        if device.smartshift:
            state = device.smartshift.get_state()

            ratchet = Adw.SwitchRow(title=_("Wheel locked (ratchet)"))
            ratchet.set_tooltip_text(
                _(
                    "On, the wheel clicks step by step. Off, it spins freely "
                    "and coasts — good for long documents."
                )
            )
            self._register_setting_row(
                "ratchet",
                ratchet,
                state.mode is WheelMode.RATCHET,
                _("Off, the wheel spins freely"),
            )
            ratchet.connect("notify::active", self._on_ratchet_toggled)
            group.add(ratchet)

            point = Adw.SpinRow.new_with_range(1, 255, 1)
            point.set_title(_("SmartShift threshold"))
            point.set_tooltip_text(
                _(
                    "How hard you have to flick the wheel before it unlocks "
                    "and spins freely. Lower unlocks sooner. The mouse leaves "
                    "the factory at {}."
                ).format(state.default_auto_disengage)
            )
            self._register_setting_row(
                "smartshift",
                point,
                state.auto_disengage,
                _("speed that releases the ratchet · default {}").format(
                    state.default_auto_disengage
                ),
            )
            point.connect("notify::value", self._on_smartshift_changed)
            group.add(point)
            added = True

        if device.wheel:
            wheel_state = device.wheel.get_state()

            hires = Adw.SwitchRow(title=_("High-resolution scrolling"))
            hires.set_tooltip_text(
                _(
                    "Scroll pixel by pixel instead of a line at a time. "
                    "Smoother, and a few older programs do not follow it."
                )
            )
            self._register_setting_row(
                "hires_scroll",
                hires,
                wheel_state.high_resolution,
                _("Smooth, pixel-by-pixel scrolling"),
            )
            hires.connect("notify::active", self._on_hires_toggled)
            group.add(hires)

            invert = Adw.SwitchRow(title=_("Invert wheel direction"))
            invert.set_tooltip_text(
                _("Push the wheel away from you to scroll down instead of up.")
            )
            self._register_setting_row(
                "invert_scroll", invert, wheel_state.inverted, ""
            )
            invert.connect("notify::active", self._on_invert_toggled)
            group.add(invert)
            added = True

        if device.thumbwheel:
            thumb_state = device.thumbwheel.get_state()
            thumb = Adw.SwitchRow(title=_("Invert the thumb wheel"))
            thumb.set_tooltip_text(
                _("Roll the thumb wheel forward to scroll left instead of right.")
            )
            self._register_setting_row(
                "invert_thumb",
                thumb,
                thumb_state.inverted,
                _("Horizontal scrolling"),
            )
            thumb.connect("notify::active", self._on_thumb_toggled)
            group.add(thumb)
            added = True

        if added:
            self._register_group(group, per_profile=True)
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
            description=_("Pick a button to choose what it does."),
        )

        self._button_rows = {}
        self._button_controls = {}

        # Houve aqui um desenho do mouse com marcadores sobre cada botão. Ele
        # saiu porque, para acertar, precisaria representar fielmente um
        # aparelho que não temos como medir — e um marcador no lugar errado
        # ensina a coisa errada, o que é pior do que não desenhar nada. A
        # lista alcança todos os botões, inclusive os que nenhum desenho
        # mostraria, e é o único caminho por teclado e leitor de tela.
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

        self._register_group(group, per_profile=True)
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

    # -- ajustes do dispositivo ----------------------------------------
    #
    # Um ajuste do mouse não é estado só do mouse: o daemon reaplica o perfil
    # a cada troca de janela, então quem não estiver no ``config.json`` é
    # desfeito na primeira vez que você muda de aplicativo. Estas linhas
    # gravam na configuração e deixam o daemon aplicar, que é o mesmo caminho
    # que os botões e os gestos já seguiam.

    @staticmethod
    def _slider_row(
        titulo: str, minimo: float, maximo: float, passo: float, *, digitos: int = 0
    ) -> Adw.ActionRow:
        """Uma linha com controle deslizante e o valor ao lado.

        A libadwaita não tem uma linha de slider pronta, e um campo de fiar
        para velocidade obriga a acertar um número quando o que se quer é
        arrastar até parecer certo. O widget fica guardado em ``_scale`` para
        ``_load_setting_row`` saber como preencher a linha.
        """
        escala = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimo, maximo, passo)
        escala.set_draw_value(True)
        escala.set_value_pos(Gtk.PositionType.RIGHT)
        escala.set_digits(digitos)
        escala.set_hexpand(True)
        escala.set_size_request(260, -1)
        escala.set_valign(Gtk.Align.CENTER)

        row = Adw.ActionRow(title=titulo)
        row.add_suffix(escala)
        row._scale = escala  # noqa: SLF001
        return row

    def _register_group(
        self, group: Adw.PreferencesGroup, *, per_profile: bool
    ) -> None:
        """Anota se um grupo segue o perfil selecionado ou vale sempre."""
        self._scoped_groups.append((group, group.get_description() or "", per_profile))
        self._refresh_group_scopes()

    def _refresh_group_scopes(self) -> None:
        """Reescreve a descrição de cada grupo com o escopo dele."""
        config = self._store.load()
        nome = self._profile_label(config)
        for group, base, per_profile in self._scoped_groups:
            if per_profile:
                # No global não há o que esclarecer: ele é a base de todos.
                nota = (
                    ""
                    if self._profile_index is None
                    else _("Follows the “{}” profile.").format(nome)
                )
            else:
                nota = _("Same in every profile.")
            group.set_description(" ".join(p for p in (base, nota) if p))

    def _setting_value(self, campo: str) -> tuple[object, bool]:
        """O valor a mostrar para um campo, e se ele vem do global.

        Um perfil que não diz nada sobre o DPI não zera o DPI: vale o global.
        Mostrar isso é o que evita a pergunta "por que mudou sozinho".
        """
        config = self._store.load()
        proprio = getattr(self._edited_settings(config), campo)
        if proprio is not None:
            return proprio, False
        if self._profile_index is not None:
            herdado = getattr(config.default, campo)
            if herdado is not None:
                return herdado, True
        return self._device_defaults.get(campo), False

    def _register_setting_row(
        self, campo: str, row, do_dispositivo, legenda: str = ""
    ) -> None:
        """Liga uma linha a um campo de ``Settings`` e a preenche."""
        self._setting_rows[campo] = (row, legenda)
        self._device_defaults[campo] = do_dispositivo
        self._load_setting_row(campo)

    def _load_setting_row(self, campo: str) -> None:
        """Põe na linha o valor em vigor, sem disparar uma escrita."""
        registro = self._setting_rows.get(campo)
        if registro is None:
            return
        row, legenda = registro
        valor, herdado = self._setting_value(campo)
        if valor is None:
            return

        anterior = self._loading
        self._loading = True
        try:
            escala = getattr(row, "_scale", None)
            if escala is not None:
                escala.set_value(float(valor))
            elif isinstance(row, Adw.SpinRow):
                row.set_value(float(valor))
            else:
                row.set_active(bool(valor))
        finally:
            self._loading = anterior

        if herdado:
            row.set_subtitle(
                _("{}  ·  inherited from Global").format(legenda)
                if legenda
                else _("inherited from Global")
            )
        else:
            row.set_subtitle(legenda)

    def _refresh_setting_rows(self) -> None:
        for campo in list(self._setting_rows):
            self._load_setting_row(campo)

    def _write_setting(self, campo: str, valor, aplicar, descricao: str) -> None:
        """Grava um ajuste no perfil em edição e o faz valer agora.

        A janela escrevia direto no mouse e não gravava nada. Como o daemon
        reaplica o perfil a cada troca de janela, o ajuste durava até a
        próxima — era o motivo de o limiar do SmartShift parecer não salvar.
        Agora quem manda é a configuração, e o mouse recebe uma cópia.
        """
        if self._loading:
            return

        def gravar(config) -> None:
            setattr(self._edited_settings(config), campo, valor)

        self._store.update(gravar)
        # Tira o "herdado do Global" da linha, que agora tem valor próprio.
        self._load_setting_row(campo)

        if not self._store.daemon_running():
            # Sem daemon ninguém aplicaria; a janela faz o papel dele.
            self._guarded(aplicar, descricao)

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
        self._refresh_group_scopes()
        self._refresh_setting_rows()
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
        for cid in list(self._button_rows):
            self._refresh_button_row_by_cid(cid)
        self._refresh_wheel()

    # -- roda do polegar -----------------------------------------------

    def _describe_wheel(self) -> str:
        """O que a roda faz hoje, em uma linha."""
        config = self._store.load()
        vinculo = self._edited_settings(config).wheel_binding()
        if vinculo.stateful:
            # O alternador é comportamento da roda, não uma entrada do
            # catálogo, então resolve() não o conhece — e sem este caso a
            # linha mostrava "window.switch_apps" cru para quem passasse por
            # ali. O rótulo é o mesmo que o editor usa.
            if vinculo.stateful in STATEFUL_WHEEL_ACTIONS:
                return mode_label("switch")
            try:
                return resolve(Binding(action=vinculo.stateful)).label
            except UnknownAction:
                return _("Unknown action: {}").format(vinculo.stateful)
        partes = []
        # Os rótulos são os mesmos do editor de propósito: "forward" e "back"
        # sozinhos colidiriam com os botões Voltar e Avançar na tradução.
        for rotulo, ligacao in (
            (_("Roll forward"), vinculo.up),
            (_("Roll back"), vinculo.down),
        ):
            if ligacao is None:
                continue
            try:
                nome = resolve(ligacao).label
            except UnknownAction:
                nome = _("Unknown action: {}").format(ligacao.action)
            partes.append(f"{rotulo}: {nome}")
        if not partes:
            return _("Horizontal scrolling")
        return "  ·  ".join(partes)

    def _edit_wheel(self) -> None:
        """Abre o editor da roda, com o mesmo catálogo dos botões."""

        def ler():
            return self._edited_settings(self._store.load()).thumbwheel

        def gravar(bruto) -> None:
            def aplicar(config) -> None:
                ajustes = self._edited_settings(config)
                ajustes.thumbwheel = bruto or None

            self._store.update(aplicar)
            self._refresh_wheel()

        config = self._store.load()
        WheelDialog(
            ler,
            gravar,
            profile=(
                None if self._profile_index is None else self._profile_label(config)
            ),
        ).present(self)

    def _clear_wheel(self) -> None:
        def remover(config) -> None:
            self._edited_settings(config).thumbwheel = None

        self._store.update(remover)
        self._refresh_wheel()
        self._toast(_("The thumb wheel scrolls sideways again."))

    def _refresh_wheel(self) -> None:
        """Atualiza a linha da roda sem remontar a página."""
        linha = getattr(self, "_wheel_row", None)
        if linha is not None:
            linha.set_subtitle(self._describe_wheel())
        atraso = getattr(self, "_switcher_delay_row", None)
        if atraso is not None:
            vinculo = self._edited_settings(self._store.load()).wheel_binding()
            atraso.set_sensitive(vinculo.stateful == "window.switch_apps")

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
        row.set_tooltip_text(
            _("Choose what “{}” does. Same button as the marker on the drawing.")
            .format(control.label)
        )

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

        config = self._store.load()
        ButtonDialog(
            control.label,
            ler,
            gravar,
            gestures_enabled=config.gestures_enabled,
            # O global não é "um perfil": é a base sobre a qual os outros se
            # aplicam, e o diálogo diz isso com outras palavras.
            profile=(
                None if self._profile_index is None else self._profile_label(config)
            ),
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
            self._register_group(group, per_profile=False)
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
        switch.set_tooltip_text(
            _(
                "Off, every button fires its action the moment you press it. "
                "On, buttons that have gestures wait for you to release before "
                "deciding what you meant."
            )
        )
        switch.connect("notify::active", self._on_gestures_toggled)
        group.add(switch)

        # Os limiares descrevem a mão de quem usa. Ficavam só no JSON, o que
        # é o mesmo que não existirem para quem não abre o arquivo — e são
        # justamente o que se quer ajustar quando um gesto dispara sozinho.
        limiares = config.gesture_thresholds()

        segurar = Adw.SpinRow.new_with_range(200, 2000, 50)
        segurar.set_title(_("Hold starts after"))
        segurar.set_subtitle(_("Below this, a press counts as a tap"))
        segurar.set_value(limiares.hold_ms)
        segurar.set_tooltip_text(
            _(
                "In milliseconds. Hold the button longer than this and it "
                "counts as a hold instead of a tap. Raise it if holds fire "
                "when you meant to click."
            )
        )
        segurar.connect("notify::value", self._on_threshold_changed, "hold_ms")
        group.add(segurar)

        duplo = Adw.SpinRow.new_with_range(150, 1000, 50)
        duplo.set_title(_("Double tap window"))
        duplo.set_subtitle(_("How long a second tap still counts as a double"))
        duplo.set_value(limiares.double_tap_ms)
        duplo.set_tooltip_text(
            _(
                "In milliseconds. Lower it if two separate taps keep being "
                "read as one double tap."
            )
        )
        duplo.connect("notify::value", self._on_threshold_changed, "double_tap_ms")
        group.add(duplo)

        arrasto = Adw.SpinRow.new_with_range(50, 800, 25)
        arrasto.set_title(_("Drag threshold"))
        arrasto.set_subtitle(
            _("Sensor units before a press becomes a drag. Raise it if a "
              "plain click sometimes turns into one")
        )
        arrasto.set_value(limiares.drag_units)
        arrasto.set_tooltip_text(
            _(
                "How far the mouse has to travel while the button is down "
                "before it counts as a drag. An ordinary click already moves "
                "the mouse about a hundred units, so values under that will "
                "misfire."
            )
        )
        arrasto.connect("notify::value", self._on_threshold_changed, "drag_units")
        group.add(arrasto)

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

        self._register_group(group, per_profile=False)
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

    def _on_threshold_changed(self, row: Adw.SpinRow, _param, chave: str) -> None:
        if self._loading:
            return
        self._debounce(
            f"gesture_{chave}",
            _DEBOUNCE_MS,
            lambda: self._store.update(
                lambda c: c.gestures.__setitem__(chave, int(row.get_value()))
            ),
        )

    #: As opções da roda, na ordem em que aparecem. O rótulo é traduzido na
    #: montagem; o valor é o que vai para o config.json.
    def _add_wheel_group(self, page: Adw.PreferencesPage, device: LogitechDevice) -> None:
        """A roda do polegar: o que ela faz e quanto espera para confirmar."""
        if device.thumbwheel is None:
            return

        config = self._store.load()
        vinculo = self._edited_settings(config).wheel_binding()

        group = Adw.PreferencesGroup(
            title=_("Thumb wheel"),
            description=_(
                "Rolling it can switch applications, or fire an action for "
                "each direction. The wheel only stops scrolling sideways when "
                "you give it something else to do."
            ),
        )

        # A roda escolhe do mesmo catálogo que os botões. Antes eram três
        # opções fixas, o que fazia a roda parecer a única parte do mouse sem
        # personalização de verdade.
        linha = Adw.ActionRow(
            title=_("What rolling does"),
            subtitle=self._describe_wheel(),
            activatable=True,
        )
        linha.set_tooltip_text(
            _(
                "Leave it on sideways scrolling to keep the system behaviour. "
                "Anything else takes the wheel over, and it stops scrolling."
            )
        )
        linha.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        linha.connect("activated", lambda _r: self._edit_wheel())
        group.add(linha)
        self._wheel_row = linha

        economia = Adw.SpinRow.new_with_range(0, 100, 5)
        economia.set_title(_("Silence haptics below"))
        economia.set_subtitle(
            _("Battery percentage under which the motor stops buzzing. "
              "Zero keeps it always on")
        )
        economia.set_value(config.haptics_below)
        economia.set_tooltip_text(
            _(
                "The motor is the hungriest part after the sensor. Below this "
                "battery percentage the gestures still work, they just stop "
                "buzzing."
            )
        )
        economia.connect("notify::value", self._on_haptics_below_changed)

        atraso = Adw.SpinRow.new_with_range(100, 5000, 50)
        atraso.set_title(_("Confirm after"))
        atraso.set_subtitle(
            _("How long the switcher waits, once the wheel stops, before "
              "bringing the chosen window forward")
        )
        atraso.set_value(config.switcher_idle_ms)
        atraso.set_sensitive(vinculo.stateful == "window.switch_apps")
        atraso.set_tooltip_text(
            _(
                "In milliseconds, and the same in every profile. Too short and "
                "the window comes forward before you finish choosing; too long "
                "and the switcher feels stuck."
            )
        )
        atraso.connect("notify::value", self._on_switcher_delay_changed)
        group.add(atraso)
        self._switcher_delay_row = atraso

        self._register_group(group, per_profile=True)
        page.add(group)

        # A economia é do dispositivo, não da roda, mas o motor háptico não
        # tem seção própria e criar uma para uma linha só seria pior.
        if device.haptic is not None:
            poupanca = Adw.PreferencesGroup(
                title=_("Power saving"),
                description=_(
                    "The haptic motor is the hungriest part after the sensor, "
                    "and buzzing on every gesture has a cost."
                ),
            )
            poupanca.add(economia)
            self._register_group(poupanca, per_profile=False)
            page.add(poupanca)

    def _on_haptics_below_changed(self, row: Adw.SpinRow, _param) -> None:
        if self._loading:
            return
        self._debounce(
            "haptics_below",
            _DEBOUNCE_MS,
            lambda: self._store.update(
                lambda c: c.power.__setitem__("haptics_below", int(row.get_value()))
            ),
        )

    def _on_switcher_delay_changed(self, row: Adw.SpinRow, _param) -> None:
        if self._loading:
            return
        # Um valor por passo do spin viraria uma escrita por clique na seta.
        self._debounce(
            "switcher_delay",
            _DEBOUNCE_MS,
            lambda: self._store.update(
                lambda c: c.wheel.__setitem__("switcher_idle_ms", int(row.get_value()))
            ),
        )

    def _add_system_group(self, page: Adw.PreferencesPage, _device: LogitechDevice) -> None:
        """Ajustes que são da sessão, não do mouse.

        Ficam por último e com a diferença dita na descrição: eles valem para
        todo apontador, não entram nos perfis, e continuam valendo depois que
        este programa sair.
        """
        self._desktop = DesktopMouseSettings()
        if not self._desktop.available:
            return

        group = Adw.PreferencesGroup(
            title=_("System"),
            description=_(
                "Session settings, not the mouse's. They apply to every "
                "pointer including the touchpad, are the same in every "
                "profile, and stay after this program is gone."
            ),
        )

        canhoto = Adw.SwitchRow(
            title=_("Left-handed"),
            subtitle=_("Swaps the left and right buttons"),
            active=self._desktop.left_handed,
        )
        canhoto.set_tooltip_text(
            _(
                "Changes the whole session, so it affects the touchpad too. "
                "Written to GNOME settings, not to the mouse."
            )
        )
        canhoto.connect("notify::active", self._on_left_handed_changed)
        group.add(canhoto)

        velocidade = self._slider_row(_("Pointer speed"), -1.0, 1.0, 0.05, digitos=2)
        velocidade._scale.add_mark(0.0, Gtk.PositionType.BOTTOM, None)  # noqa: SLF001
        velocidade.set_subtitle(
            _("How far the pointer travels, applied by the session. Separate "
              "from the DPI above, which the sensor itself uses")
        )
        velocidade._scale.set_value(self._desktop.speed)  # noqa: SLF001
        velocidade.set_tooltip_text(
            _(
                "From -1 (slowest) to 1 (fastest). This is the same slider "
                "GNOME Settings shows; the DPI above is the sensor itself, and "
                "the two multiply."
            )
        )
        velocidade._scale.connect(  # noqa: SLF001
            "value-changed", self._on_pointer_speed_changed
        )
        group.add(velocidade)

        aceleracao = Adw.ComboRow(title=_("Acceleration"))
        modelo = Gtk.StringList()
        for _valor, rotulo in ACCEL_PROFILES:
            modelo.append(_(rotulo))
        aceleracao.set_model(modelo)
        atual = self._desktop.accel_profile
        aceleracao.set_selected(
            next((i for i, (v, _r) in enumerate(ACCEL_PROFILES) if v == atual), 0)
        )
        aceleracao.set_tooltip_text(
            _(
                "Adaptive speeds the pointer up as you move faster. Flat maps "
                "movement one to one, which is what most games expect."
            )
        )
        aceleracao.connect("notify::selected", self._on_accel_profile_changed)
        group.add(aceleracao)

        page.add(group)

    def _on_left_handed_changed(self, row: Adw.SwitchRow, _param) -> None:
        if self._loading:
            return
        self._guarded(
            lambda: setattr(self._desktop, "left_handed", row.get_active()),
            _("swap the buttons"),
        )

    def _on_pointer_speed_changed(self, escala: Gtk.Scale) -> None:
        if self._loading:
            return
        valor = escala.get_value()
        self._debounce(
            "pointer_speed",
            _DEBOUNCE_MS,
            lambda: self._guarded(
                lambda: setattr(self._desktop, "speed", valor),
                _("change the pointer speed"),
            ),
        )

    def _on_accel_profile_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        self._guarded(
            lambda: setattr(self._desktop, "accel_profile", ACCEL_PROFILES[row.get_selected()][0]),
            _("change the acceleration"),
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
                button.set_tooltip_text(
                    _(
                        "The mouse leaves this computer at once. Bring it back "
                        "with the button underneath it, or from the other "
                        "computer."
                    )
                )
                button.connect("clicked", self._on_host_switch, host.index)
                row.add_suffix(button)
            group.add(row)

        self._register_group(group, per_profile=False)
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

    def _on_dpi_changed(self, escala: Gtk.Scale) -> None:
        value = int(escala.get_value())
        self._debounce(
            "dpi",
            _DEBOUNCE_MS,
            lambda: self._write_setting(
                "dpi", value, lambda: self._device.dpi.set_dpi(value), _("apply the DPI")
            ),
        )

    def _on_smartshift_changed(self, row: Adw.SpinRow, _param) -> None:
        value = int(row.get_value())
        self._debounce(
            "smartshift",
            _DEBOUNCE_MS,
            lambda: self._write_setting(
                "smartshift",
                value,
                lambda: self._device.smartshift.set_state(auto_disengage=value),
                _("adjust SmartShift"),
            ),
        )

    def _on_ratchet_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        mode = WheelMode.RATCHET if active else WheelMode.FREESPIN
        self._write_setting(
            "ratchet",
            active,
            lambda: self._device.smartshift.set_state(mode=mode),
            _("change the wheel mode"),
        )

    def _on_hires_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._write_setting(
            "hires_scroll",
            active,
            lambda: self._device.wheel.set_state(high_resolution=active),
            _("change the scroll resolution"),
        )

    def _on_invert_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._write_setting(
            "invert_scroll",
            active,
            lambda: self._device.wheel.set_state(inverted=active),
            _("invert the wheel"),
        )

    def _on_thumb_toggled(self, row: Adw.SwitchRow, _param) -> None:
        active = row.get_active()
        self._write_setting(
            "invert_thumb",
            active,
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
