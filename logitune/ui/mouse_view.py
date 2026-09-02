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

from gi.repository import Gdk, Gtk  # noqa: E402

from logitune.i18n import _  # noqa: E402
from logitune.ui.mouse_model import MODEL_REGISTRY  # noqa: E402

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent / "assets"
#: Diâmetro do marcador. Acompanha o ``min-width`` de ``.hotspot-button``
#: em ``hotspot.css``; serve de reserva quando o widget ainda não mediu.
_HOTSPOT_PX = 28
#: Caixa máxima do desenho na tela. O tamanho real sai da proporção da
#: imagem dentro desta caixa, calculado quando ela carrega — fixar a
#: proporção aqui quebraria em silêncio no dia em que o desenho mudasse de
#: formato, que foi o que aconteceu ao trocar a vista de cima pela lateral.
_DRAWING_MAX_W = 420
_DRAWING_MAX_H = 300
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


class _BoundedPicture(Gtk.Picture):
    """Um ``Gtk.Picture`` que não cresce além do tamanho pedido.

    O tamanho natural de um ``Gtk.Picture`` é o tamanho intrínseco da imagem,
    e ele reivindica esse espaço inteiro quando a janela permite. Com um
    desenho de 420×620 isso transforma a seção de botões num pôster do mouse
    e empurra o resto da página para fora da tela. Limitar o natural mantém o
    desenho vetorial — só não deixa ele mandar no layout.
    """

    __gtype_name__ = "LogituneBoundedPicture"

    def __init__(self) -> None:
        super().__init__()
        self._teto_w = _DRAWING_MAX_W
        self._teto_h = _DRAWING_MAX_H

    def fit_within(self, largura: int, altura: int) -> None:
        """Ajusta o teto à proporção da imagem, dentro da caixa máxima."""
        if largura <= 0 or altura <= 0:
            return
        escala = min(_DRAWING_MAX_W / largura, _DRAWING_MAX_H / altura)
        self._teto_w = max(1, round(largura * escala))
        self._teto_h = max(1, round(altura * escala))
        # O mínimo de um Gtk.Picture que pode encolher é zero, e sem pedir
        # este tamanho o desenho colapsa para nada em vez de ficar no tamanho
        # que acabamos de calcular.
        self.set_size_request(self._teto_w, self._teto_h)
        self.queue_resize()

    def do_measure(self, orientation, for_size):
        minimo, natural, _min_base, _nat_base = Gtk.Picture.do_measure(
            self, orientation, for_size
        )
        teto = (
            self._teto_w
            if orientation == Gtk.Orientation.HORIZONTAL
            else self._teto_h
        )
        # Uma imagem não tem linha de base; devolver uma faz o GTK reclamar.
        return min(minimo, teto), min(natural, teto), -1, -1


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
        extras: list | None = None,
    ) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
        )
        self.add_css_class("mouse-view-container")
        _ensure_css()

        self._controls = {c.control_id: c for c in controls}
        #: Pontos que não são botões, por chave: ``(hotspot, rótulo, descrever,
        #: configurar, limpar)``. A roda do polegar é o primeiro deles.
        self._extras = {e[0].key: e for e in (extras or ())}
        self._binding_for = binding_for
        self._describe_binding = describe_binding
        self._on_configure = on_configure
        self._on_clear = on_clear
        self._active_cid: int | None = None
        #: Falso quando não há desenho para este modelo; a janela então
        #: mostra só a lista de botões.
        self._available = True

        # Encontrar imagem e mapa de hotspots para o modelo
        entry = MODEL_REGISTRY.get(model_name)
        if entry is None:
            # Tentar correspondência parcial
            for name, data in MODEL_REGISTRY.items():
                if name.casefold() in model_name.casefold():
                    entry = data
                    break

        if entry is None:
            # Sem desenho para este modelo não há o que mostrar. Desenhar o
            # MX Master 4 para outro mouse seria pior que não desenhar nada:
            # os botões estariam nos lugares errados.
            logger.info(
                "sem desenho para o modelo %r; a lista de botões dá conta", model_name
            )
            self._available = False
            return

        image_name, self._hotspot_map = entry
        image_path = _ASSETS / image_name
        if not image_path.exists():
            logger.warning("desenho do mouse não encontrado: %s", image_path)
            self._available = False
            return

        # -- Montagem do widget --------------------------------------------

        # O desenho tem tamanho fixo. Deixá-lo crescer com a janela fazia uma
        # página de preferências virar um pôster do mouse: numa janela larga
        # ele passava de 600px de altura e empurrava todo o resto para fora da
        # tela.
        self._overlay = Gtk.Overlay(
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            hexpand=False,
            vexpand=False,
        )

        self._picture = _BoundedPicture()
        self._picture.set_filename(str(image_path))
        self._picture.set_can_shrink(True)
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        pintavel = self._picture.get_paintable()
        if pintavel is not None:
            self._picture.fit_within(
                pintavel.get_intrinsic_width(), pintavel.get_intrinsic_height()
            )
        self._overlay.set_child(self._picture)

        # Quem posiciona os marcadores é o próprio Gtk.Overlay, que repergunta
        # a posição de cada filho a cada alocação. Um Gtk.Fixed os colocaria
        # uma vez só, e eles ficariam para trás quando a janela mudasse de
        # tamanho — a imagem se reajusta, os marcadores não.
        self._overlay.connect("get-child-position", self._place_hotspot)

        self.append(self._overlay)

        #: Mapeamento CID → botão GTK no overlay.
        self._hotspot_buttons: dict[int, Gtk.Button] = {}
        #: Mapeamento CID → popover GTK.
        self._hotspot_popovers: dict[int, Gtk.Popover] = {}

        for cid, (x_pct, y_pct) in self._hotspot_map.items():
            if cid not in self._controls:
                continue
            self._create_hotspot(cid, x_pct, y_pct)

        for chave, (ponto, *_resto) in self._extras.items():
            self._create_hotspot(chave, ponto.x, ponto.y)

        # Trocar a imagem muda a proporção, e com ela toda a geometria.
        self._picture.connect(
            "notify::paintable", lambda *_: self._overlay.queue_allocate()
        )

    # -- Criação de hotspots -----------------------------------------------

    def _create_hotspot(self, cid: int, x_pct: float, y_pct: float) -> None:
        """Cria um marcador ⊕ para o botão de Control ID ``cid``."""
        btn = Gtk.Button()
        btn.set_child(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        btn.add_css_class("hotspot-button")
        btn.add_css_class("circular")
        btn.add_css_class("pulse")
        # Sem isto, um posicionamento recusado faria o marcador ocupar o
        # overlay inteiro em vez de ficar do seu tamanho.
        btn.set_halign(Gtk.Align.START)
        btn.set_valign(Gtk.Align.START)
        btn.connect("clicked", self._on_hotspot_clicked, cid)

        # Guardar a posição percentual como atributo do botão.
        btn._x_pct = x_pct  # noqa: SLF001
        btn._y_pct = y_pct  # noqa: SLF001

        self._overlay.add_overlay(btn)
        self._hotspot_buttons[cid] = btn
        # O tooltip nasce completo: antes só ganhava a ação depois do primeiro
        # refresh, e quem passasse o mouse antes disso via só o nome do botão.
        self._describe_tooltip(cid)

        # Popover
        popover = self._create_popover(cid)
        popover.set_parent(btn)
        self._hotspot_popovers[cid] = popover

    def _resumo(self, chave) -> tuple[str, str, bool, bool]:
        """Rótulo, descrição, se é herdado e se dá para limpar.

        Um marcador pode apontar para um botão programável ou para um ponto
        que não é botão, como a roda do polegar. Os dois têm nome e estado
        para mostrar; o que muda é onde esse estado mora.
        """
        extra = self._extras.get(chave)
        if extra is not None:
            _ponto, rotulo, descrever, _configurar, limpar = extra
            descricao = descrever()
            return rotulo, descricao, False, limpar is not None and bool(descricao)

        control = self._controls[chave]
        binding, herdado = self._binding_for(chave)
        descricao = self._describe_binding(binding)
        proprio = binding is not None and not binding.is_empty and not herdado
        return control.label, descricao, herdado, proprio

    def _create_popover(self, cid) -> Gtk.Popover:
        """Popover com nome do botão, ação configurada e botões de ação."""
        rotulo, description, inherited, own_binding = self._resumo(cid)

        popover = Gtk.Popover()
        popover.add_css_class("hotspot-popover")
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_autohide(True)
        popover.connect("closed", self._on_popover_closed, cid)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("hotspot-popover-box")

        title = Gtk.Label(label=rotulo, xalign=0)
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

    def _image_area(self) -> tuple[float, float, float, float] | None:
        """Onde a imagem realmente está dentro do widget.

        O ``Gtk.Picture`` com ``ContentFit.CONTAIN`` preserva a proporção e
        deixa barras de um lado ou do outro. Os percentuais dos marcadores
        são relativos à imagem, não ao widget, então essas barras precisam
        entrar na conta — senão os marcadores escorregam conforme a janela
        muda de formato.
        """
        largura = self._overlay.get_width()
        altura = self._overlay.get_height()
        if largura <= 1 or altura <= 1:
            return None

        paintable = self._picture.get_paintable()
        if paintable is None:
            return None
        intrinseca_w = paintable.get_intrinsic_width()
        intrinseca_h = paintable.get_intrinsic_height()
        if intrinseca_w <= 0 or intrinseca_h <= 0:
            return None

        proporcao = intrinseca_w / intrinseca_h
        if largura / altura > proporcao:
            desenhada_h = altura
            desenhada_w = desenhada_h * proporcao
        else:
            desenhada_w = largura
            desenhada_h = desenhada_w / proporcao

        return (
            (largura - desenhada_w) / 2,
            (altura - desenhada_h) / 2,
            desenhada_w,
            desenhada_h,
        )

    def _place_hotspot(
        self, _overlay: Gtk.Overlay, widget: Gtk.Widget, alocacao: Gdk.Rectangle
    ) -> bool:
        """Onde um marcador fica, recalculado a cada alocação do overlay.

        O retângulo chega como terceiro argumento e tem que ser **preenchido
        no lugar**; devolver um novo não tem efeito. Devolvendo a tupla, o
        overlay caía no posicionamento padrão e dava a cada marcador a área
        inteira — e como ``.hotspot-button`` é um círculo branco, o resultado
        era uma mancha branca cobrindo o desenho.
        """
        x_pct = getattr(widget, "_x_pct", None)
        if x_pct is None:
            return False

        area = self._image_area()
        if area is None:
            return False
        offset_x, offset_y, desenhada_w, desenhada_h = area

        _minimo, natural = widget.get_preferred_size()
        largura = natural.width or _HOTSPOT_PX
        altura = natural.height or _HOTSPOT_PX

        alocacao.x = int(offset_x + x_pct / 100.0 * desenhada_w - largura / 2)
        alocacao.y = int(offset_y + widget._y_pct / 100.0 * desenhada_h - altura / 2)  # noqa: SLF001
        alocacao.width = largura
        alocacao.height = altura
        return True

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
        extra = self._extras.get(cid)
        if extra is not None:
            extra[3]()
            return
        control = self._controls.get(cid)
        if control is not None:
            self._on_configure(control)

    def _on_clear_clicked(
        self, _btn: Gtk.Button, cid: int, popover: Gtk.Popover,
    ) -> None:
        """Limpa o vínculo do botão."""
        popover.popdown()
        extra = self._extras.get(cid)
        if extra is not None:
            if extra[4] is not None:
                extra[4]()
            return
        control = self._controls.get(cid)
        if control is not None:
            self._on_clear(control)

    def _describe_tooltip(self, cid) -> None:
        """Põe no marcador o nome do ponto e o que ele faz hoje."""
        btn = self._hotspot_buttons.get(cid)
        if btn is None:
            return
        if cid not in self._extras and cid not in self._controls:
            return
        rotulo, descricao, herdado, _proprio = self._resumo(cid)
        if herdado:
            descricao = _("{}  ·  inherited from Global").format(descricao)
        btn.set_tooltip_text(f"{rotulo} — {descricao}")

    # -- API pública -------------------------------------------------------

    def refresh_hotspot(self, cid: int) -> None:
        """Atualiza o popover de um hotspot sem recriar o widget inteiro.

        Chamado por ``_refresh_button_row_by_cid`` na janela principal.
        """
        self._describe_tooltip(cid)

    def refresh_all(self) -> None:
        """Atualiza todos os hotspots."""
        for cid in self._hotspot_buttons:
            self.refresh_hotspot(cid)

    @property
    def available(self) -> bool:
        """Há desenho para este modelo?"""
        return self._available
