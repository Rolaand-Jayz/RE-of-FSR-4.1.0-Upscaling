# FSR 4.1.0 Architecture Map

**Date:** 2026-06-01
**Method:** LLVM IR analysis of 602 DXBC blobs from FSR 4.1.0 DLL (15,605,520 bytes)
**Build:** git commit abd3160, March 20 2026

---

## 1. Shader Blob Inventory

| Metric | 4.0.2 | 4.1.0 |
|--------|-------|-------|
| Total DXBC blobs | 584 | 602 |
| Unique shader types (by size+rbl+ace) | -- | ~200 |
| ML-related blobs (with rawBufferLoad) | ~120 | 174 |
| Model passes (C++ provider) | 14 | 27 |

## 2. Pass Classification

Analysis of all 602 blobs by resource binding signature and operation counts reveals three distinct ML pass groups:

### Group A: Spatial Processing Passes (data orchestration)
- Blobs: 126 instances, ~24 unique types
- Signature: SRV buf 18 + SRV tex 0 -> UAV buf 0,11
- Characteristics: Very high atomicCompareExchange (782-9088 per blob), low arithmetic (0-4 ops), moderate rawBufferLoad (38-162)
- Size range: 131KB-1709KB LLVM IR
- Function: Manage scratch buffer layout using atomic-based dynamic allocation. Handle spatial tiling, data staging, and intermediate tensor orchestration between compute passes.

### Group B: ML Body Passes (neural network inference)
- Blobs: 48 instances = 16 unique types x 3 variants
- Signature: SRV buf [3,6/9,17/18] + SRV tex 1 -> UAV buf [0,1,2,6/9,11/12]
- Characteristics: Consistent rbl=54, ace=1580, variable arithmetic (155-407 fmul+fadd)
- Size range: 252-290KB LLVM IR
- 3 variants per type: Likely WMMA, non-WMMA, and possibly a third configuration
- Function: Actual neural network layers -- Conv2D, FasterNetBlock, ConvNextBlock, dequantization, activations

### Group C: Encoder/Decoder Passes (interface between texture and buffer domains)
- Blobs: Multiple instances, ~8 unique types
- Signature: SRV buf [0,1,2,3,4,18] + SRV tex 1 -> UAV buf [0,3,11] + UAV tex 0
- Characteristics: rbl=6, ace=206, high arithmetic (401-728)
- Size range: 81-132KB LLVM IR
- Function: Convert between texture (image) data and buffer (NHWC tensor) data. Handle downsampling (encoder) and upsampling (decoder), with color space conversion.

## 3. The 27-Pass Architecture

The C++ provider creates 27 model dispatches per frame (up from 14 in 4.0.2). Based on blob analysis:

```
Input (color texture + depth + motion vectors)
|
+-- Encoder passes (~4-6 dispatches)
|   +-- Texture -> NHWC buffer conversion
|   +-- Spatial downsampling (2x stride)
|   +-- Channel expansion (increasing width)
|   +-- Weight dequantization setup
|
+-- Data orchestration passes (~5-8 dispatches)
|   +-- Scratch buffer allocation via atomicCompareExchange
|   +-- Spatial tiling and tile management
|   +-- Intermediate tensor staging
|   +-- Buffer layout reorganization
|
+-- ML body passes (16 unique x 1 variant selected = ~13-16 dispatches)
|   +-- NHWC buffer reads + writes
|   +-- Conv2D operations (pointwise, depthwise, strided)
|   +-- FasterNet/ConvNext blocks
|   +-- FP8 dequantization (bitcast + scale)
|   +-- Residual connections
|   +-- Activation: ReLU (FMax(x, 0.0))
|
+-- Decoder passes (~2-4 dispatches)
|   +-- NHWC buffer -> texture conversion
|   +-- Spatial upsampling (transposed conv)
|   +-- Channel reduction + output projection
|
Output (upscaled color texture)
```

The 13 extra passes compared to 4.0.2 are primarily data orchestration passes -- the spatial processing group (Group A) handles scratch buffer management that was simpler or absent in 4.0.2.

## 4. Weight Data Flow

### 4.0.2 (MIT source)
- Weights embedded as static const uint arrays in HLSL
- Compiled directly into shader bytecode
- No runtime weight loading

### 4.1.0 (DLL)
- No embedded weight arrays in any shader blob
- Weights stored in InitializerBuffer (131,072 bytes)
- InitializerBuffer staged to GPU via upload buffer
- ML passes load weights dynamically via rawBufferLoad with cbuffer-computed offsets
- Offsets are NOT constant -- computed from dispatch parameters
- Scratch buffer (21MB at 1080p, 84MB at 4K) holds both weights and intermediate tensors
- AtomicCompareExchange used for dynamic scratch buffer allocation

### Implication for Tensor Offset Map
The previous 78-tensor offset map derived from 4.0.2's HLSL schema is STRUCTURALLY CONSISTENT with 4.1.0 but NOT runtime-verified because:
1. 4.1.0 has 27 main-loop dispatches vs 4.0.2's 14 main passes -- the tensor layout is fundamentally different
2. Offsets are computed dynamically from cbuffer values, not hardcoded
3. The scratch buffer uses atomic-based allocation, meaning tensor positions vary per dispatch

The tensor structure can only be definitively confirmed via runtime capture. Static evidence (matching model name, matching pass count, matching blob sizes) supports but does not prove offset equivalence.

## 5. Body Pass Architecture Detail

16 unique body pass types, grouped by resource binding:

| Group | SRV bufs | Extra SRV | UAV bufs | Count | Unique sizes |
|-------|----------|-----------|----------|-------|-------------|
| B1 | 3,6,9,18 | -- | 0,1,2,6,9,11,(12) | 24 | 4 (290/275/263/254 KB) |
| B2 | 3,9,18 | -- | 0,1,2,6,11,(12) | 18 | 4 (289/288/274/263/254/253 KB) |
| B3 | 3,9,17,18 | 17 | 0,1,2,6,11,(12) | 6 | 2 (262 KB) |

The presence/absence of UAV buf 12 and SRV buf 6/17 suggests:
- UAV buf 12: Skip connection or auxiliary output (present in some passes, absent in paired variants)
- SRV buf 6: Additional input feature map
- SRV buf 17: Likely the InitializerBuffer or a derived weight buffer (only in group B3)

Arithmetic complexity decreases across the pass order:
- 407 ops (largest body passes) -> 365 -> 246 -> 155 ops (smallest)

This suggests a pyramid structure: wide layers (many ops) at the beginning, narrower layers (fewer ops) toward the end.

## 6. Encoder/Decoder Pass Detail

8 unique encoder/decoder types, with two sub-groups:

### Full encoder (all 5 input features):
- SRV bufs: 0,1,2,3,4,18 (depth, motion, exposure, etc.)
- 132KB, 131KB, 116KB, 115KB, 102KB, 93KB, 90KB sizes
- 6 variants per type (3 resolution tiers x 2 WMMA modes)

### Reduced encoder (fewer inputs):
- SRV bufs: 0,1,3,4,18 (or with 6,17)
- 123KB, 122KB, 107KB, 106KB, 102KB, 93KB, 82KB, 81KB sizes
- 3 or 6 variants per type

The decoder passes share the same signature but read from buffers and write to UAV texture 0.

## 7. Key Differences from 4.0.2

| Aspect | 4.0.2 | 4.1.0 |
|--------|-------|-------|
| Model passes | 14 | 27 |
| Weight storage | Embedded in shaders | InitializerBuffer + dynamic loading |
| Weight access | Static const arrays | rawBufferLoad + cbuffer offsets |
| Body pass types | ~10 unique | 16 unique |
| Data orchestration | Minimal | Extensive (atomicCompareExchange-based) |
| Scratch buffer | Fixed size | Resolution-dependent (21/84/322 MB) |
| Preset weights | 6 unique blobs | 2 unique blobs (5 shared + DRS) |
| Compute pipeline | Pre->Body->Post | Encoder->Orchestration->Body->Decoder |

## 8. What Still Needs RE

### Cannot be done statically:
- Exact tensor offsets within the 131KB weight blob -- offsets are computed dynamically from cbuffer values set by the C++ dispatch function
- Per-pass weight allocation -- the scratch buffer uses dynamic allocation
- Operator sequence within each pass -- the LLVM IR is heavily optimized and operators are fused

### Can be done with runtime capture:
- The D3D12 hook tool at /mnt/workdrive/fsr-re/tools/capture/ can intercept dispatch calls
- Capturing cbuffer values + resource bindings for all 27 passes would give definitive tensor layout
- Capturing rawBufferLoad offsets at runtime would map the weight access pattern

### Partially done (needs verification):
- The 222 FP32 output composition biases at blob offset 130088 -- consumed by postpass via rawBufferLoad (resolved, see docs/extra-params-analysis.md)
- The exact spatial pyramid structure (which passes operate at which resolution)
