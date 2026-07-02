# Release Notes

This release is a **static reverse-engineering evidence bundle** for AMD's FidelityFX Super Resolution 4.1.0 temporal upscaler. It documents what static analysis can reveal about a closed-source neural network DLL — extracted weights, shader/pass catalogs, data-layout reconstruction, and provider-DLL dispatch analysis.

## Included

- Extracted weight blob hashes and committed research blobs (6 presets, 131,072 bytes each)
- DXIL inventory (27 model-family entrypoints, 602 shader blobs cataloged)
- Static provider dispatch analysis (27-iteration loop, optional SPD/RCAS/Debug passes)
- Static resource binding artifacts (9 register spaces, per-pass UAV/CBV/SRV layouts)
- Bounded data-DLL rebuild comparison (per-section hash comparison, no byte-equality claim)
- Verification suite (schema v4, categorized by evidence strength)
- Machine-readable claim registry (`claims.json`) with confidence values

## Not Included

- Native D3D12 runtime capture (all three Linux/Proton capture methods failed)
- Functional equivalence proof (not claimed, not tested)
- Replacement DLL (not a drop-in replacement)
- Frame generation analysis (out of scope; upscaler only)
- Complete per-instruction decode of every arithmetic operation

## Claim Ceiling

This release proves **static extraction and static structural analysis only.**

It does not prove runtime pass order, runtime descriptor bindings, runtime CBV values, runtime tensor offset use, functional equivalence to AMD's DLL, or deployability as a replacement implementation.

See `CURRENT_STATUS.md` for the one-glance truth table and `claims.json` for machine-queryable confidence values.
