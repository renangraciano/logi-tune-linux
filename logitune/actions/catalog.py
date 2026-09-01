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
from logitune.i18n import _
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
        description=description or _("Sends {}").format(shortcut),
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
        _keys("system.overview", _("Activities overview"), S, "super",
              _("Opens the GNOME activities overview")),
        _shell("system.applications", _("Application grid"), S, "ShowApplications",
               _("Shows every installed application")),
        _shell("system.search", _("Search"), S, "FocusSearch",
               _("Opens GNOME search")),
        ActionSpec(
            id="system.lock",
            label=_("Lock the screen"),
            category=S,
            description=_("Locks the session"),
            run=lambda context: dbus.lock_screen(),
            probe=dbus.screensaver_availability,
        ),
        # A captura de tela tem método D-Bus, mas o GNOME recusa a chamada de
        # quem não é o shell (AccessDenied). A tecla é o caminho sancionado.
        _keys("system.screenshot", _("Screenshot"), S, "print",
              _("Opens the GNOME screenshot tool")),
        _keys("system.screenshot_area", _("Capture an area"), S, "shift+print",
              _("Captures a region of the screen directly")),
        _keys("system.screenshot_window", _("Capture the window"), S, "alt+print",
              _("Captures the focused window directly")),
        _keys("system.notifications", _("Notification centre"), S, "super+v"),

        # -- janelas e áreas de trabalho -------------------------------
        _keys("window.switch", _("Switch windows"), J, "alt+tab"),
        _keys("window.maximize", _("Maximise/restore"), J, "alt+f10"),
        _keys("window.minimize", _("Minimise"), J, "super+h"),
        _keys("window.close", _("Close the window"), J, "alt+f4"),
        _keys("window.tile_left", _("Tile left"), J, "super+left"),
        _keys("window.tile_right", _("Tile right"), J, "super+right"),
        _keys("workspace.left", _("Previous workspace"), J, "ctrl+alt+left"),
        _keys("workspace.right", _("Next workspace"), J, "ctrl+alt+right"),
        _keys("workspace.move_left", _("Move the window left"), J,
              "ctrl+shift+alt+left"),
        _keys("workspace.move_right", _("Move the window right"), J,
              "ctrl+shift+alt+right"),

        # -- mídia -----------------------------------------------------
        _media("media.play_pause", _("Play/pause"), "PlayPause",
               _("Controls the active player over MPRIS")),
        _media("media.next", _("Next track"), "Next", _("Skips to the next track")),
        _media("media.previous", _("Previous track"), "Previous", _("Goes back one track")),
        _media("media.stop", _("Stop"), "Stop", _("Stops playback")),
        _volume("media.volume_up", _("Volume up"), audio.DEFAULT_STEP),
        _volume("media.volume_down", _("Volume down"), -audio.DEFAULT_STEP),
        ActionSpec(
            id="media.mute",
            label=_("Mute"),
            category=M,
            description=_("Silences the audio output"),
            run=lambda context: audio.toggle_mute(),
            probe=audio.availability,
        ),

        # -- reunião ---------------------------------------------------
        # Só o microfone: ligar e desligar a câmera não tem controle de
        # sessão no Linux, cada aplicativo de reunião resolve do seu jeito.
        ActionSpec(
            id="meeting.mic_mute",
            label=_("Microphone mute"),
            category=R,
            description=_("Silences the default audio input"),
            run=lambda context: audio.toggle_mute(target=audio.SOURCE),
            probe=audio.availability,
        ),

        # -- edição ----------------------------------------------------
        _keys("edit.copy", _("Copy"), E, "ctrl+c"),
        _keys("edit.paste", _("Paste"), E, "ctrl+v"),
        _keys("edit.cut", _("Cut"), E, "ctrl+x"),
        _keys("edit.undo", _("Undo"), E, "ctrl+z"),
        _keys("edit.redo", _("Redo"), E, "ctrl+shift+z"),
        _keys("edit.select_all", _("Select all"), E, "ctrl+a"),
        _keys("edit.save", _("Save"), E, "ctrl+s"),
        _keys("edit.find", _("Find"), E, "ctrl+f"),
        _keys("edit.zoom_in", _("Zoom in"), E, "ctrl+plus"),
        _keys("edit.zoom_out", _("Zoom out"), E, "ctrl+minus"),
        _keys("edit.zoom_reset", _("Actual size"), E, "ctrl+0"),

        # -- navegador -------------------------------------------------
        _keys("browser.back", _("Back"), N, "alt+left"),
        _keys("browser.forward", _("Forward"), N, "alt+right"),
        _keys("browser.reload", _("Reload"), N, "ctrl+r"),
        _keys("browser.new_tab", _("New tab"), N, "ctrl+t"),
        _keys("browser.close_tab", _("Close tab"), N, "ctrl+w"),
        _keys("browser.reopen_tab", _("Reopen closed tab"), N, "ctrl+shift+t"),
        _keys("browser.next_tab", _("Next tab"), N, "ctrl+pagedown"),
        _keys("browser.previous_tab", _("Previous tab"), N, "ctrl+pageup"),

        # -- mouse -----------------------------------------------------
        ActionSpec(
            id="mouse.toggle_ratchet",
            label=_("Lock/free the wheel"),
            category=Category.MOUSE,
            description=_("Toggles between ratchet and freewheel"),
            run=mouse.toggle_ratchet,
        ),
        ActionSpec(
            id="mouse.dpi_cycle",
            label=_("Change sensitivity"),
            category=Category.MOUSE,
            description=_("Moves to the next DPI in the list, or toggles sniper mode"),
            parameters=(
                Parameter("values", _("DPI values to cycle"), kind="number", required=False),
            ),
            run=mouse.cycle_dpi,
        ),
        ActionSpec(
            id="mouse.host_next",
            label=_("Switch computer"),
            category=Category.MOUSE,
            description=_("Easy-Switch to the next paired channel"),
            run=mouse.next_host,
        ),
        ActionSpec(
            id="mouse.haptic",
            label=_("Vibrate"),
            category=Category.MOUSE,
            description=_("Plays a haptic motor pattern"),
            parameters=(
                Parameter("waveform", _("Pattern (0–14)"), kind="number", required=False, default=2),
            ),
            run=mouse.play_haptic,
        ),

        # -- abrir -----------------------------------------------------
        ActionSpec(
            id="app.launch",
            label=_("Open an application"),
            category=Category.APLICATIVO,
            description=_("Starts an installed application"),
            parameters=(Parameter("app", _("Application"), kind="app"),),
            run=lambda context: launch.launch_app(context.require("app")),
            probe=launch.availability,
        ),
        ActionSpec(
            id="app.open_url",
            label=_("Open an address"),
            category=Category.APLICATIVO,
            description=_("Opens a site, file or folder in the default application"),
            parameters=(Parameter("url", _("Address or path"), kind="url"),),
            run=lambda context: launch.open_uri(context.require("url")),
            probe=launch.availability,
        ),

        # -- personalizado ---------------------------------------------
        ActionSpec(
            id="key.shortcut",
            label=_("Keyboard shortcut"),
            category=Category.PERSONALIZADO,
            description='Envia qualquer combinação, escrita como "ctrl+shift+t"',
            parameters=(Parameter("keys", _("Shortcut"), kind="shortcut"),),
            run=lambda context: keys.tap(context.require("keys")),
            probe=keys.availability,
        ),
        ActionSpec(
            id="shell.run",
            label=_("Run a command"),
            category=Category.PERSONALIZADO,
            description=_("Runs a command line; the escape hatch for whatever the catalogue misses"),
            parameters=(Parameter("command", _("Command line"), kind="command"),),
            run=lambda context: launch.run_command(context.require("command")),
        ),
    ]


def build() -> Registry:
    """Monta o catálogo padrão."""
    registry = Registry()
    for spec in _specs():
        registry.register(spec)
    return registry
