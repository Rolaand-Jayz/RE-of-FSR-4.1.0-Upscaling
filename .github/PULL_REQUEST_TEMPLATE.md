## What this changes

<!-- One or two sentences. -->

## Checklist

- [ ] Claims carry evidence tags (STATIC-REPRODUCIBLE, STATIC-INFERRED, PLAUSIBILITY-CHECK, RUNTIME-NOT-OBSERVED, BOUNDED-REBUILD).
- [ ] No claim is moved toward runtime-observed without a capture that meets `runtime-validation/README.md`.
- [ ] Legal boundaries in `LEGAL.md` are respected: no AMD binaries, decompiled or disassembled AMD source, extracted data, or NDA material.
- [ ] `claims.json`, `CURRENT_STATUS.md`, and `VALIDATION_STATUS.md` agree if a claim's status or confidence changed.
- [ ] `REPRODUCING.md` is updated if commands, inputs, or expected outputs changed.
- [ ] Failed and negative results are kept, not deleted or rewritten.
- [ ] `make verify-public` passes locally.
