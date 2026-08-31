# MX Master 4 haptic waveforms

HID++ feature `0x19B0`. Undocumented by Logitech; everything here was
established by probing the hardware, on firmware `RBM 27.03.B0019`.

## Function surface

| Function | Name | Behaviour |
| --- | --- | --- |
| `0x00` | getCapabilities | returns `00 01 00 3c 08 00 7f ff` |
| `0x01` | (status) | returns `01 3c 00 …` |
| `0x02` | unknown | rejects every argument tried so far with `INVALID_ARGUMENT` |
| `0x03` | unknown | always returns zeroes |
| `0x04` | playWaveform | plays a pattern; echoes the index back |
| `0x05`+ | — | `INVALID_FUNCTION_ID`, so the feature has exactly five functions |

`playWaveform` accepts indices **0–14** and rejects 15 and above with
`INVALID_ARGUMENT`.

**It takes only the pattern index.** Sending extra bytes — plausible amplitude
and duration values drawn from `getCapabilities`, where `7f ff` looks like a
maximum amplitude and `00 3c` like a duration — produces a byte-identical
response, so the firmware ignores them. The patterns are fixed; there is no
amplitude or duration control on this function.

The fields of `getCapabilities` remain undecoded, so the code keeps the raw
bytes rather than inventing a layout.

## The patterns

Catalogued by hand on an MX Master 4 — a haptic motor cannot be characterised
in software. Rebuild this table on your own device with:

```bash
logitune haptic --catalog -o docs/haptic-waveforms.md
```

| Pattern | Feel | Family |
| --- | --- | --- |
| `0` | short | tick |
| `1` | short | tick |
| `2` | click | click |
| `3` | click | click |
| `4` | soft click | click |
| `5` | click with light vibration | click |
| `6` | light vibration | vibration |
| `7` | multi-click vibration | multi-click |
| `8` | multi-click vibration | multi-click |
| `9` | multi-click vibration | multi-click |
| `10` | multi-click vibration | multi-click |
| `11` | fast multi-click vibration | multi-click |
| `12` | slow multi-click vibration | multi-click |
| `13` | slow musical vibration | extended |
| `14` | phone-style buzz | extended |

The patterns fall into four families of increasing length, and within the
multi-click family (`7`–`10`) the differences are subtle enough to be hard to
tell apart by hand.

## Choosing a pattern

For the Actions Ring, and for feedback generally:

| Purpose | Suggested | Why |
| --- | --- | --- |
| Moving between menu items | `0` or `1` | short enough to fire repeatedly without becoming noise |
| Confirming a selection | `2` or `3` | a distinct click reads as "done" |
| Rejecting an action, hitting a limit | `6` | a buzz reads differently from a click |
| Notification, mode change | `14` | long enough to notice away from the task |

Avoid the multi-click family for anything that repeats quickly: the patterns
are long enough to overlap and are hard to tell apart.
