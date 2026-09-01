# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do sistema de ações: catálogo, vínculos e síntese de teclas.

Nada aqui toca no hardware, no D-Bus ou no ``/dev/uinput``: as sondagens de
disponibilidade e o teclado virtual são substituídos, de modo que a suíte
continua rodando em qualquer máquina.
"""

from __future__ import annotations

import pytest

from logitune.actions import (
    Binding,
    BindingError,
    ButtonBinding,
    Category,
    Gesture,
    Registry,
    ResolvedAction,
    UnknownAction,
    command_binding,
    default_registry,
    merge_raw,
    resolve,
)
from logitune.actions.catalog import RECOMMENDED
from logitune.actions.spec import (
    ActionContext,
    ActionError,
    ActionSpec,
    Availability,
    Parameter,
)
from logitune.config import Settings

from logitune.actions.backends import keys

# O evdev só é necessário para sintetizar teclas. Catálogo, vínculos, merge e
# resolução não dependem dele — e não podem ser pulados junto, senão a suíte
# some inteira em qualquer máquina sem o pacote, como aconteceu no CI.
try:
    import evdev
except ImportError:  # pragma: no cover - depende do ambiente
    evdev = None

requer_evdev = pytest.mark.skipif(evdev is None, reason="precisa do python3-evdev")


@requer_evdev
class TestAtalhos:
    def test_le_modificadores_e_tecla(self):
        atalho = keys.parse_shortcut("ctrl+shift+t")
        assert atalho.key == evdev.ecodes.KEY_T
        assert atalho.modifiers == (evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_LEFTSHIFT)

    def test_modificador_sozinho_e_atalho_valido(self):
        # "super" abre a visão de atividades do GNOME: é o caso mais usado de
        # todos, e não pode ser recusado por não ter uma tecla "principal".
        atalho = keys.parse_shortcut("super")
        assert atalho.key == evdev.ecodes.KEY_LEFTMETA
        assert atalho.modifiers == ()

    def test_apelidos(self):
        assert keys.parse_shortcut("print").key == evdev.ecodes.KEY_SYSRQ
        assert keys.parse_shortcut("esc").key == evdev.ecodes.KEY_ESC
        assert keys.parse_shortcut("pgdn").key == evdev.ecodes.KEY_PAGEDOWN

    def test_mais_literal(self):
        # O separador também é uma tecla: "ctrl++" é ctrl mais '+'.
        atalho = keys.parse_shortcut("ctrl++")
        assert atalho.key == evdev.ecodes.KEY_EQUAL
        assert atalho.modifiers == (evdev.ecodes.KEY_LEFTCTRL,)

    def test_ordem_nao_importa(self):
        assert keys.parse_shortcut("t+ctrl").key == keys.parse_shortcut("ctrl+t").key

    @pytest.mark.parametrize("texto", ["", "   ", "ctrl+nao_existe", "a+b"])
    def test_atalhos_invalidos(self, texto):
        with pytest.raises(ActionError):
            keys.parse_shortcut(texto)


class TecladoFalso:
    """Anota o que teria sido emitido, sem criar dispositivo nenhum."""

    def __init__(self):
        self.emitidos: list[str] = []

    def tap(self, shortcut) -> None:
        self.emitidos.append(shortcut.text)


@requer_evdev
class TestSinteseDeTeclas:
    def test_emite_o_atalho_pedido(self, monkeypatch):
        falso = TecladoFalso()
        monkeypatch.setattr(keys, "keyboard", lambda: falso)
        keys.tap("ctrl+c")
        assert falso.emitidos == ["ctrl+c"]

    def test_ordem_de_pressionar_e_soltar(self, monkeypatch):
        """Os modificadores sobem na ordem inversa da que desceram.

        Soltar o ctrl antes da tecla faria o aplicativo ver uma tecla solta
        sem modificador, que é como um atalho vira um caractere digitado.
        """
        escritos: list[tuple[int, int]] = []

        class Dispositivo:
            def write(self, tipo, code, value):
                escritos.append((code, value))

            def syn(self):
                pass

        teclado = keys.Keyboard()
        monkeypatch.setattr(teclado, "_open", lambda: Dispositivo())
        teclado.tap(keys.parse_shortcut("ctrl+shift+t"))

        ctrl, shift, t = (
            evdev.ecodes.KEY_LEFTCTRL,
            evdev.ecodes.KEY_LEFTSHIFT,
            evdev.ecodes.KEY_T,
        )
        assert escritos == [
            (ctrl, 1), (shift, 1), (t, 1),
            (t, 0), (shift, 0), (ctrl, 0),
        ]


class TestCatalogo:
    def test_identificadores_sao_unicos(self):
        registro = default_registry()
        assert len({spec.id for spec in registro}) == len(registro)

    @requer_evdev
    def test_todo_atalho_do_catalogo_e_valido(self):
        """Um atalho com erro de digitação só apareceria no dia do clique."""
        for spec in default_registry():
            if spec.shortcut:
                keys.parse_shortcut(spec.shortcut)

    def test_as_recomendadas_existem(self):
        registro = default_registry()
        assert [i for i in RECOMMENDED if i not in registro] == []

    def test_toda_acao_tem_rotulo_e_categoria(self):
        for spec in default_registry():
            assert spec.label.strip()
            assert isinstance(spec.category, Category)

    def test_agrupamento_respeita_a_ordem_das_categorias(self):
        categorias = list(default_registry().by_category())
        assert categorias == sorted(categorias, key=lambda c: c.order)

    def test_busca_encontra_pela_categoria(self):
        # Nenhuma ação de navegador tem o nome da categoria no id nem no
        # rótulo. Usamos o rótulo traduzido para o teste não depender do
        # idioma da sessão.
        encontradas = default_registry().search(Category.NAVEGADOR.label)
        assert {s.id for s in encontradas} >= {"browser.back", "browser.forward"}

    def test_registro_recusa_duplicata(self):
        registro = Registry()
        spec = ActionSpec("x", "X", Category.SISTEMA, run=lambda c: None)
        registro.register(spec)
        with pytest.raises(ValueError):
            registro.register(spec)


class TestVinculos:
    def test_texto_simples_e_o_id_da_acao(self):
        vinculo = ButtonBinding.parse("browser.back")
        assert vinculo.press == Binding("browser.back")
        assert not vinculo.gestures

    def test_objeto_carrega_parametros(self):
        vinculo = ButtonBinding.parse({"action": "key.shortcut", "keys": "ctrl+shift+t"})
        assert vinculo.press.action == "key.shortcut"
        assert vinculo.press.params == {"keys": "ctrl+shift+t"}

    def test_mapa_de_gestos(self):
        vinculo = ButtonBinding.parse({"tap": "system.overview", "drag_left": "workspace.left"})
        assert vinculo.press is None
        assert vinculo.gestures[Gesture.TAP] == Binding("system.overview")
        assert vinculo.gestures[Gesture.DRAG_LEFT] == Binding("workspace.left")

    def test_gestos_ficam_separados_do_clique(self):
        vinculo = ButtonBinding.parse({"tap": "media.next", "hold": "media.stop"})
        assert vinculo.press is None
        assert set(vinculo.gestures) == {Gesture.TAP, Gesture.HOLD}

    def test_gesto_desconhecido_e_recusado(self):
        with pytest.raises(BindingError, match="drag_diagonal"):
            ButtonBinding.parse({"drag_diagonal": "media.next"})

    def test_objeto_sem_acao_nem_gestos_e_recusado(self):
        with pytest.raises(BindingError):
            ButtonBinding.parse(42)

    def test_roundtrip_para_json(self):
        for bruto in ("browser.back", {"action": "shell.run", "command": "ls"},
                      {"tap": "media.next"}):
            assert ButtonBinding.parse(bruto).to_json() == bruto

    def test_comando_antigo_vira_shell_run(self):
        vinculo = command_binding("gnome-calculator")
        assert vinculo.press == Binding("shell.run", {"command": "gnome-calculator"})


class TestMerge:
    def test_gestos_sao_combinados_um_a_um(self):
        """Um perfil que troca só o toque não pode apagar os outros gestos."""
        base = {"0x01A0": {"tap": "a", "hold": "b", "drag_left": "c"}}
        perfil = {"0x01A0": {"tap": "z"}}
        assert merge_raw(base, perfil) == {
            "0x01A0": {"tap": "z", "hold": "b", "drag_left": "c"}
        }

    def test_acao_simples_sobrepoe_o_mapa_inteiro(self):
        base = {"0x01A0": {"tap": "a", "hold": "b"}}
        assert merge_raw(base, {"0x01A0": "media.next"}) == {"0x01A0": "media.next"}

    def test_botao_novo_e_acrescentado(self):
        assert merge_raw({"0x1": "a"}, {"0x2": "b"}) == {"0x1": "a", "0x2": "b"}

    def test_settings_combina_por_gesto(self):
        base = Settings(bindings={"0x01A0": {"tap": "a", "hold": "b"}})
        merged = Settings(bindings={"0x01A0": {"tap": "z"}}).merged_with(base)
        assert merged.bindings == {"0x01A0": {"tap": "z", "hold": "b"}}


class TestSettingsBindings:
    def test_le_as_duas_formas(self):
        settings = Settings(
            actions={"0x00C4": "gnome-calculator"},
            bindings={"0x0053": "browser.back"},
        )
        pares = dict(settings.binding_pairs())
        assert pares[0x0053].press == Binding("browser.back")
        assert pares[0x00C4].press == Binding("shell.run", {"command": "gnome-calculator"})

    def test_bindings_tem_a_palavra_final(self):
        settings = Settings(
            actions={"0x0053": "xdotool key alt+Left"},
            bindings={"0x0053": "browser.back"},
        )
        assert dict(settings.binding_pairs())[0x0053].press == Binding("browser.back")

    def test_controle_invalido_e_descartado(self):
        assert Settings(bindings={"não é hex": "browser.back"}).binding_pairs() == []

    def test_vinculo_invalido_nao_derruba_os_outros(self):
        settings = Settings(bindings={"0x1": {"gesto_errado": "a"}, "0x2": "browser.back"})
        assert [cid for cid, _ in settings.binding_pairs()] == [0x2]

    def test_roundtrip_json_preserva_os_vinculos(self, tmp_path):
        from logitune.config import Config, load

        original = Config(default=Settings(bindings={"0x01A0": {"tap": "system.overview"}}))
        destino = tmp_path / "config.json"
        original.save(destino)
        assert load(destino).default.bindings == {"0x01A0": {"tap": "system.overview"}}


class TestResolucao:
    def test_resolve_uma_acao_do_catalogo(self):
        acao = resolve(Binding("browser.back"))
        assert acao.spec.id == "browser.back"

    def test_acao_inexistente(self):
        with pytest.raises(UnknownAction):
            resolve(Binding("nao.existe"))

    def test_parametro_obrigatorio_em_branco_conta_como_indisponivel(self):
        """A ação existe, mas não tem o que executar — e o daemon precisa
        saber disso antes de desviar o botão."""
        disponivel = resolve(Binding("app.open_url")).available()
        assert not disponivel.ok
        assert "url" in disponivel.reason

    def test_parametro_preenchido_dispensa_o_aviso(self):
        # Com uma ação do catálogo isto passaria a testar o backend dela — o
        # app.open_url só está disponível onde há PyGObject. O que importa
        # aqui é só o preenchimento do parâmetro.
        spec = ActionSpec(
            "t.url", "Com URL", Category.SISTEMA,
            run=lambda context: None,
            parameters=(Parameter("url", "Endereço"),),
        )
        assert ResolvedAction(spec, {"url": "https://exemplo.org"}).available().ok

    def test_valor_padrao_chega_na_execucao(self):
        vistos = {}
        spec = ActionSpec(
            "t.padrao", "Padrão", Category.SISTEMA,
            run=lambda context: vistos.update(context.params),
            parameters=(Parameter("n", "N", required=False, default=7),),
        )
        ResolvedAction(spec).run()
        assert vistos == {"n": 7}

    def test_parametro_da_config_vence_o_padrao(self):
        vistos = {}
        spec = ActionSpec(
            "t.sobrepoe", "Sobrepõe", Category.SISTEMA,
            run=lambda context: vistos.update(context.params),
            parameters=(Parameter("n", "N", required=False, default=7),),
        )
        ResolvedAction(spec, {"n": 3}).run()
        assert vistos == {"n": 3}

    def test_sondagem_que_estoura_vira_indisponivel(self):
        """Um backend quebrado não pode derrubar a listagem da interface."""
        def explode():
            raise RuntimeError("boom")

        spec = ActionSpec("t.ruim", "Ruim", Category.SISTEMA, run=lambda c: None, probe=explode)
        assert not spec.available().ok


class TestDisponibilidade:
    def test_falta_passageira_ainda_vale_o_desvio(self):
        # Nenhum tocador aberto agora não é motivo para devolver o botão à
        # função de fábrica: abrir o Spotify resolve.
        assert Availability(False, "sem tocador", transient=True).usable
        assert not Availability(False, "sem permissão").usable
        assert Availability(True).usable


class TestContexto:
    def test_parametro_obrigatorio_ausente(self):
        with pytest.raises(ActionError, match="url"):
            ActionContext().require("url")

    def test_sem_dispositivo(self):
        with pytest.raises(ActionError, match="mouse"):
            ActionContext().require_device()


class DispositivoFalso:
    """O mínimo que o daemon toca ao resolver vínculos."""

    name = "Mouse falso"
    hidpp = None
    controls = None


def _daemon(settings_bindings, registro):
    from logitune.config import Config
    from logitune.daemon.service import Daemon

    return Daemon(Config(), DispositivoFalso()), Settings(bindings=settings_bindings)


class TestDaemonResolveVinculos:
    """O daemon só desvia um botão cuja ação ele consegue executar.

    Um botão desviado com uma ação quebrada não faz nada e não avisa, o que é
    pior do que um botão que continua com a função de fábrica.
    """

    @pytest.fixture
    def registro(self, monkeypatch):
        from logitune.actions import registry as registry_module

        registro = Registry()
        registro.register(ActionSpec("t.ok", "Boa", Category.SISTEMA, run=lambda c: None))
        registro.register(
            ActionSpec(
                "t.sem_permissao", "Sem permissão", Category.SISTEMA,
                run=lambda c: None,
                probe=lambda: Availability(False, "falta a regra udev"),
            )
        )
        registro.register(
            ActionSpec(
                "t.passageira", "Passageira", Category.MIDIA,
                run=lambda c: None,
                probe=lambda: Availability(False, "nenhum tocador", transient=True),
            )
        )
        registro.register(
            ActionSpec(
                "t.parametro", "Com parâmetro", Category.SISTEMA,
                run=lambda c: None,
                parameters=(Parameter("alvo", "Alvo"),),
            )
        )
        monkeypatch.setattr(registry_module, "_default", registro)
        return registro

    def _resolver(self, registro, bindings):
        """Só os botões de clique; os de gesto saem no segundo dicionário."""
        daemon, settings = _daemon(bindings, registro)
        cliques, _ = daemon._resolve_bindings(settings)
        return cliques

    def _resolver_gestos(self, registro, bindings):
        daemon, settings = _daemon(bindings, registro)
        _, gestos = daemon._resolve_bindings(settings)
        return gestos

    def test_acao_disponivel_entra(self, registro):
        assert list(self._resolver(registro, {"0x53": "t.ok"})) == [0x53]

    def test_acao_desconhecida_fica_de_fora(self, registro):
        assert self._resolver(registro, {"0x53": "nao.existe"}) == {}

    def test_falta_estrutural_deixa_o_botao_de_fabrica(self, registro):
        assert self._resolver(registro, {"0x53": "t.sem_permissao"}) == {}

    def test_parametro_faltando_deixa_o_botao_de_fabrica(self, registro):
        assert self._resolver(registro, {"0x53": "t.parametro"}) == {}

    def test_falta_passageira_ainda_desvia(self, registro):
        # O tocador pode abrir depois; o botão precisa estar pronto.
        assert list(self._resolver(registro, {"0x53": "t.passageira"})) == [0x53]

    def test_botao_com_gestos_nao_dispara_no_clique(self, registro):
        """Um botão de gestos passa pelo reconhecedor, não pelo clique direto.

        Disparar no aperto tiraria dele a chance de virar arrasto.
        """
        vinculos = {"0x1A0": {"tap": "t.ok", "hold": "t.ok"}}
        assert self._resolver(registro, vinculos) == {}
        assert set(self._resolver_gestos(registro, vinculos)[0x1A0]) == {
            Gesture.TAP,
            Gesture.HOLD,
        }

    def test_gesto_indisponivel_nao_leva_os_outros(self, registro):
        gestos = self._resolver_gestos(
            registro, {"0x1A0": {"tap": "t.ok", "hold": "t.sem_permissao"}}
        )
        assert set(gestos[0x1A0]) == {Gesture.TAP}

    def test_botao_sem_nenhum_gesto_valido_fica_de_fabrica(self, registro):
        gestos = self._resolver_gestos(registro, {"0x1A0": {"tap": "nao.existe"}})
        assert gestos == {}

    def test_um_vinculo_ruim_nao_leva_os_bons(self, registro):
        resolvidas = self._resolver(registro, {"0x53": "nao.existe", "0x56": "t.ok"})
        assert list(resolvidas) == [0x56]

    def test_acao_que_estoura_nao_derruba_o_daemon(self, registro, caplog):
        def explode(context):
            raise ActionError("deu ruim")

        registro.register(ActionSpec("t.explode", "Explode", Category.SISTEMA, run=explode))
        daemon, _ = _daemon({}, registro)
        daemon._fire(0x53, resolve(Binding("t.explode")))
        assert "deu ruim" in caplog.text
