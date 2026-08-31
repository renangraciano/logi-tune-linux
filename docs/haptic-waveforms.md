# MX Master 4 haptic waveforms

HID++ feature `0x19B0`, function `0x04` (`playWaveform`). The firmware accepts
indices **0 through 14** and rejects 15 and above with `INVALID_ARGUMENT`.

`getCapabilities` (function `0x00`) returns `00 01 00 3c 08 00 7f ff` on
firmware `RBM 27.03.B0019`. The meaning of those fields is not established yet,
so the code keeps the raw bytes rather than pretending to decode them.

## How each pattern feels

A haptic motor cannot be characterised in software — only someone with a hand
on the mouse can tell a short tick from a long buzz. Build this table with:

```bash
logitune haptic --catalog -o docs/haptic-waveforms.md
```

It plays each pattern in turn, asks you to describe it, and writes the table
back here.

| Pattern | Feel |
| --- | --- |
| `0` | *to be catalogued* |
| `1` | *to be catalogued* |
| `2` | *to be catalogued* |
| `3` | *to be catalogued* |
| `4` | *to be catalogued* |
| `5` | *to be catalogued* |
| `6` | *to be catalogued* |
| `7` | *to be catalogued* |
| `8` | *to be catalogued* |
| `9` | *to be catalogued* |
| `10` | *to be catalogued* |
| `11` | *to be catalogued* |
| `12` | *to be catalogued* |
| `13` | *to be catalogued* |
| `14` | *to be catalogued* |

Knowing which pattern is which matters for the Actions Ring: a short tick suits
moving between items, a stronger one suits confirming a selection.
