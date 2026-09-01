# SPDX-License-Identifier: GPL-3.0-or-later
"""Como cada tipo de ação acontece de fato.

Escolhemos a API nativa sempre que existe uma, e só caímos na síntese de
teclas quando o alvo é o aplicativo em foco. Isso não é preciosismo: mídia por
MPRIS funciona com a janela minimizada, volume por PipeWire funciona sem
compositor, e nenhum dos dois depende da regra udev do ``uinput``. A síntese
fica reservada para copiar, colar, trocar de aba — coisas que só o aplicativo
em foco sabe fazer.
"""
