# Section Comparison Explainer

## What This Is

`section-comparison.json` is the output of `rebuild/compare_sections.py`. It compares the
rebuilt research DLL (`fsr_data_prepatch.dll`) against the original `fsr_data.dll` on a
per-section basis, reporting SHA-256 hashes and byte-level differences for each PE section.

## What This Is Not

This comparison does not prove a byte-identical rebuild.

The bounded claims are:
- extracted blob identity (the weight data bytes match the original)
- reconstructed lookup behavior (the C source reproduces the same export structure)
- transparent section-difference reporting (every differing region is reported honestly)

The rebuilt PE is not claimed to be:
- compiler-identical (different compiler, linker, and build flags produce different binaries)
- section-identical (`.data` differs by 638,140 bytes — expected, since the compiler lays out data differently)
- runtime-equivalent (not tested)
- deployable (not a replacement DLL)

## Why Some Sections Match and Others Don't

The extracted weight blobs are embedded by construction — the C source includes them as
static arrays, so the blob bytes match the original. However, the surrounding PE structure
(headers, section alignment, compiler-generated code, import tables) differs because the
rebuilt DLL was compiled with MinGW GCC, not AMD's original toolchain.

The `all_regions_match_without_patching: false` result in `section-comparison.json` is
correct and expected. The old tool (`pe_patcher.py`) artificially created hash equality by
copying original bytes into the rebuilt file before comparing. That circular approach has
been removed. The current tool reports differences honestly.

## Historical Context

A previous version of this project claimed MD5 hash equality as independent
independent reconstruction. That claim was overstated — the equality was circular because
the patcher copied original PE regions into the output before hashing. The circular approach
has been removed. See `docs/adversarial-review-resolution.md` issue #5 for the full history.
