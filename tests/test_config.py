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
