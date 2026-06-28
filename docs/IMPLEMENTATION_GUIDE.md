# Neural Upscaler Implementation Research Notes

> Research notes for reimplementing the quantized neural upscaler from
> static shader analysis. All information is derived from DXIL/SPIR-V IR.
> No proprietary source code is included.

---

## 1. Architecture Overview

### 1.1 Pipeline Stages

The upscaler is a 27-dispatch compute pipeline, all shaders using 32×1×1 thread groups:

| Stage | Dispatches | Function |
|-------|-----------|----------|
| Prepass | 1 | Input preprocessing (color space transform, feature extraction) |
| Core pass + scatter | 24 (12×2) | Quantized convolution network |
| Postpass | 1 | Output composition (inverse color space, temporal blend) |
| SPD | 1 | Image downsampling (standard single-pass downscaler) |

### 1.2 Network Topology

Sequential encoder→bottleneck→decoder CNN:

```
Input (7ch) → Encoder1 → Encoder2 → Encoder3 → Bottleneck → Decoder3 → Decoder2 → Output (8ch)
               16ch        32ch       64ch       128ch        64ch       32ch→16ch→8ch
```

Channel flow: **7 → 16 → 32 → 64 → 128 → 64 → 32 → 16 → 8**

Spatial pyramid: 1.0× → 0.5× → 0.25× → 0.125× → 0.25× → 0.5× → 1.0×

### 1.3 Core Pass Map

| Pass | Channels | Layer Type | Alloca (i32) | Atomics | FMax(ReLU) |
|------|----------|------------|-------------|---------|------------|
| pass1 | 7→16 | depthwise 3×3 | 72 | ~180 | 1 |
| pass2 | 16→16 | depthwise 3×3 | 72 | ~180 | 1 |
| pass3 | 16→16 | pointwise 1×1 | 72 | ~80 | 0 |
| pass4 | 16→32 | depthwise 3×3 | 128 | ~330 | 1 |
| pass5 | 32→32 | depthwise 3×3 | 128 | ~330 | 1 |
| pass6 | 32→32 | pointwise 1×1 | 128 | ~160 | 0 |
| pass7 | 32→64 | depthwise 4×4 | 256 | ~910 | 1 |
| pass8 | 64→64 | depthwise 4×4 | 256 | ~910 | 1 |
| pass9 | 64→128 | spatial mixing | 144+256 | ~520 | 8 |
| pass10 | 128→64 | depthwise | 128 | ~330 | 1 |
| pass11 | 64→32 | depthwise | 256 | ~500 | 4 |
| pass12 | 32→16 | depthwise | 72 | ~180 | 1 |

Passes 3, 6 have no ReLU (pointwise convolutions without activation).
Pass 9 has 8 ReLU calls (per-input-channel for the wider bottleneck layer).
Pass 11 has 4 ReLU calls (per-input-channel).

### 1.4 Scatter Passes

Each core pass is followed by a scatter pass (`passN_post`):
- ~124 lines each
- Zero math operations (0 fmul, 0 fadd, 0 atomics)
- 2 `rawBufferStore` calls per shader
- Pure data rearrangement (scatter results to correct buffer positions)

---

## 2. Weight Format

### 2.1 Blob Layout

Each quality preset has a 131,072-byte (128KB) weight blob:

| Region | Offset | Size | Content |
|--------|--------|------|---------|
| FP16 biases | 0 | 7,208 bytes | Per-layer bias values (FP16) |
| FP8 weights | 7,208 | 122,880 bytes | Quantized convolution weights |
| Extra params | 130,088 | 888 bytes | 222 FP32 output composition values |
| Padding | 130,976 | 96 bytes | Zero padding |

Total: 131,072 bytes = 128KB exactly.

### 2.2 FP8 Weight Encoding

Weights are stored as `uint8` values (256-entry codebook, 255 unique values in v4.1.0).
Each byte is a codebook index. The dequantization happens inside the shader via
integer arithmetic that computes IEEE 754 float32 bit patterns (see §4.2).

### 2.3 Weight Access Pattern

```
// Pseudocode for weight loading in core passes
uint weight_offset = mad(thread_id, stride, base_offset);
uint encoded = WeightBlob.Load(weight_offset);  // rawBufferLoad.i32 (4 bytes)
// encoded contains 4 uint8 weight indices packed into one i32
// These are used in integer multiply-accumulate (see §4.2)
```

### 2.4 Preset Sharing

6 quality presets exist. 5 share identical weight blobs. Only the highest quality
preset (DRS) has different weights. The network architecture is identical across presets.

---

## 3. Buffer Architecture

### 3.1 Resource Bindings

| Handle | Type | Space | Reg | Purpose |
|--------|------|-------|-----|---------|
| Weight blob | SRV | 0 | 18 | Quantized weights + params |
| Shared buffer | UAV | 0 | 11 | Cross-thread computation scratch |
| Compute buffer A | UAV | 1 | 0 | Accumulation buffer |
| Compute buffer B | UAV | 2 | 1 | Feature/history output |
| Compute buffer C | UAV | 2 | 3 | Prepass output (FP16 features) |
| Input color | SRV | 4 | 3 | Source frame |
| Motion vectors | SRV | 3 | 2 | Frame-to-frame motion |
| Depth | SRV | 2 | 1 | Scene depth |
| History | SRV | 5 | 4 | Previous frame output |
| CBV | CBV | 0 | 1 | Per-frame constants |

### 3.2 Coherent Buffer I/O (atomicCompareExchange)

The shaders use `atomicCompareExchange` (DXIL opcode 79) as a coherent buffer
access mechanism. In DXIL, this maps to LLVM `cmpxchg ptr, compare, exchange monotonic`.

Three patterns:

**Pattern 1 — Coherent Read:**
```hlsl
// HLSL equivalent
uint old_value;
InterlockedCompareExchange(buf[offset], 0, 0, old_value);
// old_value = current contents (unchanged since compare=0, exchange=0)
```

**Pattern 2 — Coherent Write:**
```hlsl
uint old_value;
InterlockedCompareExchange(buf[offset], expected, new_value, old_value);
// Atomically replaces expected with new_value
```

**Pattern 3 — Read-Activate-Write:**
```hlsl
// 1. Read accumulated value from buffer
uint raw;
InterlockedCompareExchange(buf[offset_A], counter, 0, raw);
// 2. Reinterpret as float and apply ReLU
float val = asfloat(raw);
float activated = max(val, 0.0);
// 3. Write activated result back
InterlockedCompareExchange(buf[offset_B], counter, asuint(activated), discarded);
```

### 3.3 Buffer Region Encoding

The shared computation buffer uses large offset values that encode regions:

| Hex prefix | Region | Purpose |
|-----------|--------|---------|
| 0x50xxxxxx | Gate/counter | Thread synchronization + weight offset passing |
| 0x51xxxxxx | Accumulation | Partial sums and activated results |
| 0x52xxxxxx | Feature data | Input features from previous pass |

The low 24 bits of each offset are the actual byte offset within the region.

---

## 4. Shader Implementation Details

### 4.1 DXIL Opcode Reference (Verified)

These opcodes are type-overloaded. The same number means different operations
for different types:

| Opcode | binary.f32 | binary.i32 | unary.f32 |
|--------|-----------|------------|-----------|
| 21 | — | — | **Exp2** |
| 23 | — | — | **Log2** |
| 27 | — | — | **Floor** |
| 35 | **FMax** | UMin | — |
| 36 | **FMin** | UMax | — |
| 37 | — | **IMin** | — |
| 38 | — | **IMax** | — |

| Opcode | tertiary.i32 |
|--------|-------------|
| 49 | **MAD** (multiply-add: a*b+c) |

Other key opcodes:
- 57: createHandle (resource binding)
- 59: cbufferLoadLegacy (constant buffer read)
- 66: textureLoad
- 67: textureStore
- 79: atomicCompareExchange
- 93: threadId
- 94: groupId
- 95: threadIdInGroup
- 139: rawBufferLoad

### 4.2 FP8 Dequantization and Convolution

The core passes perform convolution using integer arithmetic on quantized data.
The pipeline per thread:

```
1. Compute weight offset: mad(mad(idx, stride, channel_offset), 256, base)
2. Load 4 packed uint8 weights via rawBufferLoad.i32 from weight blob
3. Load input features from shared buffer (via atomicCompareExchange read)
4. Integer multiply-accumulate over kernel positions
5. Store partial sums to local alloca arrays
6. After accumulation loop:
   a. Read final accumulated value from shared buffer
   b. bitcast i32 → float32
   c. Apply ReLU: max(float_val, 0.0)
   d. bitcast float32 → i32
   e. Write activated result to shared buffer
```

**Key insight:** The integer multiply-accumulate operates on the raw weight byte
values. The result is a valid float32 bit pattern when reinterpreted via bitcast.
This is the quantization scheme: the weight encoding is designed so that integer
MAC on the codebook indices produces valid IEEE 754 float32 results.

**Tracing the exact MAC:** In the SPIR-V IR for pass7 (blob_0079.spirv.ll):
- Weight loads: lines 62-72, 223-233, 349-359 (one per kernel position)
- Each load reads from `@_dx_res_0_0_18` (weight blob) at computed offset
- Local computation: 254 `mul i32` + 413 `add i32` operations across the shader
- Final activation: lines 31149-31152 (bitcast → maxnum → bitcast)

### 4.3 Activation Function: ReLU

Activation is **ReLU** (`max(x, 0.0)`) applied in 10 of 12 core passes.

```hlsl
// HLSL implementation
float activated = max(value, 0.0);
```

Applied in the inner convolution loop, between the accumulation result and the
output buffer write. Passes 3 and 6 (pointwise convolutions) have no activation.

Cross-verified via DXIL (`binary.f32(35, x, 0.0)`) and SPIR-V (`llvm.maxnum.f32(x, 0.0)`).

### 4.4 CBV Architecture

Each core pass reads exactly one CBV slot:

```
pass1 → CBV slot 2
pass2 → CBV slot 3
pass3 → CBV slot 4
...
passN → CBV slot (N+1)
```

Each slot returns 4× i32 (16 bytes): base_offset, x_stride, y_stride, channel_count.
These values are derivable from the tensor map (same layout across versions).

---

## 5. Prepass Implementation

### 5.1 Function

The prepass transforms input color into neural-network-compatible features.

### 5.2 Color Space Transform (PQ EOTF)

Input pixels undergo SMPTE ST 2084 (PQ) perceptual quantizer decoding:

**Constants:**
```
m1 = 0.1593017578125
m2 = 78.84375
c1 = 0.8359375    (= c3 - c2 + 1)
c2 = 18.8515625
c3 = 18.6875
```

**PQ EOTF pipeline (per channel R, G, B):**
```hlsl
float pq_eotf(float N) {
    N = clamp(N, 0.0, 1.0);
    float N_pow = exp2(log2(N) / m2);   // N^(1/m2) via log2+exp2
    float num = max(N_pow - c1, 0.0);
    float den = c2 - c3 * N_pow;
    float L = exp2(log2(num / den) / m1);  // (num/den)^(1/m1)
    return max(L * 0.081375, 0.0);   // final scaling
}
```

**Verified from IR constants:**
- `1/m2 = 0.012683313515656` → matches `0x3F89F9B580000000`
- `1/m1 = 6.277394636015326` → matches `0x40191C0D60000000`
- `c1 = 0.8359375` → matches `0xBFEAC00000000000` (negated for subtraction)
- `c2 = 18.8515625` → matches `0x4032DA0000000000`
- `c3 = 18.6875` → matches `1.868750e+01`
- Final scale = `0.081375` → matches `0x3FB4D50600000000`

### 5.3 Input Processing

```
Inputs (per pixel):
  - Color (RGB, SRV 4:3): 4 neighborhood samples (2×2 bilinear)
  - Motion vectors (SRV 3:2): 8 neighborhood samples
  - Depth (SRV 2:1): 1 sample
  - CBV slot 1: scale/offset for coordinate transform
  - CBV slot 0: additional camera params

Output (per pixel):
  - PQ-transformed color features (FP16, UAV 2:3)
  - Written as 4-component half4 (RGBA, alpha = red)
  - 2 pixels written per thread iteration
```

### 5.4 Dispatch

Thread groups: 32×1×1. Each thread processes one spatial position with a 2×2
neighborhood of texture loads, producing 2 output pixels.

---

## 6. Postpass Implementation

### 6.1 Function

The postpass composes the 8-channel decoder output into final RGB pixels,
applies inverse color space transform, and performs temporal history blending.

### 6.2 Data Sources

```
- Weight blob (SRV 0:18): 222 FP32 output composition params at offset 130,304+
- Shared buffer (UAV 0:11): 8-channel decoder output
- Intermediate textures: previous pass results
- History texture (SRV 3:9): previous frame output (FP16)
- CBV: per-frame constants
```

### 6.3 Output Composition Pipeline

```hlsl
// 1. Load 8 decoder channels from shared buffer (via atomicCompareExchange)
// 2. Load 8 FP32 bias values from weight blob extra params region
// 3. Add biases to decoder output
float3 composed = decoder_output.rgb + output_biases.rgb;

// 4. Load depth-based modulation
float3 depth_mod = textureLoad(depth_tex, coords);
depth_mod = exp2(depth_mod * 6.277) * 0.081375;  // PQ-like transform
depth_mod = max(depth_mod, 0.0);
composed += depth_mod * modulation_weight;

// 5. Normalize
float sum = composed.r + composed.g + composed.b + w;
composed /= sum;

// 6. Temporal blend (sigmoid-based)
float blend_factor = 1.0 - 1.0 / (1.0 + exp2(-input_alpha * 1.4427));
float3 history = textureLoad(history_tex, coords);  // FP16 → FP32
float3 output = history * (1.0 - blend_factor) + composed * blend_factor;
```

**Sigmoid implementation** (verified from IR):
```
blend = 1 - 1/(1 + exp2(-x * log2(e)))
      = 1 - 1/(1 + 2^(-x * 1.4427))
where log2(e) = 1.44269504... (IR constant 0xBFF7154760000000)
```

### 6.4 Output Writes

4 textures written per output pixel:

| UAV | Space:Reg | Format | Content |
|-----|-----------|--------|---------|
| History alpha | 5:9 | FP32 | Blend factor (scalar, replicated RGBA) |
| Output color | 2:1 | FP32 | Final blended RGB |
| Clamped output | 4:6 | FP32 | RGB clamped to [0, 64000] |
| FP16 intermediate | 6:12 | FP16 | Half-precision RGB for downstream passes |

**Clamp constant:** `FMin(value, 64000.0)` on all three output channels.

### 6.5 Dispatch

Processes 2×2 output pixel tiles per thread iteration.

---

## 7. Temporal Feedback

### 7.1 History Buffer

The upscaler uses TAA-style temporal accumulation (not RNN recurrence):

```
Frame N:
  Prepass reads History (SRV 5:4) as 7th input feature
  → Core network processes [color, motion, depth, history, ...]
  → Postpass blends neural output with reprojected history
  → Postpass writes new History (UAV 2:1) for Frame N+1
```

### 7.2 No Skip Connections

4 independent evidence sources confirm no encoder-to-decoder skip connections:
1. Resource name table: only input/output names, no skip resources
2. Binding resolver: fixed table, no encoder-specific outputs
3. PSV0 metadata: all 12 passes have identical resource bindings
4. Buffer analysis: no cross-layer data paths outside the sequential pipeline

---

## 8. IR File Reference

### 8.1 Blob-to-Shader Mapping

| Blob File | Shader | Lines | Key Content |
|-----------|--------|-------|-------------|
| blob_0001.ll | prepass | 2267 | PQ EOTF, feature extraction |
| blob_0036.ll | pass1 | 3620 | 7→16ch depthwise conv |
| blob_0058.ll | pass2 | ~3600 | 16→16ch depthwise conv |
| blob_0116.ll | pass3 | ~1200 | 16→16ch pointwise (no activation) |
| blob_0112.ll | pass4 | ~4600 | 16→32ch depthwise conv |
| blob_0013.ll | pass5 | ~4600 | 32→32ch depthwise conv |
| blob_0017.ll | pass6 | ~2400 | 32→32ch pointwise (no activation) |
| blob_0079.ll | pass7 | ~48000 | 32→64ch depthwise conv (largest pass) |
| blob_0108.ll | pass8 | ~48000 | 64→64ch depthwise conv |
| blob_0104.ll | pass9 | ~3500 | 64→128ch spatial mixing (8 ReLU) |
| blob_0053.ll | pass10 | ~4600 | 128→64ch depthwise conv |
| blob_0030.ll | pass11 | ~5200 | 64→32ch depthwise conv (4 ReLU) |
| blob_0054.ll | pass12 | ~3600 | 32→16ch depthwise conv |
| blob_0007.ll | postpass | 2674 | Output composition, temporal blend |
| blob_NNNN.ll | passN_post | ~124 | Scatter (data rearrangement) |

### 8.2 SPIR-V Cross-Reference

A SPIR-V translation exists for pass7 (`blob_0079.spirv.ll`, 3.3MB) providing
independent verification of DXIL opcode mappings via native LLVM intrinsics.

---

## 9. Implementation Checklist

To write HLSL compute shaders from these notes (currently incomplete — see Remaining Tracing Work):

### Phase 1: Scaffolding
- [ ] Define root signature with all resource bindings (§3.1)
- [ ] Create weight blob loader (§2)
- [ ] Implement CBV constant layout per pass (§4.4)

### Phase 2: Prepass
- [ ] Implement PQ EOTF (§5.2) — exact constants verified
- [ ] Implement coordinate transform using CBV slot 1
- [ ] Implement 2×2 neighborhood sampling
- [ ] Write FP16 output to UAV 2:3

### Phase 3: Core Passes
- [ ] Implement coherent buffer I/O wrapper (§3.2)
- [ ] Implement weight loading from blob (§4.2)
- [ ] Implement integer MAC convolution loop
  - Trace exact mul/add operations in each blob_NNNN.ll
  - The IR is complete — every instruction is present
- [ ] Implement ReLU activation (§4.3)
- [ ] Implement scatter passes (rawBufferStore × 2)

### Phase 4: Postpass
- [ ] Implement 222 FP32 param loading from blob offset 130,304
- [ ] Implement output composition with biases (§6.3)
- [ ] Implement sigmoid temporal blend (§6.3)
- [ ] Implement 4 output writes with correct formats (§6.4)

### Phase 5: Dispatch
- [ ] 27 dispatches per frame in order: prepass → (pass+scatter)×12 → postpass → SPD
- [ ] Thread groups: 32×1×1 for all passes

### Remaining Tracing Work

The DXIL IR contains every operation needed. These specific sections need
close reading to extract the exact arithmetic:

1. **Integer MAC formula** (pass7, blob_0079.spirv.ll lines 200-31149):
   The 254 `mul i32` and 413 `add i32` operations encode the full convolution.
   Trace which values are weight indices vs. input features vs. accumulation.

2. **Buffer offset computation**: The `mad` chains that compute offsets into the
   shared buffer encode the spatial/channel addressing. Extract the stride
   formulas from the first 100 lines of each pass.

3. **Weight blob indexing**: The offset computation before each `rawBufferLoad`
   from the weight blob encodes the weight tensor layout. Map these to the
   tensor-map.json dimensions.

---

## 10. Version Differences (4.0.2 → 4.1.0)

| Property | 4.0.2 | 4.1.0 |
|----------|-------|-------|
| Entry point name | Same (v07) | Same (v07) |
| Blob size | 130,088 bytes | 131,072 bytes |
| Extra params | None | 222 FP32 + 96 bytes padding |
| Unique FP8 values | 122 | 255 |
| Byte difference | — | 98.7% of bytes changed |
| Architecture | Identical | Identical |
| Tensor count | 78 | 78 |

The extra 984 bytes in 4.1.0 are consumed by the postpass:
- Offset 130,304: 1 FP32 LUT scale modulation parameter
- Offset 130,944: 4 FP32 output composition biases
- Offset 130,960: 4 FP32 output composition biases
- Remaining: padding and unused params

---

## Appendix A: Verified Constant Table

| Constant | Hex (double bits) | Decimal | Usage |
|----------|-------------------|---------|-------|
| 1/m2 | 0x3F89F9B580000000 | 0.012683313515656 | PQ EOTF exponent |
| -c1 | 0xBFEAC00000000000 | -0.8359375 | PQ EOTF offset |
| c3 | 1.868750e+01 | 18.6875 | PQ EOTF denominator |
| c2 | 0x4032DA0000000000 | 18.8515625 | PQ EOTF denominator |
| 1/m1 | 0x40191C0D60000000 | 6.277394636015326 | PQ EOTF exponent |
| 100/3 | 0x4040AAAAA0000000 | 33.33333206176758 | PQ scale |
| scale | 0x3FB4D50600000000 | 0.08137547969818115 | PQ output scale |
| -log2(e) | 0xBFF7154760000000 | -1.4426950216293335 | Sigmoid base conversion |
| 1/150 | 0x3F7B4E81C0000000 | 0.006666666828095913 | Postpass normalization |

## Appendix B: Resource Handle Convention

In all shaders, handles are created in this order:
```
%1 = UAV space=2, reg=3      (prepass: output, core: compute C)
%2 = UAV space=1, reg=0      (accumulation buffer)
%3 = UAV space=0, reg=11     (shared computation buffer)
%4 = SRV space=5, reg=4      (history input)
%5 = SRV space=4, reg=3      (input color)
%6 = SRV space=3, reg=2      (motion vectors)
%7 = SRV space=2, reg=1      (depth)
%8 = SRV space=1, reg=0      (auxiliary)
%9 = SRV space=0, reg=18     (weight blob)
%10 = Sampler space=0, reg=0
%11 = CBV space=0, reg=1     (per-frame constants)
```

Note: Postpass uses a different handle ordering with additional UAV outputs.
