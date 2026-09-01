# SPDX-License-Identifier: GPL-3.0-or-later
"""Visualização do mouse com hotspots clicáveis sobre os botões.

Mostra a imagem do mouse com marcadores ⊕ posicionados sobre cada botão
programável. Clicar num marcador abre um popover com o nome do botão e a
ação configurada, de onde é possível abrir o diálogo completo de edição.

As coordenadas dos hotspots são definidas como percentuais relativos à imagem;
cada modelo de mouse terá seu próprio conjunto.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from logitune.i18n import _  # noqa: E402

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent / "assets"
_CSS_LOADED = False


def _ensure_css() -> None:
    """Carrega o CSS dos hotspots uma única vez."""
    global _CSS_LOADED  # noqa: PLW0603
    if _CSS_LOADED:
        return
    css_path = _ASSETS / "hotspot.css"
    if not css_path.exists():
        logger.warning("CSS dos hotspots não encontrado: %s", css_path)
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(str(css_path))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    _CSS_LOADED = True


# ---------------------------------------------------------------------------
# Coordenadas dos hotspots por modelo
# ---------------------------------------------------------------------------

#: Posições relativas (x%, y%) de cada Control ID na imagem do MX Master 4.
#: Serão convertidas em pixels em tempo de execução com base no tamanho real
#: da imagem renderizada.
MX_MASTER_4_HOTSPOTS: dict[int, tuple[float, float]] = {
    0x0052: (54.0, 26.0),   # Middle button (scroll wheel click)
    0x0053: (30.0, 51.0),   # Back
    0x0056: (27.0, 57.0),   # Forward
    0x00C3: (34.0, 46.0),   # Gesture button
    0x00C4: (44.0, 35.0),   # SmartShift (mode shift)
    0x01A0: (24.0, 62.0),   # Actions Ring (MX Master 4 only)
}

#: Registro de modelos → (nome da imagem, mapa de hotspots).
MODEL_REGISTRY: dict[str, tuple[str, dict[int, tuple[float, float]]]] = {
    "MX Master 4": ("mx_master4.png", MX_MASTER_4_HOTSPOTS),
}


class MouseHotspotView(Gtk.Box):
    """Mostra a imagem do mouse com hotspots ⊕ nos botões programáveis.

    Parameters
    ----------
    controls:
        Lista de ``ControlInfo`` divertíveis do dispositivo.
    model_name:
        Nome do dispositivo (ex: ``"MX Master 4"``), usado para escolher
        a imagem e o mapa de coordenadas. Se o modelo não estiver no
        registro, nenhum hotspot é mostrado.
    binding_for:
        Função ``(cid) -> (ButtonBinding | None, bool)`` que devolve o
        vínculo em vigor para um botão e se ele é herdado.
    describe_binding:
        Função ``(ButtonBinding | None) -> str`` que descreve um vínculo
        em texto legível.
    on_configure:
        Callback ``(control) -> None`` chamado quando o usuário quer
        configurar um botão (abre o ButtonDialog).
    on_clear:
        Callback ``(control) -> None`` chamado quando o usuário quer
        limpar o vínculo do botão.
    """

    def __init__(
        self,
        controls: list,
        model_name: str,
        binding_for: Callable,
        describe_binding: Callable,
        on_configure: Callable,
        on_clear: Callable,
    ) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
        )
        self.add_css_class("mouse-view-container")
        _ensure_css()

        self._controls = {c.control_id: c for c in controls}
        self._binding_for = binding_for
        self._describe_binding = describe_binding
        self._on_configure = on_configure
        self._on_clear = on_clear
        self._active_cid: int | None = None

        # Encontrar imagem e mapa de hotspots para o modelo
        entry = MODEL_REGISTRY.get(model_name)
        if entry is None:
            # Tentar correspondência parcial
            for name, data in MODEL_REGISTRY.items():
                if name.casefold() in model_name.casefold():
                    entry = data
                    break

        if entry is None:
            logger.info(
                "Modelo %r não tem mapa de hotspots; exibindo sem marcadores.", model_name,
            )
            self._hotspot_map: dict[int, tuple[float, float]] = {}
            image_name = "mx_master4.png"
        else:
            image_name, self._hotspot_map = entry

        image_path = _ASSETS / image_name
        if not image_path.exists():
            logger.warning("Imagem do mouse não encontrada: %s", image_path)
            return

        # -- Montagem do widget --------------------------------------------

        self._overlay = Gtk.Overlay()

        self._picture = Gtk.Picture.new_for_filename(str(image_path))
        self._picture.set_can_shrink(True)
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._picture.set_size_request(-1, 350)
        self._overlay.set_child(self._picture)

        # O Gtk.Fixed posiciona os hotspots sobre a imagem. As coordenadas
        # são recalculadas sempre que o widget muda de tamanho.
        self._fixed = Gtk.Fixed()
        self._overlay.add_overlay(self._fixed)

        self.append(self._overlay)

        #: Mapeamento CID → botão GTK no overlay.
        self._hotspot_buttons: dict[int, Gtk.Button] = {}
        #: Mapeamento CID → popover GTK.
        self._hotspot_popovers: dict[int, Gtk.Popover] = {}

        for cid, (x_pct, y_pct) in self._hotspot_map.items():
            if cid not in self._controls:
                continue
            self._create_hotspot(cid, x_pct, y_pct)

        # Reposiciona os hotspots quando o widget redimensiona.
        self._picture.connect("notify::paintable", lambda *_: self._reposition())

        # Legenda
        label = Gtk.Label(
            label=_("Click a button on the mouse to customise it."),
            margin_top=8,
        )
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        self.append(label)

        # Atraso para posicionar os hotspots após o layout inicial.
        GLib.idle_add(self._reposition)

    # -- Criação de hotspots -----------------------------------------------

    def _create_hotspot(self, cid: int, x_pct: float, y_pct: float) -> None:
        """Cria um marcador ⊕ para o botão de Control ID ``cid``."""
        control = self._controls[cid]

        btn = Gtk.Button()
        btn.set_child(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        btn.add_css_class("hotspot-button")
        btn.add_css_class("circular")
        btn.add_css_class("pulse")
        btn.set_tooltip_text(control.label)
        btn.connect("clicked", self._on_hotspot_clicked, cid)

        # Guardar a posição percentual como atributo do botão.
        btn._x_pct = x_pct  # noqa: SLF001
        btn._y_pct = y_pct  # noqa: SLF001

        self._fixed.put(btn, 0, 0)
        self._hotspot_buttons[cid] = btn

        # Popover
        popover = self._create_popover(cid)
        popover.set_parent(btn)
        self._hotspot_popovers[cid] = popover

    def _create_popover(self, cid: int) -> Gtk.Popover:
        """Popover com nome do botão, ação configurada e botões de ação."""
        control = self._controls[cid]
        binding, inherited = self._binding_for(cid)
        description = self._describe_binding(binding)

        popover = Gtk.Popover()
        popover.add_css_class("hotspot-popover")
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_autohide(True)
        popover.connect("closed", self._on_popover_closed, cid)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("hotspot-popover-box")

        title = Gtk.Label(label=control.label, xalign=0)
        title.add_css_class("hotspot-popover-title")
        box.append(title)

        subtitle_text = description
        if inherited:
            subtitle_text = _("{}  ·  inherited from Global").format(description)
        subtitle = Gtk.Label(label=subtitle_text, xalign=0, wrap=True)
        subtitle.add_css_class("hotspot-popover-subtitle")
        box.append(subtitle)

        actions_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.END,
        )
        actions_box.add_css_class("hotspot-popover-actions")

        # Botão limpar
        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_btn.add_css_class("flat")
        clear_btn.set_tooltip_text(_("Back to the button default"))
        own_binding = binding is not None and not binding.is_empty and not inherited
        clear_btn.set_sensitive(own_binding)
        clear_btn.connect("clicked", self._on_clear_clicked, cid, popover)
        actions_box.append(clear_btn)

        # Botão configurar
        config_btn = Gtk.Button(label=_("Configure"))
        config_btn.add_css_class("suggested-action")
        config_btn.add_css_class("pill")
        config_btn.connect("clicked", self._on_configure_clicked, cid, popover)
        actions_box.append(config_btn)

        box.append(actions_box)
        popover.set_child(box)
        return popover

    # -- Posicionamento ----------------------------------------------------

    def _reposition(self) -> bool:
        """Recalcula a posição de cada hotspot com base no tamanho atual."""
        alloc = self._picture.get_allocation()
        if alloc.width <= 1 or alloc.height <= 1:
            return False  # Ainda sem layout

        # O Gtk.Picture com ContentFit.CONTAIN pode ter barras; precisamos
        # calcular a área efetiva da imagem.
        paintable = self._picture.get_paintable()
        if paintable is None:
            return False

        intrinsic_w = paintable.get_intrinsic_width()
        intrinsic_h = paintable.get_intrinsic_height()
        if intrinsic_w <= 0 or intrinsic_h <= 0:
            return False

        img_ratio = intrinsic_w / intrinsic_h
        widget_ratio = alloc.width / alloc.height

        if widget_ratio > img_ratio:
            # Imagem pilotada pela altura; barras laterais
            rendered_h = alloc.height
            rendered_w = rendered_h * img_ratio
        else:
            # Imagem pilotada pela largura; barras acima/abaixo
            rendered_w = alloc.width
            rendered_h = rendered_w / img_ratio

        offset_x = (alloc.width - rendered_w) / 2
        offset_y = (alloc.height - rendered_h) / 2

        btn_half = 14  # Metade do tamanho do botão (28px / 2)

        for cid, btn in self._hotspot_buttons.items():
            x_pct = btn._x_pct / 100.0  # noqa: SLF001
            y_pct = btn._y_pct / 100.0  # noqa: SLF001
            px = offset_x + x_pct * rendered_w - btn_half
            py = offset_y + y_pct * rendered_h - btn_half
            self._fixed.move(btn, px, py)

        return False  # Não repetir o idle_add

    # -- Interação ---------------------------------------------------------

    def _on_hotspot_clicked(self, _btn: Gtk.Button, cid: int) -> None:
        """Abre o popover do hotspot clicado."""
        # Desativar o anterior
        if self._active_cid is not None and self._active_cid != cid:
            old_btn = self._hotspot_buttons.get(self._active_cid)
            if old_btn is not None:
                old_btn.remove_css_class("active")
            old_pop = self._hotspot_popovers.get(self._active_cid)
            if old_pop is not None:
                old_pop.popdown()

        self._active_cid = cid
        btn = self._hotspot_buttons[cid]
        btn.add_css_class("active")

        # Recriar o popover para refletir o estado atual
        old_popover = self._hotspot_popovers.get(cid)
        if old_popover is not None:
            old_popover.unparent()
        popover = self._create_popover(cid)
        popover.set_parent(btn)
        self._hotspot_popovers[cid] = popover
        popover.popup()

    def _on_popover_closed(self, _popover: Gtk.Popover, cid: int) -> None:
        """Desativa o hotspot quando o popover fecha."""
        if self._active_cid == cid:
            btn = self._hotspot_buttons.get(cid)
            if btn is not None:
                btn.remove_css_class("active")
            self._active_cid = None

    def _on_configure_clicked(
        self, _btn: Gtk.Button, cid: int, popover: Gtk.Popover,
    ) -> None:
        """Abre o diálogo completo de edição do botão."""
        popover.popdown()
        control = self._controls.get(cid)
        if control is not None:
            self._on_configure(control)

    def _on_clear_clicked(
        self, _btn: Gtk.Button, cid: int, popover: Gtk.Popover,
    ) -> None:
        """Limpa o vínculo do botão."""
        popover.popdown()
        control = self._controls.get(cid)
        if control is not None:
            self._on_clear(control)

    # -- API pública -------------------------------------------------------

    def refresh_hotspot(self, cid: int) -> None:
        """Atualiza o popover de um hotspot sem recriar o widget inteiro.

        Chamado por ``_refresh_button_row_by_cid`` na janela principal.
        """
        btn = self._hotspot_buttons.get(cid)
        if btn is None:
            return
        # Atualizar tooltip
        control = self._controls.get(cid)
        if control is None:
            return
        binding, _inherited = self._binding_for(cid)
        desc = self._describe_binding(binding)
        btn.set_tooltip_text(f"{control.label} — {desc}")

    def refresh_all(self) -> None:
        """Atualiza todos os hotspots."""
        for cid in self._hotspot_buttons:
            self.refresh_hotspot(cid)
