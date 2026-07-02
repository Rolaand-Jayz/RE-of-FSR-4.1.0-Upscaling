# Adversarial Review #2 — Resolution

**Date:** 2026-07-01
**Scope:** Map each issue raised in `docs/adversarial-review-2.md` to the exact wording fix and files changed.

This document is a traceability record. Every issue below was addressed by weakening the original claim to the strength the evidence supports, not by adding new evidence. No issue was dismissed.

## Issue Resolution Table

| Issue | Finding (from adversarial review) | Resolution | Files Changed |
|---|---|---|---|
| 1 | "atomicCompareExchange is a LUT lookup" asserted as a confirmed mechanism | Wording changed from "is" to "appears to function as" a side-effect-free table read | `docs/shader-internals.md` |
| 2 | Kernel sizes (3x3 / 4x4 / 5x4) stated as extracted dimensions | Wording changed from "are" to "consistent with" the phi-node counts | `docs/IMPLEMENTATION_GUIDE.md` |
| 3 | "No attention mechanism" stated as a proven negative | Wording changed to "attention cannot be ruled out" | `docs/shader-internals.md`, `reports/architecture-map-v410.md` |
| 4 | "U-Net-like architecture" asserted without skip-connection evidence | Wording changed to "bottleneck architecture with symmetric pass structure" | `docs/architecture.md`, `docs/shader-internals.md` |
| 5 (circular proof) | Historical patcher copied original bytes into output before hashing; MD5 equality was circular | Patching behavior removed; tool now reports per-section hashes/differences without copying original bytes. Historical patched artifact retained only as a non-proof artifact | `rebuild/pe_patcher.py`, `rebuild/README.md`, `rebuild/run_rebuild_section_comparison.sh` |

## Circular-Proof Resolution (Issue 5), Detail

The earlier data-DLL rebuild claimed hash equality as proof of independent reconstruction. That equality was circular: the tool copied differing sections, headers, and overlay bytes from the original DLL into the rebuilt file before hashing. An identical hash was therefore inevitable and established nothing about an independent rebuild.

Resolution applied:
- `rebuild/pe_patcher.py` no longer copies original bytes. It compares an independently built DLL against the original and emits per-region hashes and byte differences (section-comparison behavior).
- ~~`rebuild/fsr_data_final.dll`~~ — removed from repo. It was the original AMD binary redistributed under a different name. The hash (`cb1aa61c71c33b25549ed59c1551d661`) is retained in `rebuild/README.md` for reference.
- `scripts/validate_claims.py` enforces this forward: it scans all text files for overclaim language and fails CI on matches. New documentation files are scanned with no allowlist.

## Caveats Acknowledged but Not Closed

The adversarial review also raised two caveats that remain open because they require runtime data this project does not have:

1. **Prepass variant count (90 variants).** Why so many variants exist for a single pass type is not explained. No additional static analysis resolved it.
2. **"no_scale" designation.** FP8 E4M3/E5M2 use per-value exponents. "no_scale" likely means no separate scale tensor rather than a shared exponent. This interpretation is noted but not confirmed.

These remain documented gaps. They are not closed by rewording; closing them requires runtime capture or further static analysis.
