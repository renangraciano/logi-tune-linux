#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Monta o .deb a partir do wheel.
#
# Não usamos dh-python nem pybuild de propósito: o pacote é Python puro, o
# wheel já é a única fonte da verdade sobre o que entra nele, e descompactá-lo
# num diretório de montagem é mais fácil de conferir do que uma cadeia de
# debhelper. O preço é que este script precisa saber onde cada coisa mora no
# sistema — que é o que os comentários abaixo explicam.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

PACOTE="logi-tune-linux"
DESTINO="${1:-dist}"

versao_python() {
  python3 - <<'PY'
import pathlib, re
print(re.search(r'__version__ = "([^"]+)"',
                pathlib.Path("logitune/__init__.py").read_text()).group(1))
PY
}

# A conversão mora em deb_version.py, onde os testes a alcançam: o PEP 440
# escreve "0.2.0rc1" e o dpkg compara isso como maior que "0.2.0", então uma
# pré-release pareceria mais nova que a versão final.
versao_debian() {
  python3 "$RAIZ/scripts/deb_version.py" "$1"
}

VERSAO="$(versao_python)"
VERSAO_DEB="$(versao_debian "$VERSAO")"
MONTAGEM="$(mktemp -d)"
trap 'rm -rf "$MONTAGEM"' EXIT

echo "==> ${PACOTE} ${VERSAO} (Debian: ${VERSAO_DEB})"

# -- 1. o wheel ---------------------------------------------------------
# Vem do build normal, então carrega os catálogos compilados pelo setup.py.
echo "==> construindo o wheel"
rm -rf build "${DESTINO:?}"/*.whl
python3 -m build --wheel --outdir "$DESTINO" >/dev/null
WHEEL="$(ls -t "$DESTINO"/*.whl | head -1)"
echo "    $WHEEL"

# -- 2. o Python ---------------------------------------------------------
# /usr/lib/python3/dist-packages é o diretório que o Python do sistema lê em
# qualquer versão do interpretador; o pip escreveria em site-packages de uma
# versão específica, que não está no caminho no Debian nem no Ubuntu.
ARVORE="$MONTAGEM/usr/lib/python3/dist-packages"
mkdir -p "$ARVORE"
python3 -m zipfile -e "$WHEEL" "$ARVORE"
rm -rf "$ARVORE"/*.dist-info/RECORD

# -- 3. os comandos ------------------------------------------------------
# Escritos aqui em vez de aproveitados do wheel: os do pip trazem o caminho
# absoluto do Python que construiu o pacote, que não existe na máquina de
# quem instala.
mkdir -p "$MONTAGEM/usr/bin"
escrever_comando() {
  local nome="$1" modulo="$2" funcao="$3"
  cat > "$MONTAGEM/usr/bin/$nome" <<EOF
#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
import sys

from $modulo import $funcao

if __name__ == "__main__":
    sys.exit($funcao())
EOF
  chmod 755 "$MONTAGEM/usr/bin/$nome"
}
escrever_comando logitune        logitune.cli            main
escrever_comando logitune-daemon logitune.daemon.service main
escrever_comando logitune-gui    logitune.ui.app         main

# -- 4. regra udev, unidade, entrada de menu e ícone ---------------------
install -Dm644 packaging/udev/70-logitune.rules \
  "$MONTAGEM/usr/lib/udev/rules.d/70-logitune.rules"

# A unidade do repositório aponta para ~/.local/bin, que é onde o pipx põe os
# comandos. Num pacote eles ficam em /usr/bin, e o systemd exige caminho
# absoluto — não há como uma única linha servir aos dois casos.
mkdir -p "$MONTAGEM/usr/lib/systemd/user"
sed 's|ExecStart=%h/\.local/bin/logitune-daemon|ExecStart=/usr/bin/logitune-daemon|' \
  packaging/systemd/logitune-daemon.service \
  > "$MONTAGEM/usr/lib/systemd/user/logitune-daemon.service"
if ! grep -q '^ExecStart=/usr/bin/logitune-daemon$' \
     "$MONTAGEM/usr/lib/systemd/user/logitune-daemon.service"; then
  echo "erro: não consegui reescrever o ExecStart da unidade" >&2
  exit 1
fi
chmod 644 "$MONTAGEM/usr/lib/systemd/user/logitune-daemon.service"

install -Dm644 packaging/desktop/io.github.renangraciano.LogiTuneLinux.desktop \
  "$MONTAGEM/usr/share/applications/io.github.renangraciano.LogiTuneLinux.desktop"
install -Dm644 packaging/icons/io.github.renangraciano.LogiTuneLinux.svg \
  "$MONTAGEM/usr/share/icons/hicolor/scalable/apps/io.github.renangraciano.LogiTuneLinux.svg"

# -- 5. documentação exigida pela política --------------------------------
DOC="$MONTAGEM/usr/share/doc/$PACOTE"
mkdir -p "$DOC"
install -m644 README.md "$DOC/README.md"
install -m644 README.pt-BR.md "$DOC/README.pt-BR.md"
sed -n '1,200p' CHANGELOG.md | gzip -9n > "$DOC/changelog.gz"
cat > "$DOC/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: logi-tune-linux
Source: https://github.com/renangraciano/logi-tune-linux

Files: *
Copyright: 2026 Renan Graciano de Souza
License: GPL-3.0-or-later
 This program is free software: you can redistribute it and/or modify it
 under the terms of the GNU General Public License as published by the Free
 Software Foundation, either version 3 of the License, or (at your option)
 any later version.
 .
 This program is distributed in the hope that it will be useful, but WITHOUT
 ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
 more details.
 .
 On Debian systems the full text of the GNU General Public License version 3
 can be found in /usr/share/common-licenses/GPL-3.
EOF

# -- 6. metadados do pacote ----------------------------------------------
TAMANHO="$(du -ks "$MONTAGEM" | cut -f1)"
mkdir -p "$MONTAGEM/DEBIAN"
cat > "$MONTAGEM/DEBIAN/control" <<EOF
Package: $PACOTE
Version: $VERSAO_DEB
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1
Recommends: python3-evdev, python3-xlib
Suggests: gettext
Installed-Size: $TAMANHO
Maintainer: Renan Graciano de Souza <graccciano@gmail.com>
Homepage: https://github.com/renangraciano/logi-tune-linux
Description: Configure Logitech MX Master mice on Linux
 An open alternative to Logi Options+ for the MX Master 4, speaking HID++ 2.0
 straight to /dev/hidraw with no root and no other daemon in the way.
 .
 Sets pointer sensitivity, SmartShift, scrolling and Easy-Switch; binds any of
 53 actions to a button; reaches the haptic motor and the Actions Ring button
 that no other Linux tool supports; and applies a different profile per
 application.
 .
 python3-evdev is needed only for the actions that synthesise key presses, and
 python3-xlib only for per-application profiles, which is why both are
 recommended rather than required.
EOF

cat > "$MONTAGEM/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    # A regra dá acesso ao mouse sem root. Ela só passa a valer para um
    # aparelho já conectado depois de reconectá-lo, e o acesso ao uinput
    # depende de uma ACL concedida no login.
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules >/dev/null 2>&1 || true
        udevadm trigger --subsystem-match=hidraw >/dev/null 2>&1 || true
    fi

    cat <<'AVISO'

logi-tune-linux instalado. Faltam dois passos que só você pode dar:

  1. Reconecte o receptor (ou o mouse) para a regra udev valer, e faça
     logout/login para o acesso ao /dev/uinput.
  2. Ligue o serviço de usuário, que é quem aplica ações e perfis:

       systemctl --user enable --now logitune-daemon

  Depois, "logitune doctor" confere cada passo e diz o que falta.

AVISO
fi

exit 0
EOF
chmod 755 "$MONTAGEM/DEBIAN/postinst"

cat > "$MONTAGEM/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules >/dev/null 2>&1 || true
    fi
fi

exit 0
EOF
chmod 755 "$MONTAGEM/DEBIAN/postrm"

# -- 7. montar -----------------------------------------------------------
mkdir -p "$DESTINO"
ARQUIVO="$DESTINO/${PACOTE}_${VERSAO_DEB}_all.deb"
dpkg-deb --root-owner-group --build "$MONTAGEM" "$ARQUIVO" >/dev/null
echo "==> $ARQUIVO"
dpkg-deb --info "$ARQUIVO" | sed -n '2,12p'
