# Validation Status — FSR 4.1.0 Reverse Engineering

> **Honest assessment of what is proven, what is inferred, and what remains open.**
>
> This document replaces all prior validation claims. It was rewritten after
> cross-referencing every doc, spec, and analysis artifact in this repository
> against the raw DXIL IR (1187 LLVM IR files).

## Evidence Tiers

| Symbol | Meaning |
|--------|---------|
| ✅ | Verified — direct observation, reproducible |
| ⚠️ | Static-only — derived from binary analysis, not runtime-verified |
| 🔶 | Inferred — reasonable conclusion from indirect evidence |
| ❌ | Unresolved — genuine gap, requires additional work |

---

## Architecture

### ✅ Model Identity
- Internal name: `fsr4_model_v07_fp8_no_scale` — confirmed in DXIL entry points
- Internal codename: MLSR — from Ghidra debug string
- Version v07 shared between 4.0.2 and 4.1.0 — matching entry point names
- Build date: March 20, 2026 — from Ghidra debug string
- Git commit: `abd3160` — from Ghidra debug string

### ✅ Network Topology
- Sequential encoder → bottleneck → decoder pipeline
- Channel flow: **7 → 16 → 32 → 64 → 128 → 64 → 32 → 16 → 8**
- Spatial pyramid: 1.0× → 0.5× → 0.25× → 0.125× → 0.25× → 0.5× → 1.0×
- All 78 tensors mapped with exact shapes and offsets (from 4.0.2 HLSL source)
- Source: 4.0.2 HLSL source + tensor-map.json (78 entries, all shapes confirmed)

### ✅ Channel Dimensions
- Fully resolved for every layer via tensor-map.json
- encoder1: 7→16ch, encoder2: 16→32ch, encoder3: 32→64ch
- bottleneck: 64→128→64ch, decoder3: 64→32ch, decoder2: 32→16→8ch
- Weight tensor shapes confirmed (e.g. `[2,2,7,16]`, `[3,3,16,16]`, `[1,1,64,128]`)
- Alloca sizes in DXIL corroborate: 72-element stacks (pass1/2/12), 128-element (pass4/5/10), 256-element (pass7/8)

### ✅ Residual Block Architecture
- Variant A (encoder2, decoder2): DepthwiseConv 3×3 → PointwiseExpand → PointwiseContract
- Variant B (encoder3, bottleneck, decoder3): SpatialMixingPartialConv → PointwiseExpand → PointwiseContract
- Both variants: element-wise residual add
- Source: 4.0.2 HLSL source + tensor naming convention

### ✅ Dispatch Pipeline
- 27 compute dispatches per frame (loop counter `0x1b`)
- 1 prepass + 12 core ML passes × 2 (pass + scatter) + 1 postpass + 1 SPD = 27
- Source: Ghidra decompilation of dispatch function

---

## Weight Data

### ✅ Weight Blob Locations
- 6 blobs × 131,072 bytes each, found via LEA tracing in Ghidra
- Only 2 unique blobs: 5 presets share identical weights, only DRS differs
- MD5-verified

### ✅ Weight Extraction
- All 6 blobs extracted from DLL via pefile RVA resolution
- Weight blobs byte-identical between workdrive copy and desktop repo

### ✅ Data DLL Bit-Identical Rebuild
- `fsr_data.dll` reconstructed from C source + weight blobs
- MD5 verified: `cb1aa61c71c33b25549ed59c1551d661` (original == rebuilt)
- Note: exact byte match requires PE patcher step; GCC version affects pre-patch output

### ✅ Blob Format
- v4.0.2: 130,088 bytes (7,208 bytes FP16 biases + 122,880 bytes FP8 weights)
- v4.1.0: 131,072 bytes (same zones + 984 bytes extra, including 444 FP16 scale factors)

### ✅ Weight Retrain Confirmation
- 98.7% of bytes changed between 4.0.2 and 4.1.0
- 4.0.2: 122 unique FP8 values (clustered codebook)
- 4.1.0: 255 unique FP8 values (full uint8 range)
- Byte-by-byte diff analysis completed

---

## Shader Internals

### ✅ FP8 Decode Mechanism (DXIL IR analysis)
- Shaders use `atomicCompareExchange` (dx.op 79) as side-effect-free LUT reads
- 3 LUT regions identified by offset patterns:
  - `0x500000XX`: scale factor lookup
  - `0x51000AXX`: secondary decode lookup
  - `0x520002XX`–`0x52001XXX`: 8-entry FP8 decode table (0x100 stride within groups)
- Pattern: 1 FP8 byte → 8 decoded FP16 values via LUT
- Source: DXIL IR analysis of all 12 core passes (1187 .ll files)

### ✅ Pass Complexity Tiers
- Small (pass1/2/12): ~1.3KB stack, 1989 atomics, 3×3-equivalent loops
- Medium (pass4/5/10): ~2.5KB stack, 3296 atomics, 4×4-equivalent loops
- Large (pass7/8): ~6KB stack, 9088 atomics, 5×4-equivalent loops
- Specialized (pass3/6/9/11): unique roles, varying complexity
- Source: alloca sizes + atomic counts from DXIL IR

### ✅ Post Passes = Pure Scatter
- All 13 post passes: 0 atomics, 0 weight loads, 0 float math, 2–5 rawBufferStore ops
- Confirmed in DXIL IR — pure data rearrangement

### ✅ "no_scale" Designation
- Means "no per-tensor scale tensor in the main weight path"
- The 444 extra FP16 values in v4.1.0 are likely quantization scale factors
- Not a claim that all scale-related parameters vanished

---

## Skip Connections

### ⚠️ No Skip Connections (90% confidence)

**Evidence against (4 independent sources):**

1. **Resource name table** (Ghidra): Only `r_input_color` and `rw_mlsr_output_color` in 12-entry SRV table — no skip resource names
2. **Binding resolver** (Ghidra): Fixed table match, no encoder-specific output names
3. **PSV0 metadata** (pefile): All 12 model passes have byte-identical resource binding metadata
4. **Dispatch loop** (Ghidra): Flat sequential loop, no code path for non-consecutive pass output binding

**What this doesn't prove:** Runtime GPU resource bindings were not captured.

**Architecture note:** The pass symmetry (pass1≈pass12, pass4≈pass10, pass7≈pass8) is consistent with a bottleneck autoencoder — the symmetric structure comes from decoder mirroring the encoder, not from skip connections. Without skip connections, this is technically a **bottleneck autoencoder**, not a U-Net (U-Net requires skip connections by definition).

---

## Activation Functions

### ❌ Exact Activation Function — PARTIALLY NARROWED

**What we can state definitively (from DXIL IR analysis of all 12 core passes):**

1. **No explicit activation operation in IR.** Zero instances of `SMax`, `SMin`, `UMin`, `UMax` (dx.op 35–38) across all 12 passes. Zero `icmp` + `select` clamp patterns. Zero `fcmp` comparisons.

2. **No float-domain activation.** Zero `fmul`, zero `fcmp` in core passes. The only float operation is 1 `fadd` per pass (pass1/2/4/5/7/8/10/12) or 0–4 `fadd` (pass3/6/9/11) — these are late in the SSA chain (output stage), likely bias addition or coordinate computation.

3. **Computation is purely integer.** All math is `add`, `mul`, `shl`, `lshr`, `and`, `or` + LUT lookups via `atomicCompareExchange`. The `or` ops are offset computation; the `and` ops are modulo masks for circular addressing.

4. **This rules out:** Sigmoid, tanh, GELU, Swish, Mish — all require float transcendental functions that would appear as `fmul`/`fdiv`/library calls in the IR.

**Most likely explanation:**

The activation function is **ReLU-family (ReLU or ReLU6)**, **folded into the FP8 decode LUT**. In quantized inference, fusing `activation(dequantize(weight))` into a single LUT is a standard optimization: the 256-entry LUT pre-computes the activation curve for all possible FP8 byte values, so no separate clamp operation is needed in the shader.

**What would close this gap:** Runtime capture of the LUT contents (populated in the scratch buffer before shader dispatch). The LUT values would directly reveal the activation curve shape.

---

## Temporal State Flow

### ✅ Resolved — History Buffer Feedback (not RNN recurrence)

**The temporal mechanism is a TAA-style history buffer, not neural network recurrence:**

1. **Postpass** writes to UAV (space=2, reg=1) via `textureStore.f32` — this is the "History output"
2. **Prepass** reads from SRV (space=5, reg=4) — this is the "History" input
3. The neural network itself (pass1–pass12) has **no temporal/recurrent connections** — zero temporal/history/prev tensors in the 78-tensor map
4. History feedback happens at the **pipeline level**, not within the network

**Mechanism:** Frame N's postpass output → stored as history → frame N+1's prepass reads it as a 7th input feature alongside color, motion vectors, and depth. This is identical to temporal anti-aliasing's jitter/reproject/history pattern.

---

## Attention Mechanism

### ⚠️ No Evidence of Attention (cannot fully rule out)

**Evidence against:**
- Zero `fmul` in core passes — softmax (required for attention) needs float multiply
- No QKV-pattern tensor names in 78-tensor map
- Architecture matches MobileNet-style CNN, not transformer

**Why we can't rule it out completely:**
- All computation goes through integer LUT. If attention weights were stored as FP8 and decoded through the same LUT, there would be no visible softmax pattern. (Per adversarial review #2)

**Practical assessment:** The architecture is almost certainly pure convolutional. The model name `fsr4_model_v07` and the MobileNet-style block structure strongly indicate a CNN. The "cannot rule out" caveat is theoretical, not practical.

---

## Genuinely Unresolved

| # | Gap | Status | What would close it |
|---|-----|--------|---------------------|
| 1 | Exact activation variant (ReLU vs ReLU6 vs other) | Narrowed to ReLU-family, likely LUT-folded | Runtime LUT content capture |
| 2 | Runtime cbuffer offset values | Assumed identical to 4.0.2 HLSL offsets (85% confidence) | D3D12 hook deployment |
| 3 | 444 extra FP16 parameters purpose | Statistical analysis suggests quantization scale factors (70% confidence) | Shader tracing |
| 4 | Provider DLL bit-identical rebuild | Never attempted (~15.6MB compiled C++) | Full decompilation + recompilation |
| 5 | FP8 LUT mechanism verification | Pattern analysis suggests side-effect-free reads, not confirmed at runtime | GPU debugging / PIX capture |

---

## Previously Listed as Unresolved — Now Resolved

These items were listed as gaps in earlier documentation but are actually documented with evidence in this repository:

| Item | Previous status | Actual status | Evidence location |
|------|----------------|---------------|-------------------|
| Channel dimensions | ❌ Unresolved | ✅ Fully resolved | tensor-map.json + architecture.md |
| Skip connections | ❌ Unresolved | ⚠️ Resolved (90% no) | architecture.md (4 evidence sources) |
| Temporal state flow | ❌ Unresolved | ✅ History buffer feedback | shader-internals.md + DXIL IR |
| "no_scale" designation | ❌ Unresolved | ✅ No per-tensor scale in weight path | shader-internals.md |
| Attention mechanism | ❌ Unresolved | ⚠️ No evidence, theoretical possibility only | adversarial-review-2.md + DXIL IR |

---

## Summary

**Confidence by area:**

| Area | Confidence | Basis |
|------|-----------|-------|
| Weight blob locations + extraction | 99% | Direct LEA tracing, pefile verification, MD5 match |
| 78-tensor offset map (4.0.2) | 99% | Parsed from MIT-licensed source |
| Network architecture topology | 95% | HLSL source + DXIL entry point match |
| Channel dimensions | 99% | tensor-map.json with all 78 shapes |
| FP8 decode mechanism | 85% | DXIL IR pattern analysis (runtime not confirmed) |
| No skip connections | 90% | 4 independent static evidence sources |
| Temporal = history buffer | 95% | DXIL IR shows read/write paths, no recurrent tensors |
| Activation = ReLU-family, LUT-folded | 75% | Negative evidence (ruled out float activations), inferred mechanism |
| Architecture unchanged 4.0.2→4.1.0 | 95% | Same entry points, same tensor count, same blob layout |
| Weight retrain confirmation | 99% | 98.7% byte diff, uniform across layers |

**Bottom line:** The RE is structurally complete. The architecture is fully mapped. The 5 remaining gaps are either runtime-verification needs (items 2, 5), a specific function identification (item 1), a parameter purpose (item 3), or an engineering task (item 4). None of these gaps undermine the core findings.
