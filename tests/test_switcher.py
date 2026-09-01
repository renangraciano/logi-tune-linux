# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do alternador de aplicativos na roda do polegar.

A propriedade que importa é que o Alt fique pressionado entre um detent e o
outro. Soltá-lo fecharia a janela do alternador e recomeçaria a lista a cada
giro, que é como este recurso deixa de funcionar sem dar erro.
"""

from __future__ import annotations

import pytest

from logitune.actions.binding import BindingError, WheelBinding
from logitune.actions.switcher import AppSwitcher


class TecladoFalso:
    """Anota a sequência sem criar dispositivo nenhum."""

    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def press(self, code: int) -> None:
        self.eventos.append(("press", code))

    def release(self, code: int) -> None:
        self.eventos.append(("release", code))

    def tap(self, shortcut) -> None:
        self.eventos.append(("tap", shortcut.text))


@pytest.fixture
def teclado() -> TecladoFalso:
    return TecladoFalso()


@pytest.fixture
def switcher(teclado) -> AppSwitcher:
    pytest.importorskip("evdev")
    return AppSwitcher(keyboard=teclado, idle_ms=800)


class TestAlternador:
    def test_segura_o_alt_entre_os_detents(self, switcher, teclado):
        switcher.step(+1, now=0.0)
        switcher.step(+1, now=0.2)
        switcher.step(+1, now=0.4)
        # Um único press, nenhum release enquanto a roda gira.
        assert [e for e in teclado.eventos if e[0] == "press"] == [("press", 56)]
        assert [e for e in teclado.eventos if e[0] == "release"] == []
        assert [e[1] for e in teclado.eventos if e[0] == "tap"] == ["tab"] * 3

    def test_confirma_quando_a_roda_para(self, switcher, teclado):
        switcher.step(+1, now=0.0)
        switcher.tick(now=0.5)
        assert switcher.active, "confirmou cedo demais"
        switcher.tick(now=1.0)
        assert not switcher.active
        assert teclado.eventos[-1] == ("release", 56)

    def test_o_relogio_reinicia_a_cada_giro(self, switcher):
        switcher.step(+1, now=0.0)
        switcher.step(+1, now=0.7)
        switcher.tick(now=1.0)
        # Passou 1s do primeiro giro, mas só 0,3s do último.
        assert switcher.active

    def test_sentido_inverso_usa_shift(self, switcher, teclado):
        switcher.step(-1, now=0.0)
        assert ("tap", "shift+tab") in teclado.eventos

    def test_giro_zero_nao_abre_nada(self, switcher, teclado):
        switcher.step(0, now=0.0)
        assert teclado.eventos == []
        assert not switcher.active

    def test_cancelar_solta_a_tecla(self, switcher, teclado):
        """Uma tecla segurada sobrevive ao processo que a segurou."""
        switcher.step(+1, now=0.0)
        switcher.cancel()
        assert ("release", 56) in teclado.eventos
        assert not switcher.active

    def test_cancelar_sem_estar_ativo_nao_faz_nada(self, switcher, teclado):
        switcher.cancel()
        assert teclado.eventos == []

    def test_prazo_acorda_o_daemon(self, switcher):
        assert switcher.next_deadline(now=0.0) is None
        switcher.step(+1, now=0.0)
        assert switcher.next_deadline(now=0.0) == pytest.approx(0.8)
        assert switcher.next_deadline(now=0.6) == pytest.approx(0.2)

    def test_o_prazo_some_depois_de_confirmar(self, switcher):
        """Um prazo preso em zero faria o laço girar sem parar."""
        switcher.step(+1, now=0.0)
        switcher.tick(now=1.0)
        assert switcher.next_deadline(now=1.0) is None


class TestConfiguracaoDaRoda:
    def test_comportamento_continuo(self):
        assert WheelBinding.parse("window.switch_apps").stateful == "window.switch_apps"

    def test_uma_acao_por_sentido(self):
        roda = WheelBinding.parse({"up": "media.volume_up", "down": "media.volume_down"})
        assert roda.for_direction(+1).action == "media.volume_up"
        assert roda.for_direction(-1).action == "media.volume_down"

    def test_vazia_por_padrao(self):
        assert WheelBinding.parse(None).is_empty

    def test_acao_comum_como_texto_e_recusada(self):
        """Uma ação sem estado não sabe de que lado a roda girou."""
        with pytest.raises(BindingError, match="up"):
            WheelBinding.parse("media.volume_up")

    def test_chave_desconhecida_e_recusada(self):
        with pytest.raises(BindingError, match="left"):
            WheelBinding.parse({"left": "media.volume_up"})

    def test_roundtrip_json(self):
        for bruto in ("window.switch_apps", {"up": "media.volume_up"}):
            assert WheelBinding.parse(bruto).to_json() == bruto


class TestContagemDeDetents:
    """A roda reporta na resolução desviada, não em detents.

    No MX Master 4 são 120 por volta contra 20 nativos: seis unidades por
    clique. Um passo por unidade faria o alternador voar pela lista — foi
    medido no hardware, não deduzido.
    """

    def test_seis_unidades_fecham_um_detent(self):
        from logitune.actions.switcher import DetentCounter

        contador = DetentCounter(6)
        assert [contador.feed(1) for _ in range(6)] == [0, 0, 0, 0, 0, 1]

    def test_o_resto_sobrevive_entre_eventos(self):
        """Um giro lento chega em deltas pequenos e ainda precisa somar."""
        from logitune.actions.switcher import DetentCounter

        contador = DetentCounter(6)
        assert contador.feed(4) == 0
        assert contador.feed(4) == 1  # 8 unidades = 1 detent, sobram 2
        assert contador.feed(4) == 1  # 6 acumuladas fecham o próximo

    def test_giro_rapido_fecha_varios(self):
        from logitune.actions.switcher import DetentCounter

        assert DetentCounter(6).feed(-24) == -4

    def test_sentido_negativo_nao_arredonda_para_o_lado_errado(self):
        # int() trunca em direção ao zero, que é o que se quer nos dois lados.
        from logitune.actions.switcher import DetentCounter

        contador = DetentCounter(6)
        assert contador.feed(-4) == 0
        assert contador.feed(-4) == -1

    def test_reset_esquece_o_resto(self):
        from logitune.actions.switcher import DetentCounter

        contador = DetentCounter(6)
        contador.feed(5)
        contador.reset()
        assert contador.feed(1) == 0

    def test_proporcao_de_um_nao_acumula(self):
        from logitune.actions.switcher import DetentCounter

        assert [DetentCounter(1).feed(d) for d in (1, -1, 3)] == [1, -1, 3]


class TestTempoConfiguravel:
    """O tempo de confirmação estava fixo no código, o que é o mesmo que não
    existir para quem quer ajustá-lo."""

    def test_padrao(self):
        from logitune.config import Config

        assert Config().switcher_idle_ms == 800

    def test_valor_configurado(self):
        from logitune.config import Config

        assert Config(wheel={"switcher_idle_ms": 1200}).switcher_idle_ms == 1200

    @pytest.mark.parametrize("bruto", [50, 9000, "abc", None, -1])
    def test_valor_fora_da_faixa_ou_invalido_cai_no_padrao(self, bruto):
        from logitune.config import Config

        assert Config(wheel={"switcher_idle_ms": bruto}).switcher_idle_ms == 800

    def test_roundtrip_json(self, tmp_path):
        from logitune.config import Config, load

        destino = tmp_path / "config.json"
        Config(wheel={"switcher_idle_ms": 1500}).save(destino)
        assert load(destino).switcher_idle_ms == 1500
