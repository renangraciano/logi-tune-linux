# SPDX-License-Identifier: GPL-3.0-or-later
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
from typing import Any

from logitune.actions.gestures import GestureThresholds
from logitune.actions.binding import (
    BindingError,
    ButtonBinding,
    WheelBinding,
    command_binding,
    merge_raw,
)

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1

#: Só o dono lê e escreve a configuração: ela define comandos que o daemon
#: executa, então permissão de grupo ou de outros vira execução de código.
FILE_MODE = 0o600
DIR_MODE = 0o700


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
    #: Forma antiga, mantida para não quebrar quem já configurou: cada entrada
    #: vira a ação ``shell.run``. Prefira ``bindings``.
    actions: dict[str, str] = field(default_factory=dict)
    #: Ações do catálogo por botão, de CID para id de ação, objeto com
    #: parâmetros ou mapa de gestos. Ver :mod:`logitune.actions.binding`.
    bindings: dict[str, Any] = field(default_factory=dict)
    #: O que a roda do polegar faz. Vazio deixa a rolagem horizontal do
    #: sistema em paz, que é o comportamento de fábrica.
    thumbwheel: Any = None

    def merged_with(self, base: Settings) -> Settings:
        """Combina com um perfil base, deixando este ter a última palavra."""
        merged = Settings(**{**asdict(base), **{
            k: v for k, v in asdict(self).items() if v is not None and v != {}
        }})
        merged.buttons = {**base.buttons, **self.buttons}
        merged.actions = {**base.actions, **self.actions}
        # Os vínculos precisam de merge por gesto: um perfil que sobrescreve
        # só o "tap" não pode apagar os outros seis gestos do mesmo botão.
        merged.bindings = merge_raw(base.bindings, self.bindings)
        merged.thumbwheel = (
            self.thumbwheel if self.thumbwheel is not None else base.thumbwheel
        )
        return merged

    def wheel_binding(self) -> WheelBinding:
        """O que a roda do polegar faz neste perfil."""
        try:
            return WheelBinding.parse(self.thumbwheel)
        except BindingError as exc:
            logger.warning("roda do polegar com configuração inválida: %s", exc)
            return WheelBinding()

    def action_pairs(self) -> list[tuple[int, str]]:
        """As ações antigas como pares ``(CID, comando)``."""
        pairs: list[tuple[int, str]] = []
        for source, command in self.actions.items():
            try:
                pairs.append((int(source, 0), command))
            except ValueError:
                logger.warning("ação com controle inválido ignorada: %s", source)
        return pairs

    def binding_pairs(self) -> list[tuple[int, ButtonBinding]]:
        """Tudo que os botões fazem, como pares ``(CID, vínculo)``.

        As duas formas de configurar entram aqui: os comandos da chave antiga
        ``actions`` e os vínculos de ``bindings``, com estes últimos tendo a
        palavra final quando o mesmo botão aparece nos dois lugares.
        """
        pairs: dict[int, ButtonBinding] = {}

        for source, command in self.actions.items():
            try:
                pairs[int(source, 0)] = command_binding(command)
            except ValueError:
                logger.warning("ação com controle inválido ignorada: %s", source)

        for source, raw in self.bindings.items():
            try:
                cid = int(source, 0)
            except ValueError:
                logger.warning("vínculo com controle inválido ignorado: %s", source)
                continue
            try:
                pairs[cid] = ButtonBinding.parse(raw)
            except BindingError as exc:
                logger.warning("vínculo inválido para %s: %s", source, exc)

        return sorted(pairs.items())

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
    #: Reconhecimento de gestos: se está ligado e com que limiares. Fica fora
    #: dos perfis de propósito: descreve a mão de quem usa, não o aplicativo
    #: em foco.
    gestures: dict[str, Any] = field(default_factory=dict)

    @property
    def gestures_enabled(self) -> bool:
        """Os gestos estão ligados?

        Ligados por padrão: quem escreveu um mapa de gestos já disse o que
        queria, e não deveria precisar de uma segunda confirmação. O
        interruptor existe para desligar sem perder a configuração.
        """
        return bool(self.gestures.get("enabled", True))

    #: Ajustes da roda do polegar que descrevem a mão, não o aplicativo: o
    #: tempo até o alternador confirmar a escolha. Fica fora dos perfis pelo
    #: mesmo motivo que os limiares de gesto.
    wheel: dict[str, Any] = field(default_factory=dict)

    #: Economia de energia. Fica fora dos perfis: descreve o cuidado com o
    #: dispositivo, não o aplicativo em foco.
    power: dict[str, Any] = field(default_factory=dict)

    @property
    def haptics_below(self) -> int:
        """Abaixo de que carga o motor háptico cala. Zero desliga a economia."""
        from logitune.actions.power import DEFAULT_THRESHOLD

        bruto = self.power.get("haptics_below", DEFAULT_THRESHOLD)
        try:
            valor = int(bruto)
        except (TypeError, ValueError):
            logger.warning("haptics_below inválido ignorado: %r", bruto)
            return DEFAULT_THRESHOLD
        if not 0 <= valor <= 100:
            logger.warning("haptics_below fora da faixa (0–100): %s", valor)
            return DEFAULT_THRESHOLD
        return valor

    @property
    def switcher_idle_ms(self) -> int:
        """Quanto tempo sem girar até o alternador confirmar.

        Curto demais confirma no meio de um giro lento; longo demais atrasa a
        janela que se quis trazer para a frente.
        """
        from logitune.actions.switcher import DEFAULT_IDLE_MS

        bruto = self.wheel.get("switcher_idle_ms", DEFAULT_IDLE_MS)
        try:
            valor = int(bruto)
        except (TypeError, ValueError):
            logger.warning("switcher_idle_ms inválido ignorado: %r", bruto)
            return DEFAULT_IDLE_MS
        if not 100 <= valor <= 5000:
            logger.warning("switcher_idle_ms fora da faixa (100–5000): %s", valor)
            return DEFAULT_IDLE_MS
        return valor

    def gesture_thresholds(self) -> GestureThresholds:
        """Os limiares configurados, caindo no padrão medido para o resto."""
        campos = {f for f in GestureThresholds.__dataclass_fields__}
        valores: dict[str, int] = {}
        for chave, valor in self.gestures.items():
            if chave == "enabled":
                continue
            if chave not in campos:
                logger.warning("limiar de gesto desconhecido ignorado: %s", chave)
                continue
            try:
                valores[chave] = int(valor)
            except (TypeError, ValueError):
                logger.warning("limiar de gesto inválido ignorado: %s=%r", chave, valor)

        try:
            return GestureThresholds(**valores)
        except ValueError as exc:
            logger.error("limiares de gesto inválidos (%s); usando os padrões", exc)
            return GestureThresholds()

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
            "gestures": dict(self.gestures),
            "wheel": dict(self.wheel),
            "power": dict(self.power),
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
            gestures=dict(data.get("gestures", {}) or {}),
            wheel=dict(data.get("wheel", {}) or {}),
            power=dict(data.get("power", {}) or {}),
        )

    def save(self, path: Path | None = None) -> Path:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)

        # Este arquivo decide quais comandos o daemon executa, então quem
        # puder escrevê-lo executa código com os privilégios do usuário.
        # Trancamos o diretório e o arquivo para o dono.
        try:
            target.parent.chmod(DIR_MODE)
        except OSError as exc:
            logger.warning("não consegui restringir %s: %s", target.parent, exc)

        # Escrita atômica: um daemon lendo nunca vê um arquivo pela metade.
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")
        temporary.chmod(FILE_MODE)
        temporary.replace(target)
        return target


def check_permissions(path: Path | None = None) -> str | None:
    """Avisa se a configuração está exposta a outros usuários.

    Devolve a mensagem de aviso, ou ``None`` se as permissões estão certas.
    """
    target = path or config_path()
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        return None
    if mode & 0o077:
        return (
            f"{target} está acessível a outros usuários (modo {mode:04o}). "
            f"Como este arquivo define comandos que o daemon executa, "
            f"corrija com: chmod {FILE_MODE:o} {target}"
        )
    return None


def validate(path: Path | None = None) -> str | None:
    """Confere se a configuração é legível. Devolve o erro, ou ``None``.

    :func:`load` engole o erro de propósito — um arquivo quebrado não pode
    derrubar o daemon — mas engolir também esconde: o daemon volta aos padrões
    e nada na tela avisa que os seus ajustes pararam de valer. Esta função
    existe para o diagnóstico poder contar.
    """
    target = path or config_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        return f"{target} tem JSON inválido na linha {exc.lineno}: {exc.msg}"
    except OSError as exc:
        return f"não consegui ler {target}: {exc}"
    if not isinstance(data, dict):
        return f"{target} deveria conter um objeto JSON"
    return None


def load(path: Path | None = None) -> Config:
    """Lê a configuração, devolvendo o padrão se o arquivo não existir."""
    target = path or config_path()
    if not target.is_file():
        return Config()

    aviso = check_permissions(target)
    if aviso:
        logger.warning("%s", aviso)
    try:
        return Config.from_dict(json.loads(target.read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("não foi possível ler %s: %s — usando a configuração padrão", target, exc)
        return Config()


def example_config() -> Config:
    """Uma configuração de exemplo, escrita no primeiro uso do daemon."""
    return Config(
        default=Settings(
            dpi=2800,
            smartshift=32,
            invert_thumb=True,
            # Um botão, uma ação: é o que quase todo mundo quer, e o que a
            # configuração de exemplo deve ensinar. Gestos existem, mas são
            # opcionais — veja o README. "logitune actions" lista o catálogo.
            bindings={
                "0x0056": "browser.reopen_tab",
                "0x01A0": "system.overview",
            },
        ),
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
