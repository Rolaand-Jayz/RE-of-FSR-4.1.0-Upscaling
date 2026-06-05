# FSR 4.0 Shader Internals

## Overview

The FSR 4.0 neural upscaler uses **28 unique compute shader functions** across
**27 + 3 conditional passes**. All shaders are DXIL compute shaders targeting
thread group dimensions **(32, 1, 1)** — wavefront-width 1D dispatch.

The architecture is named `fsr4_model_v07_fp8_no_scale` internally, confirming:
- Model version 7
- FP8 quantized weights (no per-tensor scale factors — "no_scale")
- The "no_scale" designation means FP8 values use a fixed shared exponent
  rather than per-tensor scale factors

## Shader Naming Convention

Each pass has **3 variants** (one per quality preset: quality/balanced/performance
or possibly ultra-performance). The variants are **byte-identical shader code**
differing only in **constant offsets** into the weight buffer (InitializerBuffer),
confirming all presets share the same neural architecture with different trained
weights.

```
fsr4_model_v07_fp8_no_scale_prepass     — 90 variants (many quality/resolution combos)
fsr4_model_v07_fp8_no_scale_pass0_post  — 3 variants per pass
fsr4_model_v07_fp8_no_scale_pass1       — 3 variants per pass
...
fsr4_model_v07_fp8_no_scale_pass12      — 3 variants per pass
fsr4_model_v07_fp8_no_scale_pass12_post — 3 variants per pass
fsr4_model_v07_fp8_no_scale_postpass    — 48 variants (many quality/resolution combos)
```

The prepass and postpass have many more variants because they are parameterized
for multiple quality presets × resolution tiers, while the core ML passes (1–12)
are resolution-independent and only need 3 variants (one per weight set).

## FP8 Decode Mechanism

### The LUT-Based FP8→FP16 Conversion

The shaders do NOT perform FP8 arithmetic directly. Instead, they use a
**256-entry lookup table (LUT)** stored in the ScratchBuffer (UAV space=1, reg=0)
to convert FP8 values to FP16.

The decode pattern per FP8 byte:
1. Read FP8 byte from weight SRV (space=0, reg=18) via `rawBufferLoad`
2. Use `atomicCompareExchange` with FIXED byte offsets into the LUT UAV
3. The LUT offset pattern reveals a 256-byte stride (0x100) — exactly matching
   the 256 possible FP8 byte values
4. Each FP8 byte produces 8 FP16 values via LUT lookup
5. Pairs are combined: 4 FP16 pairs per decode cycle

The constant offsets in the `atomicCompareExchange` calls are NOT actual atomic
operations — they are GPU-side table lookups. The pattern:

```
offset 0x50000029 = LUT base (scale factor lookup)
offset 0x51000a29 = secondary scale lookup
offset 0x52000029 = FP8 decode entry 0 (stride 0x100 between entries)
offset 0x52000129 = FP8 decode entry 1
...8 consecutive entries with 0x100 stride...
```

This is a hardware-optimized FP8 decode that leverages GPU atomics as
side-effect-free table lookups for parallel conversion.

### Why Atomics as LUT Lookups?

DXIL compute shaders lack a general-purpose LUT instruction. The
`InterlockedCompareExchange` (dx.op 79) on a raw buffer serves as an
idiomatic way to:
- Read a value from a known offset (the "expected" parameter)
- Return the previous value at that offset
- Since `compare` = 0 and `value` = 0, the exchange is a no-op on the buffer
- The return value is the LUT entry

This is AMD's optimization to avoid branching for FP8 decode.

## Neural Architecture

### Pass Structure

The 28 passes break into distinct architectural roles:

| Tier | Passes | Role | Lines | Atomics | Float Ops |
|------|--------|------|-------|---------|-----------|
| Input | prepass | Feature extraction + sampling | 2267 | 206 | 466 fmul, 262 fadd |
| Small Conv | pass1, pass2, pass12 | 1×1 convolutions | ~4900 | 1989 | ~1 fadd |
| Medium Conv | pass4, pass5, pass10 | Wider convolutions | ~8000 | 3296 | ~1 fadd |
| Large Conv | pass7, pass8 | Deepest convolutions | ~20750 | 9088 | ~1 fadd |
| Specialized | pass3, pass6, pass9, pass11 | Unique roles | varies | varies | varies |
| Output | postpass | Composite + writeback | 2675 | 1580 | 146 fmul, 100 fadd |
| Scatter | pass*_post (×13) | Data rearrangement only | ~125 | 0 | 0 |

### Prepass — Input Feature Extraction

**Not an ML layer.** This is a conventional shader that:
- Reads 5 SRVs (input color planes at space 0–5) via a Sampler (bilinear)
- Performs heavy float math (466 multiply, 262 add) — feature extraction
- Writes to 3 UAVs (output feature planes)
- Uses 1D/2D dispatch (groupId in X and Z only)
- Purpose: Extract features from the input image (luma, chroma, motion vectors,
  depth) into feature planes for the ML pipeline

### Core ML Passes (pass1–pass12)

All 12 core ML passes share the same resource binding pattern:
- **UAV space=1 reg=0** — ScratchBuffer (FP8 decode LUT + working memory)
- **UAV space=0 reg=11** — ScratchBuffer (output scatter target)
- **SRV space=0 reg=18** — InitializerBuffer (FP8 weights)
- **CBV space=0 reg=0** — Constant buffer (dispatch parameters)
- **3D dispatch** using groupId in X, Y, and Z dimensions
- **0 barriers** — no cross-wavefront synchronization needed
- **Integer-only computation** — the FP8 decode + accumulation happens through
  the LUT atomic mechanism, with minimal explicit float math (1 fadd per pass)

The key insight: these passes are **purely integer-based ML convolutions** that
use the FP8→FP16 LUT to decode weights, then accumulate results in integer
registers, with only a final float conversion at the end.

### Post Passes — Pure Scatter

All 13 post passes (pass0_post through pass12_post) are trivial:
- Only 2–5 `rawBufferStore` operations
- 0 atomics, 0 loads from weights, 0 float math
- Only UAV s0r11 (scratch) + CBV s0r0 (params)
- **Purpose:** Read accumulated results from the scratch buffer and scatter
  them to the appropriate output plane positions. These are data rearrangement
  passes, not compute.

### Postpass — Output Composite

Mixed conventional + ML processing:
- 1580 atomics (ML component) + 146 fmul + 100 fadd (conventional component)
- Reads from 4 SRVs + writes to 7 UAVs
- 7 output UAVs suggests: RGB output, luma, temporal history update, debug,
  and possibly intermediate feature maps for the next frame

## Stack Buffer Sizes (Intermediate Tensor Dimensions)

The alloca sizes reveal the internal tensor shapes per pass:

| Pass | Allocations (i32 arrays) | Total bytes |
|------|--------------------------|-------------|
| pass1, pass2, pass12 | 16, 16, 32, 32, 32, 64, 64, 72 | 1,312 |
| pass3 | 32 | 128 |
| pass4, pass5, pass10 | 32, 64, 64, 64, 64, 72, 128, 128 | 2,464 |
| pass6 | 64 | 256 |
| pass7, pass8 | 64, 128, 128, 144, 256, 256, 256, 256 | 5,952 |
| pass9 | 32, 64, 64 | 640 |
| pass11 | 32, 32 | 256 |

The allocation pattern shows **3 tiers of model complexity**:
1. **Small** (pass1/2/12): ~1.3KB stack — 72-element working set
2. **Medium** (pass4/5/10): ~2.5KB stack — 128-element working set
3. **Large** (pass7/8): ~6KB stack — 256-element working set

The pass7/8 passes are the deepest layers with 256-wide intermediate tensors,
likely the most computationally expensive layers in the network.

## Loop Structure

| Pass | Phi Nodes | Loop Structure |
|------|-----------|----------------|
| prepass | 1 | Single flat loop |
| pass1/2/12 | 12 | 3×3 nested loop (9 iterations) |
| pass3 | 3 | Small loop |
| pass4/5/10 | 16 | 4×4 nested loop (16 iterations) |
| pass6 | 3 | Small loop |
| pass7/8 | 20 | 5×4 nested loop (20 iterations) |
| pass9 | 132 | Deep nested loop — heaviest control flow |
| pass11 | 75 | Deep nested loop |
| postpass | 65 | Moderate loop |
| all post passes | 5 | Minimal loop (5 phis) |

The nested loop counts directly correspond to the convolution kernel sizes:
- 3×3 = 9 iterations (pass1/2/12 — small 3×3 convolutions)
- 4×4 = 16 iterations (pass4/5/10 — medium convolutions)
- 5×4 = 20 iterations (pass7/8 — large convolutions)

This suggests the network uses a mix of convolution kernel sizes, with the
deepest layers using 5×4 kernels.

## Weight Access Pattern

All core ML passes access weights from the same SRV (space=0, reg=18) which
maps to the InitializerBuffer containing FP8 quantized weights.

The `dx.op.tertiary.i32(i32 49, stride, dim1, dim2)` call is a mad (multiply-add)
used to compute the weight offset:
```
weight_offset = stride * dim1 + dim2 + constant_base
```

The three variants per pass use different `constant_base` values:
- Variant A: 15392
- Variant B: 30752
- Variant C: 61472

These are the offsets into the 128KB (0x20000 byte) weight blob for each quality
preset's weights.

## Complete Resource Binding Map

### Prepass
| Type | Space | Register | Resource |
|------|-------|----------|----------|
| Sampler | 0 | 0 | Bilinear sampler |
| SRV | 0 | 18 | InitializerBuffer (weights) |
| SRV | 1 | 0 | Input color |
| SRV | 2 | 1 | Motion vectors |
| SRV | 3 | 2 | Depth/luma |
| SRV | 4 | 3 | Extra features |
| SRV | 5 | 4 | History |
| UAV | 0 | 11 | ScratchBuffer |
| UAV | 1 | 0 | Output feature plane |
| UAV | 2 | 3 | Output feature plane |
| CBV | 0 | 1 | Parameters |

### Core ML Passes (pass1–pass12)
| Type | Space | Register | Resource |
|------|-------|----------|----------|
| SRV | 0 | 18 | InitializerBuffer (FP8 weights) |
| UAV | 0 | 11 | ScratchBuffer (scatter target) |
| UAV | 1 | 0 | ScratchBuffer (FP8 decode LUT) |
| CBV | 0 | 0 | Dispatch parameters |

### Post Passes (pass0_post–pass12_post)
| Type | Space | Register | Resource |
|------|-------|----------|----------|
| UAV | 0 | 11 | ScratchBuffer |
| CBV | 0 | 0 | Dispatch parameters |

### Postpass
| Type | Space | Register | Resource |
|------|-------|----------|----------|
| SRV | 0 | 18 | InitializerBuffer |
| SRV | 1 | 3 | Feature plane |
| SRV | 2 | 6 | Feature plane |
| SRV | 3 | 9 | Feature plane |
| UAV | 0 | 11 | ScratchBuffer |
| UAV | 1 | 0 | Output |
| UAV | 2 | 1 | History output |
| UAV | 3 | 2 | Debug/intermediate |
| UAV | 4 | 6 | Intermediate |
| UAV | 5 | 9 | Intermediate |
| UAV | 6 | 12 | Intermediate |
| CBV | 0 | 1 | Parameters |

## What We Still Don't Know

1. **Exact activation functions** — The integer-only accumulation makes it hard
   to identify activation functions (ReLU, GELU, etc.) without tracing the LUT
   contents. The LUT could encode activation curves.

2. **Temporal state flow** — We know the pipeline is recurrent (13 pre/post pairs)
   but haven't traced how temporal history feeds from one frame's output back
   into the next frame's input.

3. **Skip connections** — The pass symmetry (pass1≈pass2≈pass12) suggests
   possible skip connections or parameter sharing, but this needs confirmation
   from the dispatch order at runtime.

4. **Exact channel counts** — The stack buffer sizes give us tensor dimensions
   in i32 elements, but without knowing the packing (4 values per i32 for FP8,
   2 for FP16), the actual channel count is ambiguous.

5. **Attention mechanism** — No clear attention patterns (softmax, QKV) visible
   in the integer-only computation. The architecture may be purely convolutional.

## Data Flow Summary

```
Input Color → Prepass (feature extraction with bilinear sampling)
    ↓
Pass1 (3×3 conv, FP8→FP16 via LUT) → Pass1_post (scatter)
    ↓
Pass2 (3×3 conv) → Pass2_post (scatter)
    ↓
Pass3 (specialized, small) → Pass3_post (scatter)
    ↓
Pass4 (4×4 conv) → Pass4_post (scatter)
    ↓
Pass5 (4×4 conv) → Pass5_post (scatter)
    ↓
Pass6 (weight decode heavy) → Pass6_post (scatter)
    ↓
Pass7 (5×4 conv, deepest) → Pass7_post (scatter)
    ↓
Pass8 (5×4 conv, deepest) → Pass8_post (scatter)
    ↓
Pass9 (deep loop, specialized) → Pass9_post (scatter)
    ↓
Pass10 (4×4 conv) → Pass10_post (scatter)
    ↓
Pass11 (deep loop) → Pass11_post (scatter)
    ↓
Pass12 (3×3 conv) → Pass12_post (scatter)
    ↓
Postpass (ML + conventional composite) → Output
```

Each "post" pass is a trivial scatter — the real computation is in the main pass.
The pattern suggests a **U-Net-like architecture** where features are processed
through progressively deeper layers, then reconstructed.
