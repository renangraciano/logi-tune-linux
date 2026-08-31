## What this changes

<!-- Describe the change and, above all, why it is needed. -->

## How it was tested

<!--
Most of this project talks to physical hardware, so this section carries real
weight. Tick what applies and add detail.
-->

- [ ] `pytest` passes
- [ ] Tested against a real device — model, firmware and connection:
      <!-- e.g. MX Master 4, RBM 27.03.B0019, Bolt receiver -->
- [ ] Tested the GTK interface
- [ ] Tested the daemon
- [ ] Not applicable (documentation, CI, refactor with no behaviour change)

**If this writes to a device**, describe how you confirmed the setting applied
and that the previous state could be restored.

## Checklist

- [ ] The PR title follows [Conventional Commits](https://www.conventionalcommits.org/)
- [ ] New behaviour is covered by tests, or there is a reason it cannot be
- [ ] Undocumented HID++ findings record the raw bytes and the firmware version
- [ ] Docs updated if the user-facing behaviour changed

## Related issues

<!-- Closes #123 -->
