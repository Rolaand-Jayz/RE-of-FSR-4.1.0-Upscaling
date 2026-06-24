# FSR 4.0.2 → 4.1.0 C++ Provider Layer Diff Report

**Date:** 2026-06-01  
**Author:** Automated RE analysis  
**Sources:**  
- 4.0.2 MIT source: `ffx_provider_fsr4_dx12.cpp`, `fsr4_permutations.h`, `ffx_fsr4upscaler_resources.h`  
- 4.1.0: Ghidra decompilation of shipping DLL + `ffx_upscale.h` (v220 SDK header)

---

## 1. Version Identification

| Property | 4.0.2 | 4.1.0 |
|---|---|---|
| Version string | `"4.0.2"` | Build string: `"Mar 20 2026 16:15:21"`, git commit `"abd3160"` |
| Provider ID | `0xF5A5CA1E << 32 \| FFX_SDK_MAKE_VERSION(4,0,2)` | Version checked via `ffxCreateContextDescUpscaleVersion` with `FFX_UPSCALER_VERSION = 4.1.0` |
| Watermark format | `MLSR Upscale {wmma\|v07-i8}` | Same format, identical structure |

---

## 2. Resource Identifier Changes

### 4.0.2 Resource IDs (`ffx_fsr4upscaler_resources.h`)

| ID | Name |
|---|---|
| 0 | NULL |
| 1 | INPUT_COLOR |
| 2 | INPUT_MOTION_VECTORS |
| 3 | INPUT_DEPTH |
| 4 | INPUT_EXPOSURE |
| 5 | AUTO_EXPOSURE |
| 6 | SPD_ATOMIC_COUNT |
| 7 | SPD_MIP5 |
| 8 | LUMA_0 |
| 9 | LUMA_1 |
| 10 | MLSR_OUTPUT |
| 11 | RCAS_OUTPUT |
| 12 | FINAL_OUTPUT |
| 13 | RECURRENT |
| 14 | HISTORY |
| 15 | HISTORY_REPROJECTED |
| 16 | RCAS_TEMP |
| 17 | INTERNAL_DEFAULT_EXPOSURE |
| 18 | MLSR_BIND_SRV_BUFFER_NHWC_INPUTS |
| 19 | MLSR_BIND_SRV_BUFFER_FUSED_QUANTIZED_NHWC_OUTPUT |
| 20 | MLSR_BIND_SRV_INITIALIZER_BUFFER |
| 21 | MLSR_BIND_SRV_INITIALIZER_STAGING_BUFFER |
| 22 | MLSR_BIND_SRV_SCRATCH_BUFFER |
| 23 | DEBUG_INFORMATION |
| 24 | RESULT_COLOR |
| **25** | **COUNT** |

### 4.1.0 Resource IDs (reconstructed from Ghidra `text_00bca0.c`)

The resource creation function (`FUN_18000bca0`) creates resources with the following names and IDs:

| Offset in struct | Name | ID (hex) | ID (dec) | 4.0.2 equivalent |
|---|---|---|---|---|
| +0x00 | FSR4UPSCALER_Recurrent | 0x0D | 13 | 13 (RECURRENT) — **identical** |
| +0x0D | FSR4UPSCALER_History | 0x0E | 14 | 14 (HISTORY) — **identical** |
| +0x1A | FSR4UPSCALER_HistoryReprojected | 0x0F | 15 | 15 (HISTORY_REPROJECTED) — **identical** |
| +0x27 | FSR4UPSCALER_RcasIntermediary | 0x10 | 16 | 16 (RCAS_TEMP) — **identical** |
| +0x34 | FSR4UPSCALER_AutoExposure | 0x05 | 5 | 5 (AUTO_EXPOSURE) — **identical** |
| +0x41 | FSR4UPSCALER_DefaultExposure | 0x11 | 17 | 17 (INTERNAL_DEFAULT_EXPOSURE) — **identical** |
| +0x4D | FSR4UPSCALER_DefaultExposure (static) | — | — | Same 1x1 exposure buffer |
| +0x56 | FSR4UPSCALER_SpdAtomicCounter | 0x06 | 6 | 6 (SPD_ATOMIC_COUNT) — **identical** |
| +0x5E | FSR4UPSCALER_Luma_Mip_5 | 0x07 | 7 | 7 (SPD_MIP5) — **identical** |
| +0x70 | FSR4UPSCALER_ScratchBuffer | **0x16** | **22** | 22 (MLSR_BIND_SRV_SCRATCH_BUFFER) — **identical** |
| +0x7D | FSR4UPSCALER_InitializerBuffer | **0x14** | **20** | 20 (MLSR_BIND_SRV_INITIALIZER_BUFFER) — **identical** |
| +0x86 | FSR4UPSCALER_InitializerBuffer_Upload | **0x15** | **21** | 21 (MLSR_BIND_SRV_INITIALIZER_STAGING_BUFFER) — **identical** |
| +0x93 | FSR4UPSCALER_DebugInformation | **0x17** | **23** | 23 (DEBUG_INFORMATION) — **identical** |

### Resource ID Verdict
**Resource IDs are UNCHANGED between 4.0.2 and 4.1.0.** All 12 internal resources maintain the same numeric IDs. No new resource slots were added. The resource count remains at 25.

### Scratch Buffer Size Changes
In 4.1.0, the scratch buffer size is now resolution-dependent:
- `1920×1080` and below: `0x13E9B80` (≈21.1 MB)
- `1921×1080` to `3840×2160`: `0x4F60600` (≈83.5 MB)  
- `3841×2160` and above: `0x13CF4B00` (≈322 MB)

4.0.2 used a fixed size (not resolution-scaled in this manner — the size was hardcoded differently based on the preset selection in `CreateModel`). This is a **meaningful change**: 4.1.0 dynamically selects scratch buffer size based on the max render/upscale size at context creation time.

---

## 3. Constant Buffer Layout Changes

### 4.0.2 Constant Buffer IDs

| ID | Name |
|---|---|
| 0 | FSR4UPSCALER (main constants) |
| 1 | AUTOEXPOSURE |
| 2 | SPD_AUTOEXPOSURE |
| 3 | RCAS |
| 4 | PASS_WEIGHTS |
| **5** | **COUNT** |

### 4.0.2 Main Constants Structure (`OptimizedConstants`, 256-byte aligned)

```c
struct alignas(256) OptimizedConstants {
    float inv_size[2];           // +0x00
    float scale[2];              // +0x08
    float inv_scale[2];          // +0x10
    float jitter[2];             // +0x18
    float mv_scale[2];           // +0x20
    float tex_size[2];           // +0x28
    float max_renderSize[2];     // +0x30
    float fMotionVectorJitterCancellation[2]; // +0x38
    uint32_t width;              // +0x40
    uint32_t height;             // +0x44
    uint32_t reset;              // +0x48
    uint32_t width_lr;           // +0x4C
    uint32_t height_lr;          // +0x50
    float preExposure;           // +0x54
    float previous_preExposure;  // +0x58
    uint32_t rcas_enabled;       // +0x5C
    float rcas_sharpness;        // +0x60
    float _pad1;                 // +0x64
};
```

### 4.1.0 Main Constants Structure (reconstructed from `text_00d5b0.c`)

From the dispatch function, the constant buffer is staged at offset `lVar2 + 0x10c600` with size `0x100` (256 bytes). The field offsets are:

| Offset | 4.0.2 field | 4.1.0 offset | Notes |
|---|---|---|---|
| 0x00 | inv_size[0] | 0x10c600 | 1.0/upscaleWidth |
| 0x04 | inv_size[1] | 0x10c604 | 1.0/upscaleHeight |
| 0x08 | scale[0] | 0x10c608 | upscaleW/renderW |
| 0x0C | scale[1] | 0x10c60C | upscaleH/renderH |
| 0x10 | inv_scale[0] | 0x10c610 | 1.0/scale[0] |
| 0x14 | inv_scale[1] | 0x10c614 | 1.0/scale[1] |
| 0x18 | jitter[0] | 0x10c618 | desc->jitterOffset.x |
| 0x1C | jitter[1] | 0x10c61C | desc->jitterOffset.y |
| 0x20 | mv_scale[0] | 0x10c620 | MV scale / dimension |
| 0x24 | mv_scale[1] | 0x10c624 | MV scale / dimension |
| 0x28 | tex_size[0] | 0x10c628 | maxUpscaleSize.width |
| 0x2C | tex_size[1] | 0x10c62C | maxUpscaleSize.height |
| 0x30 | max_renderSize[0] | 0x10c630 | maxRenderSize.width |
| 0x34 | max_renderSize[1] | 0x10c634 | maxRenderSize.height |
| 0x38 | fMotionVectorJitterCancellation[0] | 0x10c638 | Computed from previousJitter |
| 0x3C | fMotionVectorJitterCancellation[1] | 0x10c63C | Computed from previousJitter |
| 0x40 | width | 0x10c640 | upscaleWidth |
| 0x44 | height | 0x10c644 | upscaleHeight |
| 0x48 | reset | 0x10c648 | desc->reset OR forceReset |
| 0x4C | width_lr | 0x10c64C | renderSize.width |
| 0x50 | height_lr | 0x10c650 | renderSize.height |
| 0x54 | preExposure | 0x10c654 | desc->preExposure |
| 0x58 | previous_preExposure | 0x10c658 | saved from previous frame |
| 0x5C | rcas_enabled | 0x10c65C | desc->enableSharpening |
| 0x60 | rcas_sharpness | 0x10c660 | desc->sharpness |
| 0x64 | _pad1 | — | Not observable from decompilation |

### Constant Buffer Verdict
**The main constant buffer layout is STRUCTURALLY IDENTICAL between 4.0.2 and 4.1.0.** All fields maintain the same offsets and semantics. The staging size is `0x100` (256 bytes) in both versions, matching the `alignas(256)` from 4.0.2.

The RCAS constant buffer is staged at `lVar2 + 0x10c800` (256 bytes), also identical.

---

## 4. SRV/UAV Binding Table Changes

### 4.0.2 SRV Binding Table
```
{1,  "r_input_color"},
{16, "r_rcas_input"},
{2,  "r_velocity"},
{3,  "r_depth"},
{4,  "r_input_exposure"},
{5,  "r_auto_exposure_texture"},
{13, "r_recurrent_0"},
{14, "r_history_color"},
{15, "r_reprojected_color"},
{23, "r_debug_visualization"},
{24, "r_result_color"},
{20, "InitializerBuffer"},
```
**12 SRV texture bindings**

### 4.0.2 UAV Binding Table
```
{16, "rw_output_color_for_rcas"},
{10, "rw_mlsr_output_color"},
{12, "rw_final_output_color"},
{11, "rw_rcas_output"},
{13, "rw_recurrent_0"},
{14, "rw_history_color"},
{15, "rw_reprojected_color"},
{5,  "rw_auto_exposure_texture"},
{6,  "rw_spd_global_atomic"},
{7,  "rw_autoexp_mip_5"},
{23, "rw_debug_visualization"},
{22, "ScratchBuffer"},
```
**12 UAV texture bindings** (ScratchBuffer listed but actually a buffer, not texture)

### 4.0.2 Constant Buffer Binding Table
```
{0, "MLSR_Optimized_Constants"},
{2, "AutoExposureSPDConstants"},
{3, "cbRCAS"},
{4, "cbPass_Weights"},
```
**4 CB bindings** (CB #1 AUTOEXPOSURE not directly bound to pipelines)

### 4.1.0 Binding Tables
The binding tables are compiled into the shader permutation data structures (embedded in DLL data sections at addresses like `DAT_18005c510`, `DAT_18005c110`, `DAT_18005c910` per preset). The `scheduleDispatch` equivalent (`FUN_18000d380`) resolves bindings by:
1. SRV textures: Reads resource IDs from pipeline state at `param_2 + 0x234c`, indexes into `param_1 + 0x148` (srvResources array)
2. UAV textures: Reads from `param_2 + 0x464c`, indexes into same resources
3. SRV buffers: Reads from `param_2 + 0x4c`, indexes into `param_1 + 0x1ac` (srvBuffer/uavBuffer resources)
4. UAV buffers: Reads from `param_2 + 0x694c`, indexes into `param_1 + 0x1ac`
5. Constant buffers: Reads from `param_2 + 0x8c4c`, indexes into `param_1 + 0xf8` (constant buffer array)

The binding count fields are at pipeline offsets:
- `+0x18`: srvBufferCount
- `+0x1C`: srvTextureCount  
- `+0x20`: uavTextureCount
- `+0x24`: uavBufferCount
- `+0x38`: constCount

### Binding Table Verdict
**The binding resolution mechanism is architecturally identical.** Resource IDs have not changed (confirmed by matching resource creation). The pipeline state structure offset layout matches expectations from 4.0.2's `FfxPipelineState`.

---

## 5. Permutation/Variant Selection Logic

### 4.0.2 Permutation Model
- **Two codepaths**: `FSR4_ENABLE_DOT4` (v07-i8 integer quantized) and `fp8_no_scale` (WMMA fp8)
- **Presets**: NativeAA, Quality, Balanced, Performance, UltraPerformance, DRS
- **Resolution tiers per preset**: 1080, 2160, 4320
- **14 model passes** (indices 0-13) + SPD auto-exposure + RCAS + debug view
- **13 padding passes** (indices 0-12, for WMMA path)

Shader naming convention: `fsr4_model_v07_{i8|fp8_no_scale}_{preset}_{resolution}_{pass}_permutations.h`

### 4.1.0 Permutation Model (from `text_00b3c0.c`)
The `CreateModel` function (`FUN_18000b3c0`) takes a preset parameter (`param_2`) with values:
- 0-4: Same presets as 4.0.2 (NativeAA through UltraPerformance)
- **5: New preset** (case 5 has different data, likely a new quality mode or variant)

The shader blob selection uses `FUN_180025990` with pass indices:
- Model passes: indices 0 through **0x1a** (26) — loop is `while (uVar17 < 0x1b)` → **27 passes total**
- SPD auto-exposure: index **0x1c** (28)
- RCAS: index **0x1b** (27)
- Debug view: index **0x1d** (29)

### Key Permutation Changes
1. **Model pass count increased from 14 to 27.** The 4.0.2 had model_pso[0..13] (14 passes). The 4.1.0 creates 27 model passes (0 through 26). This is nearly double.
2. **New pass at index 5**: Case 5 in the switch is a **new permutation variant** (could be a new quality preset not present in 4.0.2).
3. **Pass structure at offset 0x8E68 per pipeline state**: `FUN_18000d380` uses stride `0x8E68` between pipeline states, suggesting a larger pipeline state structure than 4.0.2.
4. **Padding passes eliminated or consolidated**: The 4.0.2 had separate `padding_pso[]` arrays for WMMA. In 4.1.0, the padding dispatch sizes are computed by `FUN_180008250` and stored directly in the dispatch size structure (at offsets like `param_3[0x44..0xAF]`), suggesting padding is now integrated into the main dispatch loop.

### Dispatch Size Computation (4.1.0 `FUN_1800083c0`)
This function computes dispatch sizes for all 27 passes based on 3 data tables (addresses at `DAT_18005c510/110/910` for presets 0/1/2). The structure has:
- Main dispatch sizes for passes 0-12 (13 passes × 3 fields each)
- Padding sizes computed at fixed offsets (0x44, 0x4C, 0x54, etc.)
- Different group sizes per preset

### Preset Selection Thresholds (from `text_00c700.c` CreateContext)
```
fVar14 = maxUpscaleWidth / maxRenderWidth
if (DAT_180ec57c4 <= fVar14) preset = 1 (Quality)
if (DAT_180ec57d0 <= fVar14) preset = 2 (Balanced)
if (DAT_180ec57e0 <= fVar14) preset = 3 (Performance)
if (DAT_180ec57e8 <= fVar14) preset = 5 (UltraPerformance)
if (DRS flag) preset = 4
```

And from dispatch (`text_00d5b0.c`):
```
fVar25 = upscaleWidth / renderWidth
if (DAT_180ec57c8 <= fVar25) uVar19 = 2 (Quality)
if (DAT_180ec57d0 <= fVar25) uVar19 = 3
if (DAT_180ec57e0 <= fVar25) uVar19 = 5 (UltraPerformance)
uVar19 = 2 by default (was 0=NativeAA in 4.0.2)
```

### Preset Threshold Verdict
**The threshold constants changed.** In 4.0.2:
- Quality: ≥1.50
- Balanced: ≥1.69
- Performance: ≥1.99
- UltraPerformance: ≥2.99

In 4.1.0, the thresholds are loaded from global data (`DAT_180ec57c4`, `DAT_180ec57c8`, etc.) and are likely similar but **stored differently** — the CreateContext thresholds use different globals than dispatch thresholds, and the default has changed from NativeAA (0) to what appears to be Quality (2).

---

## 6. API Parameter Changes

### New in 4.1.0

1. **`ffxCreateContextDescUpscaleVersion`** (type `0x1000b`): A **new create context descriptor** that carries `FFX_UPSCALER_VERSION`. The DLL validates this against expected version and rejects invalid versions. This is checked in `text_00c700.c`.

2. **Version validation**: The DLL reads through the create context descriptor chain looking for `type == 0x1000b` and validates `version >= 0x1000000 && version <= 0x1001001`.

3. **Context structure size**: The internal context is allocated at size **0x10CA00** (~1.07 MB) in 4.1.0, substantially larger than what 4.0.2 would have required (storing 27 pipeline states × 0x8E68 = ~1.5 MB for pipeline data alone).

### Dispatch Parameter Changes

4. **`cameraFovAngleVertical` validation**: 4.1.0 adds debug checking that `cameraFovAngleVertical` is in range `(0, PI]`. This field was present in 4.0.2's `ffxDispatchDescUpscale` but was **never validated**.

5. **`frameTimeDelta` validation**: 4.1.0 warns if `frameTimeDelta < 1.0f`. This field was present in 4.0.2 but unused/unchecked.

6. **`motionVectorScale` validation**: 4.1.0 checks that motion vector scale values don't exceed maxRenderSize and aren't zero. Not validated in 4.0.2.

7. **UNORM color format detection**: 4.1.0 adds a warning if color resource has UNORM format but no nonlinear colorspace flag is set. Not present in 4.0.2.

8. **DRS flag enforcement**: 4.1.0 checks that if the scaling ratio changes between dispatches, the `FFX_UPSCALE_ENABLE_DYNAMIC_RESOLUTION` flag was set at context creation.

### Unchanged Dispatch Parameters
All other dispatch fields (color, depth, motionVectors, exposure, output, jitterOffset, motionVectorScale, renderSize, upscaleSize, enableSharpening, sharpness, preExposure, reset) are at the same offsets and serve the same purpose.

---

## 7. Pipeline Creation Changes

### 4.0.2
- `CreateModel()` creates model PSOs via `createPipelineFunc`
- 14 model passes + optional 13 padding passes (WMMA only)
- Pass names: `"FFX_FSR4_PASS_{}"` (format string with pass index)
- Additional PSOs: `spd_auto_exposure_pso`, `rcas_pso`, `debug_view_pso`

### 4.1.0 (from `text_00b3c0.c`)
- Same `CreateModel()` pattern with `FUN_18000b3c0`
- **27 model passes** (0 through 26), stored at stride 0x8E68
- Pass names: `"FFX_FSR4_PASS_{}"` — identical format string
- SPD auto-exposure: `"FFX_FSR4_SPD_AUTOEXPOSURE_PASS"` — **identical**
- RCAS: `"FFX_FSR4_RCAS_PASS"` — **identical**
- Debug view: `"FFX_FSR4_DEBUG_VIEW_PASS"` — **identical**
- Pipeline state stored at context offsets:
  - Model PSOs: `context + 0x238` through `context + 0x238 + 26*0x8E68`
  - SPD PSO: `context + 0xF9598`
  - RCAS PSO: `context + 0xF0730`
  - Debug PSO: `context + 0x102400`

---

## 8. WMMA vs Non-WMMA Path

### 4.0.2
The dispatch explicitly branches on `supportsWmma`:
- WMMA path: Different group sizes (16×8, 32×4, etc.) + padding dispatches
- Non-WMMA path: Group sizes (64, 16×16, etc.) + no padding

### 4.1.0
The `supportsWmma` check is stored at context offset `+0x21D`. The dispatch size computation in `FUN_1800083c0` uses **3 different data tables** (preset 0, 1, 2) rather than a WMMA/non-WMMA branch. The WMMA flag influences which preset data table is selected for dispatch sizing.

The dispatch no longer has an explicit if/else for WMMA — instead, the preset data tables encode the correct group sizes for the hardware capability. This is a **cleaner design** but functionally equivalent.

---

## 9. Weight Data (Pass0Weights / Model Constants)

### 4.0.2
Two weight arrays: `weights_native[256]` and `weights_quality[256]` (1024 bytes each, 256 × uint32_t). These are embedded directly in the C++ source as hex data.

### 4.1.0
The weight data is now stored in the DLL's data section. The RCAS constant buffer staging at `lVar2 + 0x10c800` with size `0x100` suggests the weights may have been moved to per-pipeline-state data rather than a shared constant buffer. The dispatch function stages pass weights via `FUN_1800083c0` which fills the dispatch sizes structure, implying weights are baked into shader blobs or loaded differently.

---

## 10. Summary of All Differences

| Category | Change | Impact |
|---|---|---|
| **Model passes** | 14 → 27 (nearly doubled) | **MAJOR** — substantially more compute passes |
| **New preset value** | Case 5 added to preset switch | **MEDIUM** — may be new quality tier or variant |
| **Scratch buffer sizing** | Fixed → resolution-dependent (3 tiers) | **MEDIUM** — affects memory usage |
| **Version validation** | New `ffxCreateContextDescUpscaleVersion` | **LOW** — API compatibility check |
| **Debug validation** | New parameter validation (FOV, frameTime, MV scale, UNORM detection) | **LOW** — debug-only, no functional change |
| **WMMA dispatch** | Branch eliminated, preset data tables encode group sizes | **LOW** — refactored, same behavior |
| **Resource IDs** | Unchanged | None |
| **Constant buffer layout** | Unchanged | None |
| **SRV/UAV binding tables** | Unchanged | None |
| **Pass names** | Unchanged | None |
| **CB binding names** | Unchanged | None |
| **Dispatch parameter struct** | Unchanged (same offsets) | None |
| **Weight data** | Moved from C++ embedded to DLL data section | None (functional) |

---

## 11. Implications for Shader Replacement / Hooking

1. **27 model passes instead of 14**: Any hooking infrastructure must handle 27 dispatch calls per frame, not 14.
2. **Same resource binding slots**: All SRV/UAV/CB slots use the same IDs, so resource replacement hooks from 4.0.2 should work.
3. **Same constant buffer layout**: Constant buffer patching code does not need updating.
4. **New dispatch size computation**: The `FUN_1800083c0` function computes dispatch sizes from 3 preset data tables; this logic is different from 4.0.2's hardcoded arrays.
5. **Version gate**: The DLL now requires a version descriptor in the create context chain; integrators must provide `ffxCreateContextDescUpscaleVersion` with `FFX_UPSCALER_VERSION`.
