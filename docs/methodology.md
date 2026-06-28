# Methodology

> How we reverse-engineered a neural network hidden inside a GPU upscaler DLL.
>
> **Scope**: Static analysis only. No dynamic/runtime capture was performed.

## The Problem

AMD's FidelityFX Super Resolution 4.1.0 is a neural network-based upscaler shipped as a Windows DLL. Unlike 4.0.2, which shipped with MIT-licensed HLSL source code, 4.1.0 is a binary-only release. We wanted to understand:

1. **Where are the neural network weights stored?**
2. **What is the model architecture?**
3. **What changed between 4.0.2 and 4.1.0?**

## Approach: Ground-Truth-First

The key insight: **we didn't need to reverse-engineer the architecture from scratch**. The 4.0.2 SDK ships with complete HLSL source for the same model (`fsr4_model_v07_fp8_no_scale`). This gave us:

- Exact tensor names, shapes, and byte offsets
- The model topology (encoder → bottleneck → decoder)
- Pass structure (14 compute passes)

Our task reduced to: (a) find where 4.1.0 stores its weights, and (b) confirm the architecture matches.

This is the same pattern used by GPU RE projects like Asahi Linux and Panfrost: use whatever public documentation exists as your starting scaffold, then fill in gaps with binary analysis.

## Stage 1: Ghidra Static Analysis

**Goal**: Locate the weight data in the DLL.

**Method**:
1. Ran Ghidra 12.1 headless on `dll_v410.dll` (15,605,520 bytes)
2. Decompiled all 340 functions to C pseudocode
3. Traced the call chain from `ffxDispatch` (the main entry point) down to the CreateContext factory function

**Key discovery**: `FUN_18000b3c0` contains a switch statement on quality preset. Each case executes a LEA instruction loading a pointer to a data section in `.rdata`. These pointers reference **6 weight blobs**, each 131,072 bytes (0x20000), allocated as `FSR4UPSCALER_InitializerBuffer`.

**Also discovered**:
- 27 dispatches per frame (confirmed by loop counter `0x1b`)
- Resource name tables (12 SRV, 12 UAV names)
- Sequential-only pipeline structure (no skip connections detected)
- Bottleneck autoencoder spatial pyramid: 1.0× → 0.5× → 0.25× → 0.125× → 0.25× → 0.5× → 1.0×

## Stage 2: Weight Extraction

**Goal**: Extract the actual weight data from the DLL.

**Method**:
1. Used `pefile` to resolve LEA instructions to RVA → file offset mappings
2. Extracted 6 blobs from known file offsets
3. Computed MD5 hashes to identify unique blobs

**Key discovery**: Only **2 unique blobs** out of 6. Five presets (Quality, Balanced, Performance, UltraPerf, Native) share identical weights. Only DRS (dynamic resolution scaling) has separate weights. In 4.0.2, all 6 were unique.

## Stage 3: Offset Mapping

**Goal**: Map each tensor (weight/bias) to its byte offset within the blob.

**Method**:
1. Wrote `parse_offsets.py` to extract `threadGroupStorageByteOffset` attributes from 4.0.2 HLSL source
2. This produced a complete 78-tensor table with offset, shape, format, and pass assignment
3. Confirmed 4.1.0 DXIL entry points use the observed `fsr4_model_v07_fp8_no_scale_*` naming family; the authoritative inventory is `spec/dxil-entrypoint-inventory.json`
4. Searched the 4.1.0 DLL binary for the known offset constants → **zero hits**
5. Confirmed offsets are loaded from cbuffer at runtime (not hardcoded)

**Key discovery**: The 4.0.2 schema is *consistent* with 4.1.0. Same 78 tensors, same offsets (assumed), same shapes. The architecture appears frozen. See caveats in [Offset Mapping](offset-mapping.md).

## Stage 4: Architecture Diff

**Goal**: Quantify what changed between versions.

**Method**:
1. Wrote `layer_diff.py` to compare blobs byte-by-byte per layer
2. Analyzed weight distributions (histogram of unique values)
3. Traced cbuffer loads in DXIL to understand the 4.1.0 offset delivery mechanism

**Key discoveries**:
- **98.7% of bytes changed** — consistent with complete weight retrain, uniform across all layers
- **122 → 255 unique weight values** — 4.0.2 used a limited FP8 codebook; 4.1.0 uses full uint8 range
- **222 FP32 output composition biases** (888 bytes) appended after existing weights — purpose unconfirmed; possibly quantization scale factors
- **Preset collapse** — quality is now controlled by spatial tiling/dispatch, not separate models

## Tools Used

| Tool | Purpose |
|------|---------|
| Ghidra 12.1 headless | Static decompilation of DLL |
| pefile (Python) | PE parsing, RVA resolution, LEA scanning |
| llvm-dis | DXIL → LLVM IR disassembly |
| Python (custom scripts) | Offset parsing, blob extraction, weight comparison |

## Dead Ends

Not everything worked on the first try:

1. **Searching for offset constants in the binary**: We expected to find the 4.0.2 offset values (like 7208, 130088) as raw i32 constants in the DLL's `.rdata` section. Zero hits. Turns out 4.1.0 loads everything through cbuffer — a runtime mechanism that doesn't leave static traces.

2. **Parsing DXIL for hardcoded offsets**: The DXIL IR uses `createHandle` + `cbufferLoadLegacy`, not `getelementptr` with constant offsets. The offsets are runtime parameters loaded from a constant buffer populated by the DLL's dispatch code.

3. **Assuming different models per preset**: Initial hypothesis was that each quality preset had its own neural network. Ghidra analysis showed 5 of 6 presets load the same RVA. Quality is controlled by spatial tiling parameters, not different weights.

## Verification Gaps

### What we did not verify

1. **Runtime offset values**: The 4.1.0 tensor offsets are loaded from cbuffer at runtime. We did not capture these values during execution. The assumption that they match the 4.0.2 HLSL offsets is based on structural equivalence (matching model name, pass count, blob layout), not direct observation.

2. **Skip connections**: We have strong indirect evidence against skip connections (resource name table, PSV0 data, dispatch loop structure). However, we did not deploy the D3D12 capture tools to observe actual GPU resource bindings at runtime.

3. **444 extra FP16 parameters**: We observed their existence and statistical properties but did not trace how they're consumed by the shader code. The "quantization scale factors" hypothesis is based on correlation with the improved FP8 range.

4. **Model correctness**: We did not reconstruct the model from extracted weights and verify its output matches FSR 4.1.0's actual upscaling behavior.

### What would close these gaps

| Gap | Method | Tool Status |
|-----|--------|------------|
| Runtime offset values | D3D12 cbuffer capture | `tools/ffx_d3d12_capture.c` — built but not deployed |
| Skip connections | GPU binding trace across passes | `tools/ffx_d3d12_capture.c` — built but not deployed |
| Extra parameter purpose | Shader tracing / decompilation | No tool written yet |
| Model correctness | Weight extraction + inference comparison | No tool written yet |

## Evidence Assessment

| Finding | Confidence | Basis | What would raise it |
|---------|-----------|-------|---------------------|
| Weight blob locations | **99%** | Direct LEA tracing, pefile verification, allocation size match | — |
| 78-tensor offset map (4.0.2) | **99%** | Parsed from MIT-licensed source | — |
| 78-tensor offset map (4.1.0) | **85%** | Assumed from name match + structural equivalence | Runtime cbuffer capture |
| No skip connections | **90%** | Consistent indirect evidence from 3 independent sources | D3D12 hook deployment |
| Weight retrain (inferred) | **99%** | Byte-by-byte diff, 98.7% changed uniformly | — |
| Architecture unchanged | **95%** | Same entry points, same tensor count, same blob layout | Runtime verification |
| Extra params = quant scales | **70%** | Correlation with improved FP8 range, plausible mechanism | Shader tracing |
