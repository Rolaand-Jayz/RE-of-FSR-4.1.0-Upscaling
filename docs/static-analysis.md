# Static Analysis

> Ghidra decompilation of the FSR 4.1.0 DLL — dispatch pipeline, resource bindings, and skip connection assessment.
>
> **Method**: Static analysis only. No dynamic/runtime capture was performed.

## Overview

We decompiled all 340 exported functions from `dll_v410.dll` (15,273,344 bytes) using Ghidra 12.1 headless. This produced C pseudocode for the entire runtime pipeline, from the top-level dispatch entry point down to the per-pass binding resolver.

**Limitation**: Static analysis reveals program structure and data references, but cannot confirm actual runtime behavior. Findings below reflect what the code *appears to do*, not what was observed executing.

## Call Chain

*Source: Ghidra decompilation, cross-referenced with DLL export table.*

```
ffxDispatch()                              — Export #2, vtable trampoline
  └─ ffxProvider_FSR4::Dispatch()          — FUN_18000d5b0 (26 KB decompiled)
       ├─ FUN_18000b3c0()                  — CreateContext: pipeline creation, preset switch
       │    └─ LEA × 6                     — Load weight blob RVAs per preset
       ├─ FUN_1800083c0()                  — Dispatch dimension calculator (14 passes)
       ├─ FUN_18000d380() × 27             — Per-pass dispatch loop
       │    └─ FUN_18000a910()             — Resource binding name resolver
       ├─ FUN_180004eb0()                  — Pipeline state setup (22 KB)
       └─ FUN_180012be0()                  — Pass name template formatter
```

## The 27-Iteration Dispatch Loop

*Source: Direct decompilation of `FUN_18000d5b0`.*

```c
lVar24 = 0x1b;  // 27 iterations
do {
    local_1240 = (uint)(*(char *)(puVar20 + 2) != '\0');  // enabled flag
    local_1248 = puVar20[1];                                // pass variant
    FUN_18000d380(lVar2, lVar16, puVar20[-1], *puVar20);   // dispatch pass
    puVar20 = puVar20 + 4;                                  // advance params
    lVar16 = lVar16 + 0x8e68;                               // advance pass context
    lVar24 = lVar24 + -1;
} while (lVar24 != 0);
```

- **27 dispatches per frame** (0x1b = 27) ✅ *Verified: literal constant in decompiled code*
- Each pass context: 36,456 bytes (0x8e68) ✅ *Verified: stride in loop advancement*
- Total pass context: ~984 KB
- Breakdown: 1 prepass + 12 model + 12 model_post + 1 postpass + 1 SPD

## Resource Name Tables

*Source: Ghidra decompilation of `FUN_18000a910` (binding resolver) and referenced data tables.*

`FUN_18000a910` resolves per-pass resource bindings by matching shader resource names against two global tables.

### SRV (Read) Resources — 12 entries

| Index | Name | Used By |
|-------|------|---------|
| 0 | `r_input_color` | Model passes (input features) |
| 1 | `r_rcas_input` | RCAS pass |
| 2 | `r_velocity` | Prepass |
| 3 | `r_depth` | Prepass |
| 4 | `r_input_exposure` | Exposure |
| 5 | `r_auto_exposure_texture` | Auto-exposure |
| 6 | `r_recurrent_0` | Temporal feedback |
| 7 | `r_history_color` | History buffer |
| 8 | `r_reprojected_color` | Reprojection |
| 9 | `r_debug_visualization` | Debug |
| 10 | `r_result_color` | Result readback |
| 11 | `InitializerBuffer` | **Weight data** |

### UAV (Write) Resources — 12 entries

| Index | Name | Used By |
|-------|------|---------|
| 0 | `rw_output_color_for_rcas` | RCAS output |
| 1 | `rw_mlsr_output_color` | **Model output** |
| 2 | `rw_final_output_color` | Final output |
| 3 | `rw_rcas_output` | RCAS pass |
| 4 | `rw_recurrent_0` | Temporal feedback |
| 5 | `rw_history_color` | History buffer |
| 6 | `rw_reprojected_color` | Reprojection |
| 7 | `rw_auto_exposure_texture` | Auto-exposure |
| 8 | `rw_spd_global_atomic` | SPD atomic |
| 9 | `rw_autoexp_mip_5` | Auto-exposure mip |
| 10 | `rw_debug_visualization` | Debug |
| 11 | `ScratchBuffer` | Scratch |

### Skip Connection Analysis

> ⚠️ **Static analysis only.**

The model passes bind:
- **Read**: `r_input_color` + `InitializerBuffer` + cbuffer
- **Write**: `rw_mlsr_output_color`

There are **no encoder-to-decoder cross-references** in the resource name table. No names like `r_encoder_N_output` or `r_skip_N` exist. The binding resolver would need additional entries to support skip connections — they don't exist in the static name table.

**However**: This does not rule out skip connections implemented through other mechanisms (e.g., aliased resource bindings, descriptor heap manipulation, or compute shader implicit state). Runtime capture would be needed to fully exclude this possibility.

## U-Net Spatial Dimensions

*Source: Ghidra decompilation of tile config tables at RVAs 0x5c510, 0x5c8d0, 0x5cc90.*

Three tile config tables (3 base resolutions × 17 passes) encode the spatial structure:

### 1080p Base Resolution

| Pass | Scale | Dimensions | Stage |
|------|-------|-----------|-------|
| 0 | 0.5× | 540×960 | Encoder downsample |
| 1 | 1.0× | 1080×1920 | Full-res pass |
| 2 | 0.5× | 540×960 | Encoder |
| 3 | 0.5× | 540×960 | Encoder |
| 4 | 0.25× | 270×480 | Encoder |
| 5 | 0.25× | 270×480 | Encoder |
| 6 | 0.25× | 270×480 | Encoder |
| 7 | 0.125× | 135×240 | Bottleneck |
| 8 | 0.125× | 135×240 | Bottleneck |
| 9 | 0.125× | 135×240 | Bottleneck |
| 10 | 0.25× | 270×480 | Decoder |
| 11 | 0.25× | 270×480 | Decoder |
| 12 | 0.5× | 540×960 | Decoder |
| 13 | 0.5× | 540×960 | Decoder |
| 14 | 1.0× | 1080×1920 | Final pass |
| 15 | 1.0× | 1080×1920 | Postpass |
| 16 | 1.0× | 1080×1920 | Postpass |

Classic U-Net spatial pyramid: 1.0 → 0.5 → 0.25 → 0.125 → 0.25 → 0.5 → 1.0. ✅ *Verified: decoded directly from static data tables.*

## Identical PSV0 Bindings

*Source: pefile analysis of embedded DXBC blobs.*

All 12 model passes have **byte-identical** PSV0 (Pipeline State Validation) resource binding data:
- UAV space=1 reg=0 (atomic scratch)
- UAV space=0 reg=11 (output)
- SRV space=0 reg=18 (input features)
- CBV space=0 reg=0 (constants)

Since the shader code is identical across passes and register bindings don't change, the runtime is responsible for rotating which GPU buffer occupies each slot between dispatches.

**Implication**: If skip connections existed, the decoder passes would need different SRV bindings than encoder passes. The PSV0 data being identical is consistent with (but does not prove) a purely sequential pipeline.

## Build Metadata

*Source: Ghidra decompilation of embedded debug strings.*

```
MLSR Upscale {}
Build time: Mar 20 2026 16:15:21
Git branch: {}  commit: abd3160
```

- Internal name: **MLSR** (Multi-Layer Super Resolution)
- Architecture variants detected: `v07-i8` (integer 8-bit), `wmma` (wave matrix multiply)
- Colorspace modes: LINEAR, NON-LINEAR, SRGB, PQ

## Evidence Assessment

| Finding | Evidence Level | What Would Strengthen It |
|---------|---------------|------------------------|
| 27 dispatches per frame | ✅ **High** — literal constant in decompiled code | Runtime capture |
| Weight blob locations in .rdata | ✅ **High** — LEA tracing + pefile cross-verification | Runtime capture |
| Sequential pipeline (no skips) | ⚠️ **Moderate** — consistent indirect evidence, no direct observation | D3D12 hook deployment |
| U-Net spatial pyramid | ✅ **High** — decoded from static data tables | Runtime capture |
| Per-pass binding swap | ⚠️ **Moderate** — inferred from identical PSV0 + name resolver | GPU binding capture |
| Model = 12-layer sequential U-Net | ⚠️ **Moderate** — combines multiple moderate-evidence findings | End-to-end verification |
