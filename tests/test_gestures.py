# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do reconhecedor de gestos.

O caso central é a regressão de calibragem no fim do arquivo: as 25
pressionadas medidas num MX Master 4 real, com a classificação que cada uma
precisa receber. Se alguém mexer nos limiares e quebrar a separação entre um
clique e um arrasto, é ali que aparece.
"""

from __future__ import annotations

import pytest

from logitune.actions.gestures import (
    Feedback,
    Gesture,
    GestureRecognizer,
    GestureThresholds,
    Recognized,
)

CID = 0x01A0


def _reconhecedor(**kwargs) -> GestureRecognizer:
    # Por padrão todos os gestos estão configurados, que é o caso mais estrito:
    # com duplo toque ligado, o toque simples precisa esperar a janela.
    kwargs.setdefault("bound", lambda cid: set(Gesture))
    return GestureRecognizer(**kwargs)


def _executar(
    recognizer: GestureRecognizer,
    *,
    duracao_ms: float,
    dx: int = 0,
    dy: int = 0,
    amostras: int = 0,
    inicio: float = 0.0,
) -> list[Recognized]:
    """Reproduz uma pressionada, distribuindo o deslocamento nas amostras."""
    recognizer.press(CID, now=inicio)
    saida: list[Recognized] = []
    for i in range(amostras):
        instante = inicio + (duracao_ms / 1000) * (i + 1) / (amostras + 1)
        saida.extend(recognizer.tick(now=instante))
        saida.extend(
            recognizer.movement(dx // amostras, dy // amostras, now=instante)
        )
    fim = inicio + duracao_ms / 1000
    saida.extend(recognizer.tick(now=fim))
    saida.extend(recognizer.release(CID, now=fim))
    return saida


def _gestos(saida: list[Recognized]) -> list[Gesture]:
    return [r.gesture for r in saida]


class TestToque:
    def test_clique_curto_e_toque(self):
        r = _reconhecedor(bound=lambda cid: {Gesture.TAP})
        assert _gestos(_executar(r, duracao_ms=120)) == [Gesture.TAP]

    def test_sem_duplo_toque_configurado_o_toque_sai_na_hora(self):
        """Quem não usa duplo toque não deve pagar a latência da janela."""
        r = _reconhecedor(bound=lambda cid: {Gesture.TAP})
        r.press(CID, now=0.0)
        assert _gestos(r.release(CID, now=0.1)) == [Gesture.TAP]

    def test_com_duplo_toque_configurado_o_toque_espera(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        assert r.release(CID, now=0.1) == []
        assert _gestos(r.tick(now=0.2)) == []
        assert _gestos(r.tick(now=0.6)) == [Gesture.TAP]

    def test_dois_toques_na_janela_viram_duplo(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.release(CID, now=0.1)
        r.press(CID, now=0.2)
        assert _gestos(r.release(CID, now=0.3)) == [Gesture.DOUBLE_TAP]

    def test_dois_toques_lentos_sao_dois_toques(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.release(CID, now=0.1)
        primeiro = r.tick(now=0.6)
        r.press(CID, now=0.7)
        r.release(CID, now=0.8)
        segundo = r.tick(now=1.4)
        assert _gestos(primeiro) == [Gesture.TAP]
        assert _gestos(segundo) == [Gesture.TAP]


class TestSegurar:
    def test_dispara_enquanto_o_botao_esta_preso(self):
        """O hold precisa sair na hora em que cruza, não ao soltar.

        Segurar e não sentir nada até largar é indistinguível de não ter
        funcionado.
        """
        r = _reconhecedor()
        r.press(CID, now=0.0)
        assert r.tick(now=0.3) == []
        assert _gestos(r.tick(now=0.6)) == [Gesture.HOLD]

    def test_nao_repete_enquanto_segura(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.tick(now=0.6)
        assert r.tick(now=1.2) == []
        assert r.release(CID, now=2.0) == []

    def test_arrasto_tem_precedencia_sobre_segurar(self):
        """Todo arrasto medido durou mais que o limiar de hold.

        Sem precedência do deslocamento, arrastar devagar viraria segurar.
        """
        r = _reconhecedor()
        r.press(CID, now=0.0)
        for i in range(10):
            r.movement(100, 0, now=0.01 * (i + 1))
        assert r.tick(now=0.9) == []
        assert _gestos(r.release(CID, now=1.0)) == [Gesture.DRAG_RIGHT]


class TestArrasto:
    @pytest.mark.parametrize(
        "dx, dy, esperado",
        [
            (800, 0, Gesture.DRAG_RIGHT),
            (-800, 0, Gesture.DRAG_LEFT),
            (0, 800, Gesture.DRAG_DOWN),
            (0, -800, Gesture.DRAG_UP),
            # Eixo dominante decide: o desvio lateral não muda a direção.
            (-278, -918, Gesture.DRAG_UP),
            (723, -1, Gesture.DRAG_RIGHT),
        ],
    )
    def test_direcao_pelo_eixo_dominante(self, dx, dy, esperado):
        r = _reconhecedor()
        assert _gestos(_executar(r, duracao_ms=600, dx=dx, dy=dy, amostras=30)) == [esperado]

    def test_distancia_sozinha_nao_basta(self):
        """Um esbarrão medido deu 98 unidades numa amostra só.

        Exigir continuidade é o que separa a mão empurrando o mouse ao clicar
        de um arrasto de verdade.
        """
        r = _reconhecedor(bound=lambda cid: {Gesture.TAP})
        saida = _executar(r, duracao_ms=128, dx=-810, dy=-560, amostras=1)
        assert _gestos(saida) == [Gesture.TAP]

    def test_amostras_sozinhas_nao_bastam(self):
        r = _reconhecedor(bound=lambda cid: {Gesture.TAP})
        saida = _executar(r, duracao_ms=150, dx=20, dy=10, amostras=30)
        assert _gestos(saida) == [Gesture.TAP]

    def test_retorno_haptico_avisa_antes_de_soltar(self):
        sentidos: list[tuple[Feedback, Gesture]] = []
        r = _reconhecedor(feedback=lambda kind, gesture: sentidos.append((kind, gesture)))
        _executar(r, duracao_ms=600, dx=800, dy=0, amostras=30)
        assert (Feedback.CROSSED, Gesture.DRAG_RIGHT) in sentidos
        assert (Feedback.CONFIRMED, Gesture.DRAG_RIGHT) in sentidos

    def test_haptico_que_estoura_nao_derruba_o_gesto(self):
        def explode(kind, gesture):
            raise RuntimeError("motor mudo")

        r = _reconhecedor(feedback=explode)
        assert _gestos(_executar(r, duracao_ms=600, dx=800, dy=0, amostras=30)) == [
            Gesture.DRAG_RIGHT
        ]


class TestLaco:
    def test_prazo_acorda_o_daemon_para_o_hold(self):
        """Sem prazo, o hold só sairia quando outro evento acordasse o laço."""
        r = _reconhecedor()
        assert r.next_deadline(now=0.0) is None
        r.press(CID, now=0.0)
        assert r.next_deadline(now=0.0) == pytest.approx(0.5)
        assert r.next_deadline(now=0.4) == pytest.approx(0.1)

    def test_prazo_para_a_janela_do_duplo_toque(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.release(CID, now=0.1)
        assert r.next_deadline(now=0.1) == pytest.approx(0.4)

    def test_soltar_sem_pressionar_e_ignorado(self):
        assert _reconhecedor().release(CID, now=0.0) == []

    def test_reset_limpa_o_que_estava_em_curso(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.reset()
        assert r.next_deadline(now=0.0) is None
        assert r.tick(now=5.0) == []

    def test_limiares_invalidos_sao_recusados(self):
        with pytest.raises(ValueError):
            GestureThresholds(drag_units=0)


class TestCalibragemReal:
    """As 25 pressionadas medidas num MX Master 4 (RBM 27.03.B0019, Bolt).

    Cada linha é ``(duração ms, dx, dy, amostras, gesto esperado)``, copiada da
    saída de ``watch --raw-xy``. É a prova de que os limiares separam a mão
    desta pessoa, e não um modelo idealizado dela.
    """

    MEDIDAS = [
        # Cliques e segurares, sem intenção de mover.
        (630, 0, 0, 0, Gesture.HOLD),      # clique lento: vira hold (ver nota)
        (149, 0, 0, 0, Gesture.TAP),
        (173, 0, 0, 0, Gesture.TAP),
        (150, 0, 0, 0, Gesture.TAP),
        (105, 0, 0, 0, Gesture.TAP),
        (75, 0, 0, 0, Gesture.TAP),
        (1703, 0, 0, 0, Gesture.HOLD),
        (157, 0, 0, 0, Gesture.TAP),
        (97, 0, 0, 0, Gesture.TAP),
        (105, 0, 0, 0, Gesture.TAP),
        (105, 0, 0, 0, Gesture.TAP),
        (82, 0, 0, 0, Gesture.TAP),
        # Movimento acidental: a mão empurra o mouse ao apertar.
        (128, -81, -56, 1, Gesture.TAP),   # 98 unidades, e ainda é um clique
        (90, -8, -8, 1, Gesture.TAP),
        (1657, -8, -8, 1, Gesture.HOLD),
        (150, -17, -10, 1, Gesture.TAP),
        (150, -7, -3, 1, Gesture.TAP),
        # Arrastos de verdade.
        (645, 723, -1, 34, Gesture.DRAG_RIGHT),
        (600, -809, 86, 48, Gesture.DRAG_LEFT),
        (675, -278, -918, 54, Gesture.DRAG_UP),
        (562, 112, 1021, 61, Gesture.DRAG_DOWN),
        (2198, 1466, -30, 29, Gesture.DRAG_RIGHT),
        (1215, -1540, 181, 72, Gesture.DRAG_LEFT),
        (1035, -146, -992, 48, Gesture.DRAG_UP),
        (847, 99, 1039, 47, Gesture.DRAG_DOWN),
    ]

    @pytest.mark.parametrize("duracao, dx, dy, amostras, esperado", MEDIDAS)
    def test_classificacao(self, duracao, dx, dy, amostras, esperado):
        # Sem duplo toque configurado, para o toque sair no release e o caso
        # ficar isolado de uma pressionada por vez.
        r = _reconhecedor(bound=lambda cid: {Gesture.TAP, Gesture.HOLD} | {
            g for g in Gesture if g.is_drag
        })
        saida = _executar(r, duracao_ms=duracao, dx=dx, dy=dy, amostras=amostras)
        assert _gestos(saida) == [esperado]

    def test_nenhum_acidente_virou_arrasto(self):
        """A garantia que mais importa: nada sem intenção vira direção."""
        acidentes = [m for m in self.MEDIDAS if m[3] <= 1]
        assert all(not m[4].is_drag for m in acidentes)

    def test_todo_arrasto_foi_reconhecido(self):
        arrastos = [m for m in self.MEDIDAS if m[3] >= 29]
        assert all(m[4].is_drag for m in arrastos)


class TestSemLacoOcupado:
    """O prazo encurta o sono do daemon; ele não pode encurtá-lo para sempre.

    Um prazo que fica preso em zero faria o select voltar na hora, sem parar,
    e o daemon queimaria CPU enquanto um botão estivesse pressionado.
    """

    def test_o_prazo_do_hold_some_depois_de_disparar(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        assert r.next_deadline(now=0.5) == pytest.approx(0.0)
        r.tick(now=0.5)
        assert r.next_deadline(now=0.5) is None

    def test_o_prazo_do_duplo_toque_some_depois_de_disparar(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.release(CID, now=0.1)
        assert r.next_deadline(now=0.5) == pytest.approx(0.0)
        r.tick(now=0.5)
        assert r.next_deadline(now=0.5) is None

    def test_segurar_por_muito_tempo_nao_reagenda(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        r.tick(now=0.6)
        # Ainda pressionado dez segundos depois, e sem nada a esperar.
        assert r.next_deadline(now=10.0) is None
        assert r.tick(now=10.0) == []

    def test_arrasto_em_curso_nao_reagenda(self):
        r = _reconhecedor()
        r.press(CID, now=0.0)
        for i in range(5):
            r.movement(100, 0, now=0.01 * (i + 1))
        assert r.next_deadline(now=5.0) is None


class TestLimiaresConfiguraveis:
    """Os limiares descrevem a mão de quem usa, então precisam ser ajustáveis
    — e uma configuração errada não pode deixar o daemon sem gestos."""

    def test_valores_configurados_valem(self):
        from logitune.config import Config

        limiares = Config(gestures={"drag_units": 300, "hold_ms": 700}).gesture_thresholds()
        assert limiares.drag_units == 300
        assert limiares.hold_ms == 700
        # O que não foi dito continua no padrão medido.
        assert limiares.double_tap_ms == 400

    @pytest.mark.parametrize(
        "gestures",
        [
            {"nao_existe": 1},
            {"drag_units": "abc"},
            {"drag_units": -5},
            {"hold_ms": 0},
        ],
    )
    def test_configuracao_ruim_cai_no_padrao(self, gestures):
        from logitune.config import Config

        limiares = Config(gestures=gestures).gesture_thresholds()
        assert limiares.drag_units == 200
        assert limiares.hold_ms == 500

    def test_roundtrip_json(self, tmp_path):
        from logitune.config import Config, load

        destino = tmp_path / "config.json"
        Config(gestures={"drag_units": 250}).save(destino)
        assert load(destino).gesture_thresholds().drag_units == 250


class TestInterruptorDeGestos:
    """O interruptor precisa desligar de verdade, não só parecer desligado."""

    def test_ligados_por_padrao(self):
        from logitune.config import Config

        # Quem escreveu um mapa de gestos já disse o que queria; exigir uma
        # segunda confirmação faria o recurso parecer quebrado.
        assert Config().gestures_enabled is True

    def test_desligar_pela_configuracao(self):
        from logitune.config import Config

        assert Config(gestures={"enabled": False}).gestures_enabled is False

    def test_enabled_nao_e_lido_como_limiar(self, caplog):
        from logitune.config import Config

        limiares = Config(gestures={"enabled": True, "drag_units": 300}).gesture_thresholds()
        assert limiares.drag_units == 300
        assert "enabled" not in caplog.text

    def test_roundtrip_json(self, tmp_path):
        from logitune.config import Config, load

        destino = tmp_path / "config.json"
        Config(gestures={"enabled": False}).save(destino)
        assert load(destino).gestures_enabled is False


class TestDaemonComGestosDesligados:
    def _daemon(self, config):
        from logitune.daemon.service import Daemon

        class DispositivoFalso:
            name = "Mouse falso"
            hidpp = None
            controls = None

        return Daemon(config, DispositivoFalso())

    def test_botao_de_gestos_fica_de_fabrica(self):
        """Desligado quer dizer desligado: nem o toque dispara.

        Deixar o toque valendo faria o botão continuar fazendo algo que o
        usuário pediu para desligar.
        """
        from logitune.config import Config, Settings

        config = Config(gestures={"enabled": False})
        daemon = self._daemon(config)
        settings = Settings(bindings={"0x1A0": {"tap": "system.overview"}})
        cliques, gestos = daemon._resolve_bindings(settings)
        assert cliques == {}
        assert gestos == {}

    def test_botao_de_clique_nao_e_afetado(self):
        """Desligar gestos não pode desligar um botão que nunca teve gesto."""
        from logitune.config import Config, Settings

        daemon = self._daemon(Config(gestures={"enabled": False}))
        settings = Settings(bindings={"0x53": "system.overview"})
        cliques, _ = daemon._resolve_bindings(settings)
        assert list(cliques) == [0x53]

    def test_sighup_marca_a_recarga(self):
        from logitune.config import Config

        daemon = self._daemon(Config())
        assert daemon._reload_requested is False
        daemon.request_reload()
        assert daemon._reload_requested is True
