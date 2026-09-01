# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes dos perfis: correspondência, combinação e persistência."""

from __future__ import annotations

import json

from logitune.config import Config, Match, Profile, Settings, example_config, load


class TestMatch:
    def test_casa_por_classe_da_janela(self):
        match = Match(wm_class=["firefox"])
        assert match.matches("firefox", "qualquer título")
        assert not match.matches("code", "qualquer título")

    def test_ignora_maiusculas(self):
        assert Match(wm_class=["FireFox"]).matches("firefox", "")

    def test_casa_por_trecho(self):
        assert Match(wm_class=["brave"]).matches("brave-browser", "")

    def test_exige_classe_e_titulo_quando_ambos_definidos(self):
        match = Match(wm_class=["code"], title=["projeto"])
        assert match.matches("code", "meu projeto - VS Code")
        assert not match.matches("code", "outra coisa")

    def test_match_vazio_nunca_casa(self):
        # Um perfil sem regra nenhuma capturaria tudo, o que quase certamente
        # não é o que o usuário quis dizer.
        assert not Match().matches("firefox", "título")


class TestSettingsMerge:
    def test_perfil_sobrepoe_o_padrao(self):
        base = Settings(dpi=2800, smartshift=32, invert_thumb=True)
        perfil = Settings(dpi=1600)
        merged = perfil.merged_with(base)
        assert merged.dpi == 1600
        assert merged.smartshift == 32
        assert merged.invert_thumb is True

    def test_false_nao_e_tratado_como_ausente(self):
        base = Settings(ratchet=True)
        merged = Settings(ratchet=False).merged_with(base)
        assert merged.ratchet is False

    def test_botoes_sao_combinados(self):
        base = Settings(buttons={"0x0053": "0x0052"})
        merged = Settings(buttons={"0x0056": "0x00C3"}).merged_with(base)
        assert merged.buttons == {"0x0053": "0x0052", "0x0056": "0x00C3"}

    def test_pares_de_botoes_convertem_hexadecimal(self):
        assert Settings(buttons={"0x0053": "0x0052"}).button_pairs() == [(0x53, 0x52)]

    def test_par_invalido_e_descartado(self):
        assert Settings(buttons={"nada": "0x0052"}).button_pairs() == []

    def test_acoes_convertem_hexadecimal(self):
        assert Settings(actions={"0x01A0": "xdotool key super"}).action_pairs() == [
            (0x01A0, "xdotool key super")
        ]


class TestConfig:
    def test_escolhe_o_primeiro_perfil_que_casa(self):
        config = Config(
            default=Settings(dpi=2800),
            profiles=[
                Profile("A", Match(wm_class=["code"]), Settings(dpi=1000)),
                Profile("B", Match(wm_class=["code"]), Settings(dpi=2000)),
            ],
        )
        nome, settings = config.settings_for("code", "")
        assert nome == "A"
        assert settings.dpi == 1000

    def test_cai_no_padrao_quando_nada_casa(self):
        config = Config(default=Settings(dpi=2800))
        nome, settings = config.settings_for("nautilus", "")
        assert nome == "padrão"
        assert settings.dpi == 2800

    def test_roundtrip_json(self, tmp_path):
        original = example_config()
        destino = tmp_path / "config.json"
        original.save(destino)
        assert load(destino).to_dict() == original.to_dict()

    def test_arquivo_ausente_devolve_padrao(self, tmp_path):
        assert load(tmp_path / "nao-existe.json").to_dict() == Config().to_dict()

    def test_json_invalido_nao_derruba(self, tmp_path):
        ruim = tmp_path / "ruim.json"
        ruim.write_text("{ isso não é json")
        assert load(ruim).to_dict() == Config().to_dict()

    def test_campos_desconhecidos_sao_ignorados(self, tmp_path):
        arquivo = tmp_path / "futuro.json"
        arquivo.write_text(json.dumps({
            "version": 1,
            "default": {"dpi": 1200, "recurso_do_futuro": True},
            "profiles": [],
        }))
        assert load(arquivo).default.dpi == 1200

    def test_gravacao_e_atomica(self, tmp_path):
        destino = tmp_path / "config.json"
        example_config().save(destino)
        assert destino.is_file()
        # O arquivo temporário não pode sobrar no diretório.
        assert not list(tmp_path.glob("*.tmp"))


class TestPermissoes:
    """A configuração define comandos que o daemon executa, então quem puder
    escrevê-la executa código como o usuário. As permissões são um limite de
    segurança, não um detalhe."""

    def test_arquivo_salvo_e_privado(self, tmp_path):
        destino = tmp_path / "logitune" / "config.json"
        example_config().save(destino)
        modo = destino.stat().st_mode & 0o777
        assert modo == 0o600, f"config gravada como {modo:04o}"

    def test_diretorio_salvo_e_privado(self, tmp_path):
        destino = tmp_path / "logitune" / "config.json"
        example_config().save(destino)
        modo = destino.parent.stat().st_mode & 0o777
        assert modo == 0o700, f"diretório criado como {modo:04o}"

    def test_sobrescrever_nao_afrouxa_as_permissoes(self, tmp_path):
        destino = tmp_path / "logitune" / "config.json"
        example_config().save(destino)
        destino.chmod(0o644)
        example_config().save(destino)
        assert destino.stat().st_mode & 0o777 == 0o600

    def test_permissao_frouxa_e_detectada(self, tmp_path):
        from logitune.config import check_permissions

        destino = tmp_path / "config.json"
        example_config().save(destino)
        assert check_permissions(destino) is None

        destino.chmod(0o664)
        aviso = check_permissions(destino)
        assert aviso is not None and "chmod" in aviso

    def test_arquivo_ausente_nao_gera_aviso(self, tmp_path):
        from logitune.config import check_permissions

        assert check_permissions(tmp_path / "nao-existe.json") is None


class TestValidacao:
    """load() engole erro de propósito — um arquivo quebrado não pode derrubar
    o daemon. Mas engolir esconde, e foi assim que uma configuração inválida
    passou despercebida enquanto os ajustes deixavam de valer."""

    def test_arquivo_bom_nao_reclama(self, tmp_path):
        from logitune.config import validate

        destino = tmp_path / "config.json"
        example_config().save(destino)
        assert validate(destino) is None

    def test_json_quebrado_e_apontado_com_a_linha(self, tmp_path):
        from logitune.config import validate

        destino = tmp_path / "config.json"
        # O erro real cometido ao migrar de "actions" para "bindings":
        # as duas chaves ficaram na mesma linha.
        destino.write_text(
            '{\n  "version": 1,\n'
            '  "default": { "actions": "bindings": { "0x1": "a" } }\n}\n'
        )
        erro = validate(destino)
        assert erro is not None
        assert "linha 3" in erro

    def test_arquivo_ausente_nao_e_erro(self, tmp_path):
        from logitune.config import validate

        assert validate(tmp_path / "nao-existe.json") is None

    def test_json_que_nao_e_objeto(self, tmp_path):
        from logitune.config import validate

        destino = tmp_path / "config.json"
        destino.write_text("[1, 2, 3]")
        assert validate(destino) is not None
