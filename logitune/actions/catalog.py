# SPDX-License-Identifier: GPL-3.0-or-later
"""O que dá para atribuir a um botão.

O conteúdo espelha o catálogo do Logi Options+, adaptado ao GNOME: onde o
original manda para o Mission Control, mandamos para a visão de atividades;
onde ele oferece Launchpad, oferecemos a grade de aplicativos. O que não tem
equivalente ficou de fora em vez de virar uma entrada que não funciona.

Cada atalho de teclado aqui foi conferido contra as chaves do ``gsettings``
desta sessão do Ubuntu 24.04 — ``Print`` para a captura de tela, ``Super+H``
para minimizar, ``Ctrl+Alt+seta`` para as áreas de trabalho. Onde o GNOME não
tem atalho de fábrica (maximizar, por exemplo) usamos o que ele reconhece de
qualquer forma (``Alt+F10``, alternar maximizado).
"""

from __future__ import annotations

from logitune.actions.backends import audio, dbus, keys, launch, mouse
from logitune.actions.registry import Registry
from logitune.actions.spec import (
    ActionSpec,
    Category,
    Parameter,
)

#: As ações que a interface destaca antes de mostrar o catálogo inteiro,
#: como o grupo "Recomendável" do original. É uma seleção, não uma categoria:
#: cada uma delas também aparece no grupo a que pertence.
RECOMMENDED: tuple[str, ...] = (
    "system.overview",
    "system.screenshot",
    "browser.back",
    "browser.forward",
    "media.play_pause",
    "meeting.mic_mute",
    "window.switch",
    "mouse.toggle_ratchet",
)


def _keys(
    action_id: str,
    label: str,
    category: Category,
    shortcut: str,
    description: str = "",
) -> ActionSpec:
    """Uma ação que é um atalho de teclado fixo."""
    return ActionSpec(
        id=action_id,
        label=label,
        category=category,
        description=description or f"Envia {shortcut}",
        shortcut=shortcut,
        run=lambda context, atalho=shortcut: keys.tap(atalho),
        probe=keys.availability,
    )


def _shell(action_id: str, label: str, category: Category, method: str, description: str) -> ActionSpec:
    return ActionSpec(
        id=action_id,
        label=label,
        category=category,
        description=description,
        run=lambda context, m=method: dbus.shell_call(m),
        probe=dbus.shell_availability,
    )


def _media(action_id: str, label: str, method: str, description: str) -> ActionSpec:
    return ActionSpec(
        id=action_id,
        label=label,
        category=Category.MIDIA,
        description=description,
        run=lambda context, m=method: dbus.media_call(m),
        probe=dbus.media_availability,
    )


def _volume(action_id: str, label: str, step: int) -> ActionSpec:
    return ActionSpec(
        id=action_id,
        label=label,
        category=Category.MIDIA,
        description=f"Muda o volume da saída padrão em {step:+d}%",
        run=lambda context, s=step: audio.change_volume(s),
        probe=audio.availability,
    )


def _specs() -> list[ActionSpec]:
    S, J, M, R = Category.SISTEMA, Category.JANELAS, Category.MIDIA, Category.REUNIAO
    E, N = Category.EDICAO, Category.NAVEGADOR

    return [
        # -- sistema --------------------------------------------------
        _keys("system.overview", "Visão de atividades", S, "super",
              "Abre a visão de atividades do GNOME"),
        _shell("system.applications", "Grade de aplicativos", S, "ShowApplications",
               "Mostra todos os aplicativos instalados"),
        _shell("system.search", "Pesquisar", S, "FocusSearch",
               "Abre a pesquisa do GNOME"),
        ActionSpec(
            id="system.lock",
            label="Bloquear a tela",
            category=S,
            description="Tranca a sessão",
            run=lambda context: dbus.lock_screen(),
            probe=dbus.screensaver_availability,
        ),
        # A captura de tela tem método D-Bus, mas o GNOME recusa a chamada de
        # quem não é o shell (AccessDenied). A tecla é o caminho sancionado.
        _keys("system.screenshot", "Captura de tela", S, "print",
              "Abre a ferramenta de captura do GNOME"),
        _keys("system.screenshot_area", "Capturar uma área", S, "shift+print",
              "Captura direto uma região da tela"),
        _keys("system.screenshot_window", "Capturar a janela", S, "alt+print",
              "Captura direto a janela em foco"),
        _keys("system.notifications", "Central de notificações", S, "super+v"),

        # -- janelas e áreas de trabalho -------------------------------
        _keys("window.switch", "Alternar janelas", J, "alt+tab"),
        _keys("window.maximize", "Maximizar/restaurar", J, "alt+f10"),
        _keys("window.minimize", "Minimizar", J, "super+h"),
        _keys("window.close", "Fechar a janela", J, "alt+f4"),
        _keys("window.tile_left", "Encostar à esquerda", J, "super+left"),
        _keys("window.tile_right", "Encostar à direita", J, "super+right"),
        _keys("workspace.left", "Área de trabalho anterior", J, "ctrl+alt+left"),
        _keys("workspace.right", "Próxima área de trabalho", J, "ctrl+alt+right"),
        _keys("workspace.move_left", "Levar a janela para a esquerda", J,
              "ctrl+shift+alt+left"),
        _keys("workspace.move_right", "Levar a janela para a direita", J,
              "ctrl+shift+alt+right"),

        # -- mídia -----------------------------------------------------
        _media("media.play_pause", "Tocar/pausar", "PlayPause",
               "Controla o tocador ativo por MPRIS"),
        _media("media.next", "Próxima faixa", "Next", "Pula para a próxima faixa"),
        _media("media.previous", "Faixa anterior", "Previous", "Volta uma faixa"),
        _media("media.stop", "Parar", "Stop", "Para a reprodução"),
        _volume("media.volume_up", "Aumentar o volume", audio.DEFAULT_STEP),
        _volume("media.volume_down", "Diminuir o volume", -audio.DEFAULT_STEP),
        ActionSpec(
            id="media.mute",
            label="Mudo",
            category=M,
            description="Silencia a saída de áudio",
            run=lambda context: audio.toggle_mute(),
            probe=audio.availability,
        ),

        # -- reunião ---------------------------------------------------
        # Só o microfone: ligar e desligar a câmera não tem controle de
        # sessão no Linux, cada aplicativo de reunião resolve do seu jeito.
        ActionSpec(
            id="meeting.mic_mute",
            label="Mudo do microfone",
            category=R,
            description="Silencia a entrada de áudio padrão",
            run=lambda context: audio.toggle_mute(target=audio.SOURCE),
            probe=audio.availability,
        ),

        # -- edição ----------------------------------------------------
        _keys("edit.copy", "Copiar", E, "ctrl+c"),
        _keys("edit.paste", "Colar", E, "ctrl+v"),
        _keys("edit.cut", "Recortar", E, "ctrl+x"),
        _keys("edit.undo", "Desfazer", E, "ctrl+z"),
        _keys("edit.redo", "Refazer", E, "ctrl+shift+z"),
        _keys("edit.select_all", "Selecionar tudo", E, "ctrl+a"),
        _keys("edit.save", "Salvar", E, "ctrl+s"),
        _keys("edit.find", "Localizar", E, "ctrl+f"),
        _keys("edit.zoom_in", "Aproximar", E, "ctrl+plus"),
        _keys("edit.zoom_out", "Afastar", E, "ctrl+minus"),
        _keys("edit.zoom_reset", "Zoom original", E, "ctrl+0"),

        # -- navegador -------------------------------------------------
        _keys("browser.back", "Voltar", N, "alt+left"),
        _keys("browser.forward", "Avançar", N, "alt+right"),
        _keys("browser.reload", "Recarregar", N, "ctrl+r"),
        _keys("browser.new_tab", "Nova aba", N, "ctrl+t"),
        _keys("browser.close_tab", "Fechar a aba", N, "ctrl+w"),
        _keys("browser.reopen_tab", "Reabrir a aba fechada", N, "ctrl+shift+t"),
        _keys("browser.next_tab", "Próxima aba", N, "ctrl+pagedown"),
        _keys("browser.previous_tab", "Aba anterior", N, "ctrl+pageup"),

        # -- mouse -----------------------------------------------------
        ActionSpec(
            id="mouse.toggle_ratchet",
            label="Travar/soltar a roda",
            category=Category.MOUSE,
            description="Alterna entre catraca e roda livre",
            run=mouse.toggle_ratchet,
        ),
        ActionSpec(
            id="mouse.dpi_cycle",
            label="Trocar a sensibilidade",
            category=Category.MOUSE,
            description="Passa para o próximo DPI da lista, ou alterna o modo mira",
            parameters=(
                Parameter("values", "DPIs a percorrer", kind="number", required=False),
            ),
            run=mouse.cycle_dpi,
        ),
        ActionSpec(
            id="mouse.host_next",
            label="Trocar de computador",
            category=Category.MOUSE,
            description="Easy-Switch para o próximo canal pareado",
            run=mouse.next_host,
        ),
        ActionSpec(
            id="mouse.haptic",
            label="Vibrar",
            category=Category.MOUSE,
            description="Toca um padrão do motor háptico",
            parameters=(
                Parameter("waveform", "Padrão (0–14)", kind="number", required=False, default=2),
            ),
            run=mouse.play_haptic,
        ),

        # -- abrir -----------------------------------------------------
        ActionSpec(
            id="app.launch",
            label="Abrir um aplicativo",
            category=Category.APLICATIVO,
            description="Inicia um aplicativo instalado",
            parameters=(Parameter("app", "Aplicativo", kind="app"),),
            run=lambda context: launch.launch_app(context.require("app")),
            probe=launch.availability,
        ),
        ActionSpec(
            id="app.open_url",
            label="Abrir um endereço",
            category=Category.APLICATIVO,
            description="Abre um site, arquivo ou pasta no aplicativo padrão",
            parameters=(Parameter("url", "Endereço ou caminho", kind="url"),),
            run=lambda context: launch.open_uri(context.require("url")),
            probe=launch.availability,
        ),

        # -- personalizado ---------------------------------------------
        ActionSpec(
            id="key.shortcut",
            label="Atalho de teclado",
            category=Category.PERSONALIZADO,
            description='Envia qualquer combinação, escrita como "ctrl+shift+t"',
            parameters=(Parameter("keys", "Atalho", kind="shortcut"),),
            run=lambda context: keys.tap(context.require("keys")),
            probe=keys.availability,
        ),
        ActionSpec(
            id="shell.run",
            label="Executar um comando",
            category=Category.PERSONALIZADO,
            description="Roda uma linha de comando; é a saída para o que o catálogo não cobre",
            parameters=(Parameter("command", "Linha de comando", kind="command"),),
            run=lambda context: launch.run_command(context.require("command")),
        ),
    ]


def build() -> Registry:
    """Monta o catálogo padrão."""
    registry = Registry()
    for spec in _specs():
        registry.register(spec)
    return registry
