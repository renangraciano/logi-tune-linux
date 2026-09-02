# SPDX-License-Identifier: GPL-3.0-or-later
"""Todo ajuste do mouse tem que passar pela configuração.

Escrever direto no dispositivo parece funcionar e não funciona: o daemon
reaplica o perfil a cada troca de janela, então o valor volta atrás no
primeiro aplicativo que ganha o foco. Foi assim que o limiar do SmartShift
"não salvava" — a janela escrevia no mouse e não gravava nada.

O teste lê o código em vez de abrir a janela: o CI não tem PyGObject, e é
justamente lá que a regressão precisa ser barrada.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

JANELA = Path(__file__).resolve().parent.parent / "logitune" / "ui" / "window.py"

#: Os manipuladores que mexem em algo guardado no ``config.json``, com o campo
#: de ``Settings`` que cada um alimenta.
HANDLERS = {
    "_on_dpi_changed": "dpi",
    "_on_smartshift_changed": "smartshift",
    "_on_ratchet_toggled": "ratchet",
    "_on_hires_toggled": "hires_scroll",
    "_on_invert_toggled": "invert_scroll",
    "_on_thumb_toggled": "invert_thumb",
}


@pytest.fixture(scope="module")
def metodos() -> dict[str, ast.FunctionDef]:
    arvore = ast.parse(JANELA.read_text(encoding="utf-8"))
    return {
        no.name: no
        for no in ast.walk(arvore)
        if isinstance(no, ast.FunctionDef)
    }


def _chamadas(no: ast.AST) -> set[str]:
    """Os atributos de ``self`` chamados dentro de um nó."""
    nomes = set()
    for filho in ast.walk(no):
        if (
            isinstance(filho, ast.Call)
            and isinstance(filho.func, ast.Attribute)
            and isinstance(filho.func.value, ast.Name)
            and filho.func.value.id == "self"
        ):
            nomes.add(filho.func.attr)
    return nomes


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_o_ajuste_vai_para_a_configuracao(metodos, handler):
    assert handler in metodos, f"{handler} sumiu de window.py"
    assert "_write_setting" in _chamadas(metodos[handler]), (
        f"{handler} não grava na configuração; o daemon vai desfazer o ajuste "
        "na próxima troca de janela"
    )


@pytest.mark.parametrize("handler,campo", sorted(HANDLERS.items()))
def test_grava_no_campo_certo(metodos, handler, campo):
    """Trocar dois campos de lugar salvaria, e salvaria a coisa errada."""
    fonte = ast.unparse(metodos[handler])
    assert f"'{campo}'" in fonte or f'"{campo}"' in fonte, (
        f"{handler} deveria alimentar o campo {campo!r} de Settings"
    )


def test_todo_campo_de_ajuste_tem_manipulador():
    """Um campo novo em Settings precisa de uma linha que o grave."""
    from logitune.config import Settings

    do_dispositivo = {
        "dpi", "smartshift", "ratchet",
        "invert_scroll", "hires_scroll", "invert_thumb",
    }
    assert do_dispositivo <= set(Settings().__dict__), (
        "um campo de ajuste do mouse saiu de Settings"
    )
    assert set(HANDLERS.values()) == do_dispositivo


def test_a_troca_de_perfil_recarrega_as_linhas(metodos):
    """Sem isso as abas de perfil mostrariam sempre os valores do global."""
    chamadas = _chamadas(metodos["_on_profile_toggled"])
    assert "_refresh_setting_rows" in chamadas
    assert "_refresh_group_scopes" in chamadas
    assert "_refresh_all_button_rows" in chamadas
