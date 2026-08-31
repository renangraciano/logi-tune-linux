"""Perfis de configuração do logi-tune-linux.

Um perfil descreve como o mouse deve se comportar; regras de correspondência
dizem quando ele vale. O daemon observa a janela em foco e aplica o primeiro
perfil que casar, caindo no perfil padrão quando nenhum casa.

O arquivo fica em ``~/.config/logitune/config.json``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "logitune"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class Settings:
    """O que aplicar no mouse. Campos em ``None`` ficam como estão."""

    dpi: int | None = None
    #: Ponto de virada do SmartShift (1–255).
    smartshift: int | None = None
    #: ``True`` trava a roda em ratchet, ``False`` deixa livre.
    ratchet: bool | None = None
    invert_scroll: bool | None = None
    hires_scroll: bool | None = None
    invert_thumb: bool | None = None
    #: Remapeamentos, de CID de origem para CID de destino.
    #: As chaves são strings hexadecimais ("0x0053") para o JSON ficar legível.
    buttons: dict[str, str] = field(default_factory=dict)
    #: Comandos disparados por botões desviados, de CID para linha de comando.
    #: Um botão que aparece aqui é desviado pelo daemon: ele deixa de gerar o
    #: clique normal e passa a executar este comando.
    actions: dict[str, str] = field(default_factory=dict)

    def merged_with(self, base: Settings) -> Settings:
        """Combina com um perfil base, deixando este ter a última palavra."""
        merged = Settings(**{**asdict(base), **{
            k: v for k, v in asdict(self).items() if v is not None and v != {}
        }})
        merged.buttons = {**base.buttons, **self.buttons}
        merged.actions = {**base.actions, **self.actions}
        return merged

    def action_pairs(self) -> list[tuple[int, str]]:
        """As ações como pares ``(CID, comando)``."""
        pairs: list[tuple[int, str]] = []
        for source, command in self.actions.items():
            try:
                pairs.append((int(source, 0), command))
            except ValueError:
                logger.warning("ação com controle inválido ignorada: %s", source)
        return pairs

    def button_pairs(self) -> list[tuple[int, int]]:
        """Os remapeamentos como pares de inteiros ``(origem, destino)``."""
        pairs: list[tuple[int, int]] = []
        for source, target in self.buttons.items():
            try:
                pairs.append((int(source, 0), int(target, 0)))
            except ValueError:
                logger.warning("remapeamento inválido ignorado: %s -> %s", source, target)
        return pairs


@dataclass
class Match:
    """Quando um perfil se aplica.

    ``wm_class`` casa a classe da janela (``brave-browser``, ``code``);
    ``title`` casa um trecho do título. Ambos são comparados sem diferenciar
    maiúsculas. Uma lista vazia significa "não filtra por isso".
    """

    wm_class: list[str] = field(default_factory=list)
    title: list[str] = field(default_factory=list)

    def matches(self, window_class: str, window_title: str) -> bool:
        if not self.wm_class and not self.title:
            return False
        if self.wm_class:
            alvo = window_class.casefold()
            if not any(needle.casefold() in alvo for needle in self.wm_class):
                return False
        if self.title:
            alvo = window_title.casefold()
            if not any(needle.casefold() in alvo for needle in self.title):
                return False
        return True


@dataclass
class Profile:
    name: str
    match: Match = field(default_factory=Match)
    settings: Settings = field(default_factory=Settings)


@dataclass
class Config:
    version: int = CONFIG_VERSION
    #: Aplicado quando nenhum perfil casa, e como base para todos eles.
    default: Settings = field(default_factory=Settings)
    profiles: list[Profile] = field(default_factory=list)

    def profile_for(self, window_class: str, window_title: str) -> Profile | None:
        """O primeiro perfil que casa com a janela em foco."""
        for profile in self.profiles:
            if profile.match.matches(window_class, window_title):
                return profile
        return None

    def settings_for(self, window_class: str, window_title: str) -> tuple[str, Settings]:
        """Devolve ``(nome do perfil, ajustes já combinados com o padrão)``."""
        profile = self.profile_for(window_class, window_title)
        if profile is None:
            return "padrão", self.default
        return profile.name, profile.settings.merged_with(self.default)

    # -- persistência --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "default": asdict(self.default),
            "profiles": [asdict(p) for p in self.profiles],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        version = data.get("version", CONFIG_VERSION)
        if version > CONFIG_VERSION:
            logger.warning(
                "configuração na versão %s, mais nova que a suportada (%s); "
                "campos desconhecidos serão ignorados",
                version,
                CONFIG_VERSION,
            )

        def build_settings(raw: dict) -> Settings:
            campos = {f for f in Settings.__dataclass_fields__}
            return Settings(**{k: v for k, v in (raw or {}).items() if k in campos})

        profiles = []
        for raw in data.get("profiles", []):
            match_raw = raw.get("match", {}) or {}
            profiles.append(
                Profile(
                    name=raw.get("name", "sem nome"),
                    match=Match(
                        wm_class=list(match_raw.get("wm_class", [])),
                        title=list(match_raw.get("title", [])),
                    ),
                    settings=build_settings(raw.get("settings", {})),
                )
            )

        return cls(
            version=CONFIG_VERSION,
            default=build_settings(data.get("default", {})),
            profiles=profiles,
        )

    def save(self, path: Path | None = None) -> Path:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Escrita atômica: um daemon lendo nunca vê um arquivo pela metade.
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")
        temporary.replace(target)
        return target


def load(path: Path | None = None) -> Config:
    """Lê a configuração, devolvendo o padrão se o arquivo não existir."""
    target = path or config_path()
    if not target.is_file():
        return Config()
    try:
        return Config.from_dict(json.loads(target.read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("não foi possível ler %s: %s — usando a configuração padrão", target, exc)
        return Config()


def example_config() -> Config:
    """Uma configuração de exemplo, escrita no primeiro uso do daemon."""
    return Config(
        default=Settings(dpi=2800, smartshift=32, invert_thumb=True),
        profiles=[
            Profile(
                name="Navegador",
                match=Match(wm_class=["firefox", "brave", "chrome", "chromium"]),
                settings=Settings(dpi=2000),
            ),
            Profile(
                name="Editor de código",
                match=Match(wm_class=["code", "jetbrains", "gnome-terminal"]),
                settings=Settings(dpi=3200, ratchet=True),
            ),
        ],
    )
