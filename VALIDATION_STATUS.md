# Validation Status — FSR 4.1.0 Reverse Engineering

> **Canonical truth file for claim status. All other docs should reference this
> file, not restate conclusions.**
>
> Confidence values and status tiers are kept in sync with `claims.json`
> (machine-queryable) and `CURRENT_STATUS.md` (one-glance summary). If any
> conflict exists between this file and those two, the more conservative
> assessment wins.

## Evidence Tiers

| Symbol | Meaning | Claims.json status |
|--------|---------|-------------------|
| ✅ | Verified — reproducible from committed static artifacts | `verified_static` |
| ⚠️ | Static-only — derived from binary analysis, not runtime-verified | `inferred` (high confidence) |
| 🔶 | Inferred — reasonable conclusion from indirect evidence | `inferred` (lower confidence) |
| ❌ | Unresolved — genuine gap, requires additional work | `unresolved` |

**Key distinction:** "Verified" in this repo means reproducible from static
artifacts (committed blobs, DXIL IR, hash checks). It does NOT mean runtime-observed.
Runtime validation has not been performed and is the primary open gap.

---

## Architecture

### ✅ Model Identity
- Internal name: `fsr4_model_v07_fp8_no_scale` — confirmed in DXIL entry points
- Internal codename: MLSR — from Ghidra debug string
- Version v07 shared between 4.0.2 and 4.1.0 — matching entry point names
- Build date: March 20, 2026 — from Ghidra debug string
- Git commit: `abd3160` — from Ghidra debug string
- Confidence: 0.98 (verified_static)

### 🔶 Network Topology (inferred, confidence 0.55)
- Sequential encoder → bottleneck → decoder pipeline
- Channel flow: 7 → 16 → 32 → 64 → 128 → 64 → 32 → 16 → 8
- Spatial pyramid: 1.0× → 0.5× → 0.25× → 0.125× → 0.25× → 0.5× → 1.0×
- All 78 tensors mapped with exact shapes and offsets (from 4.0.2 HLSL source)
- Source: 4.0.2 HLSL source + tensor-map.json (78 entries)
- **What this doesn't prove:** Topology is inferred from static analysis of
  DXIL atomics/allocas/phi counts and the 4.0.2 source. Kernel sizes are inferred
  from phi-node patterns, not extracted. U-Net label is unsupported (no
  skip-connection evidence). Attention mechanisms cannot be fully ruled out under
  integer-only computation.

### ⚠️ Channel Dimensions (static, confidence 0.6)
- Channel dimensions come from MIT-licensed 4.0.2 source, but their exact
  applicability to 4.1.0 blob regions is a plausibility check, not a runtime proof
- encoder1: 7→16ch, encoder2: 16→32ch, encoder3: 32→64ch
- bottleneck: 64→128→64ch, decoder3: 64→32ch, decoder2: 32→16→8ch
- Alloca sizes in DXIL corroborate: 72-element stacks (pass1/2/12), 128-element (pass4/5/10), 256-element (pass7/8)
- **What this doesn't prove:** Runtime tensor shapes were never captured.

### ⚠️ Residual Block Architecture (static, confidence 0.6)
- Variant A (encoder2, decoder2): DepthwiseConv 3×3 → PointwiseExpand → PointwiseContract
- Variant B (encoder3, bottleneck, decoder3): SpatialMixingPartialConv → PointwiseExpand → PointwiseContract
- Both variants: element-wise residual add
- Source: 4.0.2 HLSL source + tensor naming convention
- **What this doesn't prove:** Architecture is inferred from 4.0.2 source and
  static analysis. Kernel sizes are hedged per adversarial review.

### ⚠️ Dispatch Pipeline (static/inferred, confidence 0.75)
- 27 model-loop host descriptor slots per frame (loop counter `0x1b`)
- Framed as a 27-iteration model loop with optional SPD AutoExposure before and
  optional RCAS / Debug View after
- The exact mapping from descriptor-table index → DXIL entrypoint is documented in
  `docs/pass-index-to-entrypoint-map.md` but is not yet runtime-confirmed
- Source: Ghidra decompilation of dispatch function
- **What this doesn't prove:** Runtime dispatch order, conditional pass
  suppression, and actual GPU resource bindings were never observed. Conditional
  flags may reorder or suppress passes at runtime.

---

## Weight Data

### ✅ Weight Blob Locations (verified_static, confidence 0.98)
- 6 blobs × 131,072 bytes each, found via LEA tracing in Ghidra
- Only 2 unique blobs: 5 presets share identical weights, only DRS differs
- MD5 + SHA-256 verified; re-extraction reproduces byte-for-byte

### ✅ Weight Extraction (verified_static, confidence 0.98)
- All 6 blobs extracted from DLL via pefile RVA resolution
- Weight blobs byte-identical between workdrive copy and desktop repo

### ⚠️ Data DLL Section Comparison (verified_static, confidence 0.6)
- `fsr_data.dll` reconstructed from C source + extracted weight blobs
- Section hashes compared independently; data section matches by construction
- The historical "bit-identical" MD5 match depended on copying original PE regions
  before comparing — this is circular and is no longer claimed as proof
- See `rebuild/README.md` for honest per-section comparison via `compare_sections.py`
- **What this doesn't prove:** Byte equality is not claimed. Runtime API
  equivalence is untested.

### ✅ Blob Format (verified_static, confidence 0.9)
- v4.0.2: 130,088 bytes (7,208 bytes FP16 biases + 122,880 bytes FP8 weights)
- v4.1.0: 131,072 bytes (same zones + 888 bytes extra = 222 FP32 output biases + 96B pad)

### ✅ Weight Retrain Confirmation (verified_static, confidence 0.99)
- 98.7% of bytes changed between 4.0.2 and 4.1.0
- 4.0.2: 122 unique FP8 values (clustered codebook)
- 4.1.0: 255 unique FP8 values (full uint8 range)
- Byte-by-byte diff analysis completed

---

## Shader Internals

### 🔶 FP8 / Integer-Domain Quantization (inferred, confidence 0.7)
- Weights are stored as uint8 values (255 unique values in 4.1.0)
- Shaders use `atomicCompareExchange` (dx.op 79) as coherent cross-thread-group buffer I/O
- 3 offset regions identified: `0x500000XX` (scale factor), `0x51000AXX` (secondary decode),
  `0x520002XX`–`0x52001XXX` (8-entry decode table with 0x100 stride)
- The fp8_no_scale path is byte-quantized and INT8-compatible: weights are stored as
  uint8, loaded in packed i32 form via rawBufferLoad.i32, and processed through
  integer-domain arithmetic before float reinterpretation
- Source: DXIL IR analysis of all 12 core passes (1187 .ll files)
- **What this doesn't prove:** Exact signedness and complete MAC semantics still
  need a dedicated proof artifact. The atomic mechanism may be a read, a
  stateful write, or a compiler artifact — alternative explanations are not ruled out.

### ⚠️ Pass Complexity Tiers (static, confidence 0.8)
- Small (pass1/2/12): ~1.3KB stack, 1989 atomics, consistent with 3×3
- Medium (pass4/5/10): ~2.5KB stack, 3296 atomics, consistent with 4×4
- Large (pass7/8): ~6KB stack, 9088 atomics, consistent with 5×4
- Specialized (pass3/6/9/11): unique roles, varying complexity
- Source: alloca sizes + atomic counts from DXIL IR
- **What this doesn't prove:** Kernel sizes are inferred from phi-node counts,
  not extracted. The "consistent with" language is deliberate.

### ✅ Post Passes = Pure Scatter (verified_static, confidence 0.97)
- All 13 post passes: 0 atomics, 0 weight loads, 0 float math, 2–5 rawBufferStore ops
- Confirmed in DXIL IR — pure data rearrangement

### ✅ "no_scale" Designation (verified_static)
- Means "no per-tensor scale tensor in the main weight path"
- The extra 888-byte region in v4.1.0 is 222 FP32 output composition / scale parameters
  consumed by postpass
- Not a claim that all scale-related parameters vanished

---

## Skip Connections

### ⚠️ No Skip Connections (static, confidence 0.7)

**Evidence against (4 independent static sources):**

1. **Resource name table** (Ghidra): Only `r_input_color` and `rw_mlsr_output_color` in 12-entry SRV table
2. **Binding resolver** (Ghidra): Fixed table match, no encoder-specific output names
3. **PSV0 metadata** (pefile): All 12 model passes have byte-identical resource binding metadata
4. **Dispatch loop** (Ghidra): Flat sequential loop, no code path for non-consecutive pass output binding

**What this doesn't prove:** Runtime GPU resource bindings were not captured.
Without skip connections, the architecture is technically a bottleneck autoencoder,
not a U-Net.

---

## Activation Functions

### ✅ Exact Activation Function — ReLU (verified_static, confidence 0.99)

`dx.op.binary.f32(i32 35, x, 0.0)` = `FMax(x, 0.0)` = ReLU, present in 10 of 12 core passes.

Cross-validated via DXIL (`FMax`) and SPIR-V (`llvm.maxnum.f32`). 20 FMax instances
across core passes. Ruled out: ReLU6, LeakyReLU, Tanh/Sigmoid/GELU.

---

## Temporal State Flow

### ⚠️ History Buffer Feedback (static, confidence 0.8)

**Static evidence:** Postpass writes to UAV (space=2, reg=1) via `textureStore.f32`.
Prepass reads from SRV (space=5, reg=4). The network (pass1–pass12) has zero temporal
tensors in the 78-tensor map. History feedback happens at the pipeline level.

**What this doesn't prove:** Runtime resource binding was not observed. The TAA-style
history-buffer interpretation is inferred from static read/write paths.

---

## Attention Mechanism

### ⚠️ No Evidence of Attention (static, cannot fully rule out)

**Evidence against:** Minimal float ops (only FMax + bias fadd). No QKV-pattern tensor
names. Architecture matches MobileNet-style CNN.

**Why we can't rule it out:** All computation goes through integer LUT. If attention
weights were stored as FP8 and decoded through the same LUT, there would be no visible
softmax pattern. (Per adversarial review #2)

---

## Open Items

| # | Gap | Status |
|---|-----|--------|
| ~~1~~ | ~~Activation variant~~ | ✅ RESOLVED: ReLU (DXIL+SPIR-V, 0.99) |
| ~~2~~ | ~~Cbuffer offsets~~ | ⚠️ Substantially resolved from tensor-map (0.6 static) |
| ~~3~~ | ~~Extra parameters~~ | ✅ RESOLVED: 222 FP32 output biases (0.9 verified) |
| 4 | Provider DLL rebuild | ⚠️ Engineering task, not an analysis gap |
| ~~5~~ | ~~Quantization mechanism~~ | 🔶 Inferred (0.7): integer-domain, exact semantics open |
| 6 | **Runtime validation** | ❌ **UNRESOLVED — primary credibility gap** |
| 7 | **Descriptor→entrypoint mapping** | ⚠️ Documented but not runtime-confirmed |

**Static analysis is substantial but bounded.** It supports the published structural
claims with binary evidence, but it does not prove complete runtime behavior or
independent bit-identical binary reconstruction. Runtime validation has not been
performed and is the primary remaining credibility gap; confirming it would require
native Windows D3D12 capture with dispatch order, PSO hashes, descriptor tables,
CBV dumps, and resource transitions.

---

## Confidence Summary (aligned with claims.json)

| Area | Confidence | Status | Basis |
|------|-----------|--------|-------|
| Weight blob extraction + identity | 0.98 | verified_static | Direct LEA tracing, pefile, hash verification |
| DXIL entrypoint inventory (27 passes) | 0.97 | verified_static | Binary-hash comparison |
| Extra FP32 region (222 values) | 0.90 | verified_static | Finite/bounded FP32 parse |
| Activation = ReLU | 0.99 | verified_static | DXIL FMax + SPIR-V maxnum (20 instances) |
| Pipeline dispatch order | 0.75 | inferred | Ghidra decompilation; never runtime-observed |
| Quantization scheme (INT8-compatible) | 0.70 | inferred | DXIL IR; exact semantics open |
| No skip connections | 0.70 | inferred | 4 static sources; no runtime binding data |
| Tensor offset map (78 tensors) | 0.60 | inferred | Plausibility parse, not runtime addressing |
| Data DLL reconstruction | 0.60 | verified_static | Per-section comparison; no byte-equality claim |
| Network architecture topology | 0.55 | inferred | DXIL patterns + 4.0.2 source; kernels hedged |
| Runtime pass order | 0.00 | unresolved | No capture data |
| Runtime CBV values | 0.00 | unresolved | No capture data |

**Bottom line:** The static analysis is substantial but bounded. Runtime validation
is the primary open gap. This is an acknowledged limitation, not a claim of completion.

**Scope note:** This analysis covers the FSR 4 temporal upscaler only. FSR 4.1.0 also
includes frame generation, which was not analyzed and is outside scope.
