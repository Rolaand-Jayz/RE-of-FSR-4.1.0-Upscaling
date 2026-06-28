# Architecture

> The neural network inside FSR 4 — a sequential encoder/body/decoder pipeline for super-resolution.
>
> **Source**: Architecture derived from MIT-licensed 4.0.2 HLSL source. Structural claims confirmed against 4.1.0 via Ghidra static analysis and DXIL entry point names. See each section for evidence level.

## Model Identity

| Property | Value | Source |
|----------|-------|--------|
| Internal name | `fsr4_model_v07_fp8_no_scale` | 4.0.2 HLSL + 4.1.0 DXIL entry points |
| Internal codename | MLSR (Multi-Layer Super Resolution) | Ghidra: debug string in dispatch function |
| Version | v07 (shared between 4.0.2 and 4.1.0) | DXIL entry point names match |
| Build date (4.1.0) | March 20, 2026 | Ghidra: embedded debug string |
| Git commit (4.1.0) | `abd3160` | Ghidra: embedded debug string |
| Weight format | FP8/INT8 quantized weights, FP16 biases | 4.0.2 HLSL tensor type declarations |
| Total parameters | ~125 KB per quality preset | pefile: blob size 131,072 bytes |

## Network Topology

*Source: 4.0.2 HLSL source (MIT-licensed). Confirmed in 4.1.0 by matching DXIL entry point names.*

```
Input (7 channels, H×W)
  │
  ├── encoder1 ─────────────────────────────────────────────────────
  │   └── DownscaleStridedConv2x2    7 → 16 channels, /2 spatial
  │       Weight: [2,2,8,16] HNWC (1024 bytes FP16)
  │
  ├── encoder2 ─────────────────────────────────────────────────────
  │   ├── ResidualBlock ×2  (16 ch)
  │   │   ├── DepthwiseConv  [3,3,16,16] HWNC
  │   │   ├── PointwiseExpand  [1,1,16,32] HWNC  (16→32)
  │   │   └── PointwiseContract  [1,1,32,16] HWNC  (32→16)
  │   └── DownscaleStridedConv2x2   16 → 32 channels, /2 spatial
  │       Weight: [2,2,16,32] HWNC (2048 bytes FP8)
  │
  ├── encoder3 ─────────────────────────────────────────────────────
  │   ├── ResidualBlock ×2  (32 ch)
  │   │   ├── SpatialMixingPartialConv  [3,3,16,16] HWNC
  │   │   ├── PointwiseExpand  [1,1,32,64] HWNC  (32→64)
  │   │   └── PointwiseContract  [1,1,64,32] HWNC  (64→32)
  │   └── DownscaleStridedConv2x2   32 → 64 channels, /2 spatial
  │       Weight: [2,2,32,64] HWNC (8192 bytes FP8)
  │
  ├── bottleneck ──────────────────────────────────────────────────
  │   ├── ResidualBlock ×3  (64→128→64 ch, deepest layer)
  │   │   ├── SpatialMixingPartialConv  [3,3,16,32] HWNC
  │   │   ├── PointwiseExpand  [1,1,64,128] HWNC  (64→128)
  │   │   └── PointwiseContract  [1,1,128,64] HWNC  (128→64)
  │   └── UpscaleConvTranspose2x2    64 → 32 channels, ×2 spatial
  │       Weight: [2,2,32,64] HWCN (8192 bytes FP8)
  │
  ├── decoder3 ────────────────────────────────────────────────────
  │   ├── ResidualBlock ×2  (32→64→32 ch)
  │   │   ├── SpatialMixingPartialConv  [3,3,16,16] HWNC
  │   │   ├── PointwiseExpand  [1,1,32,64] HWNC
  │   │   └── PointwiseContract  [1,1,64,32] HWNC
  │   └── UpscaleConvTranspose2x2    32 → 16 channels, ×2 spatial
  │       Weight: [2,2,16,32] HWCN (2048 bytes FP8)
  │
  ├── decoder2 ────────────────────────────────────────────────────
  │   ├── ResidualBlock ×2  (16→32→16 ch)
  │   │   ├── DepthwiseConv  [3,3,16,16] HWNC
  │   │   ├── PointwiseExpand  [1,1,16,32] HWNC
  │   │   └── PointwiseContract  [1,1,32,16] HWNC
  │   └── UpscaleConvTranspose2x2    16 → 8 channels, ×2 spatial
  │       Weight: [2,2,8,16] HWCN (512 bytes FP8)
  │
  └── Output (8 channels, H×W)
```

## Spatial Pyramid

*Source: Ghidra decompilation of tile config tables in `dll_v410.dll`.*

The network operates at four spatial scales in a encoder-decoder progression with spatial bottleneck:

```
Scale    Dimensions (1080p)    Stage
1.0×     1920 × 1080          Input / Output
0.5×     960 × 540            encoder1, encoder2, decoder2
0.25×    480 × 270            encoder3, decoder3
0.125×   240 × 135            bottleneck
```

Flow: **1.0 → 0.5 → 0.25 → 0.125 → 0.25 → 0.5 → 1.0**

Channel flow: **7 → 16 → 32 → 64 → 128 → 64 → 32 → 16 → 8**

## Residual Block Architecture

*Source: 4.0.2 HLSL source (MIT-licensed).*

The network uses two residual block variants:

### Variant A: MobileNet-style (encoder2, decoder2)
```
Input ──┐
        │   DepthwiseConv 3×3  (spatial mixing)
        │   PointwiseExpand 1×1 (channel expansion, 1→2×)
        │   PointwiseContract 1×1 (channel contraction, 2→1×)
Output ─┘  (element-wise add)
```

### Variant B: Spatial Mixing (encoder3, bottleneck, decoder3)
```
Input ──┐
        │   SpatialMixingPartialConv 3×3  (partial convolution for holes)
        │   PointwiseExpand 1×1 (channel expansion)
        │   PointwiseContract 1×1 (channel contraction)
Output ─┘  (element-wise add)
```

## Dispatch Pipeline

*Source: Ghidra decompilation of `FUN_18000d5b0`.*

FSR 4 runs **27 compute dispatches per frame** (confirmed by loop counter `0x1b`):

| # | Pass Type | Count | Description |
|---|-----------|-------|-------------|
| 1 | Prepass | 1 | Motion vector / depth preprocessing |
| 2–13 | Model passes | 12 | Neural network (pass 0–13, sequential) |
| 14–25 | Model post | 12 | Per-pass postprocessing |
| 26 | Postpass | 1 | Final composition |
| 27 | SPD | 1 | Mip generation |

## Skip Connection Assessment

> ⚠️ **Static analysis only — not runtime-verified.**

**No skip connections were detected** in static analysis. Evidence:

1. **Resource name table** *(Ghidra)*: Model passes only bind `r_input_color` (input) and `rw_mlsr_output_color` (output). No skip resource names exist in the 12-entry SRV table.
2. **Binding resolver** *(Ghidra)*: `FUN_18000a910` matches against a fixed table. No encoder-specific output names.
3. **Identical PSV0** *(pefile)*: All 12 model passes have byte-identical resource binding metadata.
4. **Dispatch loop** *(Ghidra)*: Flat sequential loop with no code path for non-consecutive pass output binding.

**What this doesn't prove**: We did not capture actual GPU resource bindings at runtime. The D3D12 capture tools in `tools/` were designed for this purpose but were not deployed. It remains possible (though unlikely given the evidence) that the runtime performs binding operations invisible to static analysis.

## Memory Layout

*Source: Ghidra decompilation.*

Each pass context in the dispatch loop is 36,456 bytes (0x8e68). Total pass context: 27 × 36,456 = ~984 KB.

The weight blob (`InitializerBuffer`) is allocated once at 131,072 bytes and bound to every model pass.

## 4.0.2 vs 4.1.0 Differences

| Property | 4.0.2 | 4.1.0 | Evidence |
|----------|-------|-------|----------|
| Architecture | v07 sequential bottleneck autoencoder | Identical | DXIL entry point names match |
| Tensor count | 78 | 78 (assumed identical) | ⚠️ Not runtime-verified |
| Blob size | 130,088 bytes | 131,072 bytes (+976) | pefile measurement |
| Unique presets | 6 (all different) | 2 (5 identical + DRS) | MD5 comparison |
| FP8 unique values | 122 (clustered codebook) | 255 (full uint8 range) | Statistical analysis |
| Weight change | — | 98.7% bytes changed | Byte-by-byte diff |
| Extra params | — | +222 FP32 (output composition biases) values | Observed; purpose ⚠️ unconfirmed |

**Note on offset equivalence**: The 4.0.2 HLSL source provides exact byte offsets for all 78 tensors. The 4.1.0 DXIL confirms identical entry point names, suggesting the same architecture. However, the 4.1.0 offsets are loaded from cbuffer at runtime — we did not capture the actual runtime values. The assumption that offsets match is based on structural equivalence, not direct observation.
