# logi-tune-linux

Personalização de mouses Logitech no Linux — uma alternativa livre ao
**Logi Options+** / **Logi Tune**, que a Logitech só publica para Windows e macOS.

O foco inicial é o **MX Master 4** no **Ubuntu 24.04 LTS**.

## Estado atual

Tudo abaixo foi verificado em hardware real (MX Master 4, firmware `RBM 27.03.B0019`,
conectado por receptor Bolt):

| Recurso | Estado |
| --- | --- |
| Bateria (nível, carga, notificação) | funcionando |
| Sensibilidade / DPI | funcionando |
| SmartShift e modo da roda | funcionando |
| Rolagem de alta resolução e inversão | funcionando |
| Roda do polegar (direção, desvio) | funcionando |
| Remapeamento dos botões | funcionando |
| Troca de computador (Easy-Switch) | funcionando |
| Perfis por aplicação | funcionando (X11) |
| Interface gráfica GTK4 | funcionando |
| Actions Ring | botão identificado, ação pendente |
| Feedback háptico | não implementado |

## Por que não usar logiops ou Solaar

- **logiops / logid** (0.3.3, o que vem no Ubuntu 24.04) não conhece o MX Master 4
  (WPID `B042`), roda como root, é configurado por arquivo sem introspecção e não
  devolve nada para a interface — não dá para ler bateria ou DPI atual.
- **Solaar** é excelente e foi a referência para partes deste protocolo, mas é uma
  ferramenta genérica para toda a linha Logitech. Aqui a proposta é diferente:
  reproduzir a experiência do Logi Options+ para um mouse específico, incluindo os
  recursos novos que ainda não existem em lugar nenhum no Linux.

Este projeto implementa a pilha **HID++ 2.0 do zero**, falando direto com
`/dev/hidraw`. Sem dependência de daemon externo e sem privilégio de root.

## Instalação

### Dependências

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-xlib
```

`python3-xlib` só é necessário para os perfis por aplicação.

### Regras udev

Sem elas, `/dev/hidraw*` pertence ao root e a ferramenta não enxerga o mouse:

```bash
sudo cp packaging/udev/70-logitune.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Desconecte e reconecte o receptor depois disso.

### O pacote

```bash
pip install --user .
```

## Uso

### Linha de comando

```bash
logitune                      # resumo do dispositivo
logitune dpi 1600             # define a sensibilidade
logitune smartshift 40        # ponto de virada do ratchet
logitune scroll --invert      # inverte a roda principal
logitune scroll --no-invert-thumb
logitune buttons              # lista os botões e seus mapeamentos
logitune button voltar --remap 0x0052
logitune button voltar --reset
logitune hosts                # computadores pareados
logitune host 2               # move o mouse para o canal 2
logitune watch                # mostra os eventos dos botões desviados
logitune features             # despeja a tabela HID++ (engenharia reversa)
```

Exemplo de saída:

```
MX Master 4 (receptor)
  Bateria      ██████████░░░░░░░░░░ 50% (descarregando)
  Sensibilidade 2800 DPI (padrão 1000, faixa 200–8000)
  SmartShift   modo roda livre, ponto de virada 32 (padrão 70)
  Roda         resolução normal
  Roda polegar invertida, desviada
  Host ativo   canal 1 (receptor Bolt)
```

### Interface gráfica

```bash
logitune-gui
```

### Daemon e perfis por aplicação

```bash
logitune-daemon --write-example   # cria ~/.config/logitune/config.json
logitune-daemon                   # roda em primeiro plano
```

Para deixar ativo na sessão:

```bash
cp packaging/systemd/logitune-daemon.service ~/.config/systemd/user/
systemctl --user enable --now logitune-daemon
```

O daemon fica bloqueado em `select` sobre o descritor do X e o do hidraw — não
faz polling e não consome CPU em repouso.

#### Configuração

```json
{
  "version": 1,
  "default": {
    "dpi": 2800,
    "smartshift": 32,
    "invert_thumb": true
  },
  "profiles": [
    {
      "name": "Navegador",
      "match": { "wm_class": ["firefox", "brave", "chrome"] },
      "settings": { "dpi": 2000 }
    },
    {
      "name": "Editor de código",
      "match": { "wm_class": ["code"] },
      "settings": {
        "dpi": 3200,
        "ratchet": true,
        "buttons": { "0x0053": "0x0052" },
        "actions": { "0x01A0": "xdotool key super" }
      }
    }
  ]
}
```

- `match` aceita `wm_class` e `title`; ambos casam por trecho, sem diferenciar
  maiúsculas. Se os dois estiverem presentes, os dois precisam casar.
- `buttons` remapeia um botão para o papel de outro, no próprio firmware.
- `actions` **desvia** um botão: ele deixa de gerar o clique normal e passa a
  executar o comando indicado. O daemon restaura os botões desviados ao sair.

Descubra os CIDs com `logitune buttons`.

## O que foi descoberto sobre o MX Master 4

O mouse anuncia 46 features HID++. Além das conhecidas, aparecem estas, que
nenhuma ferramenta Linux documenta:

| Feature | Observação |
| --- | --- |
| `0x19B0` | não documentada, exclusiva do MX Master 4 |
| `0x19C0` | não documentada, exclusiva do MX Master 4 |
| `0x1701` | não documentada |
| `0x00D1` | não documentada |

E um botão que não existe em nenhum modelo anterior:

| Control ID | Task ID | Rótulo |
| --- | --- | --- |
| `0x01A0` | `0x0109` | botão do **Actions Ring** |

Ele é **remapeável e desviável** (grupo 2, máscara `0x03`), o que significa que já
dá para capturá-lo no Linux hoje e ligar a qualquer ação:

```bash
logitune watch 0x01A0          # veja o evento chegar ao apertar o botão
```

Reproduzir o menu radial e o feedback háptico depende de decifrar `0x19B0`/`0x19C0`
— é o próximo passo do projeto.

## Limitações conhecidas

- **Wayland**: os perfis por aplicação exigem saber qual janela está em foco, e o
  Wayland não expõe isso a um aplicativo comum. Numa sessão Wayland o daemon avisa
  e roda apenas com o perfil padrão; o resto funciona normalmente. Uma extensão do
  GNOME resolveria isso.
- **Rodar junto com o Solaar** funciona (o kernel entrega os relatórios a cada
  leitor separadamente), mas os dois escrevem no mesmo dispositivo e podem
  desfazer os ajustes um do outro. Durante o desenvolvimento observamos o Solaar
  reescrevendo o nome do host enquanto líamos. Recomendado usar um de cada vez.
- **O modo da roda é volátil**: com o SmartShift ativo, o firmware alterna entre
  ratchet e roda livre conforme a velocidade da rolagem. Forçar um modo vale até a
  próxima rolagem rápida.
- Testado apenas com o MX Master 4 via receptor Bolt. A pilha é genérica e deve
  funcionar com outros mouses HID++ 2.0, mas isso não foi verificado.

## Desenvolvimento

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Os testes usam um transporte falso que simula um dispositivo HID++, então rodam
sem hardware.

### Organização

```
logitune/
├── hidpp/            pilha do protocolo HID++ 2.0
│   ├── transport.py    descoberta e E/S em /dev/hidraw
│   ├── device.py       features, chamadas e erros
│   ├── notifications.py eventos assíncronos do dispositivo
│   └── features/       uma feature por arquivo (0x2201, 0x1B04, …)
├── device.py         fachada de alto nível
├── config.py         perfis
├── daemon/           serviço: foco de janela e botões desviados
├── ui/               interface GTK4 + libadwaita
└── cli.py            linha de comando
```

## Créditos

O trabalho de engenharia reversa do projeto [Solaar](https://github.com/pwr-Solaar/Solaar)
e a especificação pública HID++ 2.0 da Logitech foram a base para entender o
protocolo.

## Licença

GPL-2.0-or-later.
