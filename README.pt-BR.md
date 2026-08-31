<h1 align="center">logi-tune-linux</h1>

<p align="center">
  <strong>Seu MX Master 4, totalmente configurável no Linux.</strong><br>
  Uma alternativa livre ao Logi Options+ — incluindo o motor háptico e o botão
  do Actions Ring, que nenhuma outra ferramenta Linux alcança.
</p>

<p align="center">
  <a href="LICENSE"><img alt="Licença: GPL v3" src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
  <a href="https://github.com/renangraciano/logi-tune-linux/actions/workflows/tests.yml"><img alt="Testes" src="https://github.com/renangraciano/logi-tune-linux/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="Plataforma" src="https://img.shields.io/badge/platform-Linux-lightgrey">
</p>

<p align="center">
  <a href="README.md">🇬🇧 Read in English</a>
</p>

<p align="center">
  <img src="docs/screenshot.png" alt="logi-tune-linux configurando um MX Master 4" width="420">
</p>

---

A Logitech publica o Options+ para Windows e macOS. No Linux, nada — sem
controle de DPI, sem SmartShift, sem remapeamento de botões e sem nenhum dos
recursos novos do MX Master 4.

Este projeto fala **HID++ 2.0 direto com `/dev/hidraw`**. Sem Solaar, sem
logiops, sem root.

## O que funciona

Tudo abaixo foi verificado em hardware real: um MX Master 4 (WPID `B042`,
firmware `RBM 27.03.B0019`) por receptor Bolt, Ubuntu 24.04.4, GNOME 46, X11.

| | Recurso | HID++ |
| --- | --- | --- |
| ✅ | Nível de bateria e estado de carga | `0x1004` |
| ✅ | Sensibilidade do ponteiro (200–8000 DPI) | `0x2201` |
| ✅ | Ponto de virada do SmartShift e modo da roda | `0x2111` |
| ✅ | Rolagem de alta resolução e inversão | `0x2121` |
| ✅ | Direção da roda do polegar | `0x2150` |
| ✅ | Remapeamento e desvio de botões | `0x1B04` |
| ✅ | Easy-Switch entre três computadores | `0x1814` `0x1815` |
| ✅ | **Feedback háptico — 15 padrões** | `0x19B0` |
| ✅ | Perfis por aplicação (X11) | — |
| 🚧 | Menu radial do Actions Ring | `0x01A0` |

## Duas coisas que você não encontra em outro lugar

**O motor háptico funciona.** A feature `0x19B0` não era documentada. A sondagem
do hardware estabeleceu que a função `0x04` toca um padrão de vibração, que os
índices 0–14 são aceitos e que 15 em diante são recusados com
`INVALID_ARGUMENT`:

```bash
logitune haptic --all
```

**O botão do Actions Ring é alcançável.** O MX Master 4 trouxe um botão que não
existe em nenhum modelo anterior — controle `0x01A0`, tarefa `0x0109`. Ele é
remapeável e desviável, então já dá para ligá-lo a qualquer ação:

```bash
logitune watch 0x01A0     # veja o evento chegar ao apertar o botão
```

Entre o botão e o motor, as duas metades de hardware do Actions Ring estão
resolvidas. Falta desenhar o menu radial — veja o [roadmap](#roadmap).

## Instalação

```bash
# Dependências (python3-xlib só é necessário para perfis por aplicação)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-xlib pipx

# Acesso ao dispositivo sem root
sudo cp packaging/udev/70-logitune.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# Instalação. O --system-site-packages deixa o ambiente isolado enxergar o
# PyGObject que a interface GTK usa, instalado pelo apt no sistema.
pipx install --system-site-packages .
```

Desconecte e reconecte o receptor depois de instalar a regra udev.

> **Por que pipx?** O Ubuntu 24.04 e outras distribuições recentes marcam o
> Python do sistema como gerenciado externamente
> ([PEP 668](https://peps.python.org/pep-0668/)), então `pip install --user` se
> recusa a rodar. O pipx dá um ambiente próprio a cada aplicação e coloca
> `logitune`, `logitune-gui` e `logitune-daemon` no seu `PATH`. Se
> `~/.local/bin` não estiver no `PATH`, rode `pipx ensurepath` e abra um
> terminal novo.

## Uso

```bash
logitune                      # resumo
logitune dpi 1600             # sensibilidade do ponteiro
logitune smartshift 40        # ponto de virada do ratchet
logitune scroll --invert
logitune buttons              # lista os controles e seus mapeamentos
logitune button voltar --remap 0x0052
logitune hosts                # computadores pareados
logitune host 2               # move o mouse para o canal 2
logitune haptic 3             # toca um padrão de vibração
logitune-gui                  # interface gráfica
```

### Perfis por aplicação

O daemon observa a janela em foco e reconfigura o mouse conforme você troca de
aplicativo — um DPI menor no navegador, a roda travada no editor.

```bash
logitune-daemon --write-example   # cria ~/.config/logitune/config.json
cp packaging/systemd/logitune-daemon.service ~/.config/systemd/user/
systemctl --user enable --now logitune-daemon
```

```json
{
  "default": { "dpi": 2800, "smartshift": 32 },
  "profiles": [
    {
      "name": "Navegador",
      "match": { "wm_class": ["firefox", "brave", "chrome"] },
      "settings": { "dpi": 2000 }
    },
    {
      "name": "Editor",
      "match": { "wm_class": ["code"] },
      "settings": {
        "dpi": 3200,
        "ratchet": true,
        "actions": { "0x01A0": "xdotool key super" }
      }
    }
  ]
}
```

`buttons` remapeia um controle no firmware; `actions` desvia o botão para que o
daemon execute um comando. Os botões desviados são restaurados quando o daemon
encerra.

O daemon fica bloqueado em `select` sobre os descritores do X e do hidraw — sem
polling e sem consumo de CPU em repouso.

## Comparação

| | logi-tune-linux | Solaar | logiops |
| --- | --- | --- | --- |
| Conhece o MX Master 4 | ✅ | parcialmente | ❌ (`B042` sem suporte na 0.3.3) |
| Feedback háptico | ✅ | ❌ | ❌ |
| Botão do Actions Ring | ✅ | aparece como desconhecido | ❌ |
| Roda sem root | ✅ | ✅ | ❌ |
| Perfis por aplicação | ✅ | ❌ | ✅ |
| Lê o estado de volta (bateria, DPI) | ✅ | ✅ | ❌ |
| Escopo | um dispositivo, bem feito | toda a linha Logitech | remapeamento de botões |

O Solaar é um projeto excelente e o trabalho de engenharia reversa dele embasou
partes deste protocolo. A proposta aqui é outra: reproduzir a experiência do
Options+ para um mouse específico, incluindo hardware que nada no Linux suporta.

## Engenharia reversa

O MX Master 4 anuncia 46 features HID++. Estas não constam na documentação
pública:

| Feature | Situação |
| --- | --- |
| `0x19B0` | **motor háptico** — decifrada, veja [docs/haptic-waveforms.md](docs/haptic-waveforms.md) |
| `0x19C0` | responde às funções `0x00`–`0x02`; os valores variam entre leituras, o que sugere sensor |
| `0x1701` | não decifrada |
| `0x00D1` | não decifrada |

Também corrigido no caminho: na feature `0x1815`, `getHostFriendlyName` é a
função `0x03`, não a `0x02` — a `0x02` devolve um identificador do host.

```bash
logitune features    # tabela completa de features HID++
logitune watch       # desvia botões e mostra os eventos que eles emitem
```

## Roadmap

- [ ] Menu radial do Actions Ring via extensão do GNOME Shell
- [ ] Perfis por aplicação no Wayland (a mesma extensão resolve os dois)
- [ ] Decifrar `0x19C0`
- [ ] Interface em inglês
- [ ] Pacotes Flatpak e `.deb`
- [ ] Suporte além do MX Master 4 — a pilha é HID++ 2.0 genérica, falta testar

## Limitações conhecidas

- **Wayland**: o protocolo não deixa um aplicativo comum saber qual janela está
  em foco, então os perfis por aplicação ficam desativados. O resto funciona
  normalmente, e o daemon avisa ao iniciar.
- **Rodar junto com o Solaar** funciona, mas os dois escrevem no mesmo
  dispositivo e podem desfazer os ajustes um do outro. Use um de cada vez.
- **O modo da roda é volátil**: com o SmartShift ativo, o firmware alterna entre
  ratchet e roda livre sozinho. Forçar um modo vale até a próxima rolagem
  rápida.
- Testado apenas com o MX Master 4 por receptor Bolt.

## Contribuindo

Relatos de dispositivo são a contribuição mais valiosa — `logitune features` e
`logitune buttons` de um mouse que ainda não vimos descrevem toda a superfície
HID++ dele. Veja o [CONTRIBUTING.md](CONTRIBUTING.md).

## Licença

[GPL-3.0-or-later](LICENSE).
