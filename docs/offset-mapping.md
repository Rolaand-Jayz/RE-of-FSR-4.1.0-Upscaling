# Offset Mapping

> How we mapped every tensor in the weight blob — 78 tensors with byte offsets.
>
> **Important caveat**: The 4.0.2 offsets are from MIT-licensed source and are confirmed. The 4.1.0 offsets are *assumed identical* based on matching model names and DXIL entry points — they were not captured at runtime.

## The Problem

We had extracted 131,072-byte blobs from the DLL, but we needed to know: where does each weight tensor start? How big is it? Which layer does it belong to?

## The Breakthrough: 4.0.2 HLSL as Ground Truth

*Source: FidelityFX SDK 4.0.2, MIT-licensed.*

The 4.0.2 SDK ships with complete HLSL source for `fsr4_model_v07_fp8_no_scale`. The shader files contain `threadGroupStorageByteOffset` attributes that specify exactly where each tensor begins in the InitializerBuffer:

```hlsl
// From fsr4_model_v07_fp8_no_scale_passes_1080.hlsl
groupshared float s0[2 * 2 * 8 * 16]    : register(s0);   // offset 0
groupshared float s1[16]                 : register(s1);   // offset 1024
groupshared float s2[32]                 : register(s2);   // offset 1088
// ...
```

We parsed the MIT-licensed 4.0.2 model pass source and extracted **78 tensor definitions** with their byte offsets. ✅ *This is public, MIT-licensed data — anyone can verify it.*

## Applying to 4.1.0

*Source: DXIL entry point name matching + structural analysis.*

We confirmed the 4.1.0 DXIL entry points use the same model family name (`fsr4_model_v07_fp8_no_scale`). The extracted 4.1.0 corpus contains 27 unique model entrypoints: prepass, postpass, main passes 1–12, and post stages 0–12. This supports structural continuity without inventing a nonexistent pass13.

**However**: In 4.1.0, the tensor byte offsets are loaded from cbuffer at runtime (via `cbufferLoadLegacy`), not hardcoded in the shader. We did not capture the actual cbuffer values during execution. The assumption that the 4.0.2 offsets apply verbatim to 4.1.0 is based on:

1. ✅ Matching model name (`fsr4_model_v07_fp8_no_scale`)
2. ✅ Matching pass count and entry point names
3. ✅ Identical blob structure (same bias zone size, same weight zone size)
4. ⚠️ **Not verified**: Actual runtime cbuffer values

**Risk**: If AMD changed the internal offset layout while keeping the same model name, our mapping would be wrong. Given points 1–3, this is unlikely but possible.

## Complete Tensor Map

### FP16 Parameter Zone (0 – 7,208 bytes): 40 Tensors

All values are FP16 (39 biases + 1 encoder1 weight) (`Tensor1f`). Each bias is small (16–128 values).

| Pass | Offset | Tensor | Description |
|------|--------|--------|-------------|
| 0 | 0 | encoder1_downscale_conv_weight | Input downscale weight (1024 bytes FP16, [2,2,8,16]) |
| 0 | 1,024 | encoder1_downscale_conv_bias | Input downscale bias |
| 1 | 1,088 | encoder2_RB0_dw_bias | Depthwise conv bias |
| 1 | 1,152 | encoder2_RB0_pw_expand_bias | Pointwise expand bias |
| 1 | 1,280 | encoder2_RB0_pw_contract_bias | Pointwise contract bias |
| 2 | 1,344 | encoder2_RB1_dw_bias | Depthwise conv bias |
| 2 | 1,408 | encoder2_RB1_pw_expand_bias | Pointwise expand bias |
| 2 | 1,536 | encoder2_RB1_pw_contract_bias | Pointwise contract bias |
| 3 | 1,600 | encoder2_downscale_bias | Encoder 2 downscale bias |
| 4 | 1,728 | encoder3_RB0_spatial_mixing_bias | Spatial mixing bias |
| 4 | 1,792 | encoder3_RB0_pw_expand_bias | Pointwise expand bias |
| 4 | 2,048 | encoder3_RB0_pw_contract_bias | Pointwise contract bias |
| 5 | 2,176 | encoder3_RB1_spatial_mixing_bias | Spatial mixing bias |
| 5 | 2,240 | encoder3_RB1_pw_expand_bias | Pointwise expand bias |
| 5 | 2,496 | encoder3_RB1_pw_contract_bias | Pointwise contract bias |
| 6 | 2,624 | encoder3_downscale_bias | Encoder 3 downscale bias |
| 7 | 2,880 | bottleneck_RB0_spatial_mixing_bias | Spatial mixing bias |
| 7 | 3,008 | bottleneck_RB0_pw_expand_bias | Pointwise expand bias |
| 7 | 3,520 | bottleneck_RB0_pw_contract_bias | Pointwise contract bias |
| 8 | 3,776 | bottleneck_RB1_spatial_mixing_bias | Spatial mixing bias |
| 8 | 3,904 | bottleneck_RB1_pw_expand_bias | Pointwise expand bias |
| 8 | 4,416 | bottleneck_RB1_pw_contract_bias | Pointwise contract bias |
| 9 | 4,672 | bottleneck_RB2_spatial_mixing_bias | Spatial mixing bias |
| 9 | 4,800 | bottleneck_RB2_pw_expand_bias | Pointwise expand bias |
| 9 | 5,312 | bottleneck_RB2_pw_contract_bias | Pointwise contract bias |
| 9 | 5,568 | bottleneck_upscale_bias | Upscale transpose conv bias |
| 10 | 5,696 | decoder3_RB1_spatial_mixing_bias | Spatial mixing bias |
| 10 | 5,760 | decoder3_RB1_pw_expand_bias | Pointwise expand bias |
| 10 | 6,016 | decoder3_RB1_pw_contract_bias | Pointwise contract bias |
| 11 | 6,144 | decoder3_RB2_spatial_mixing_bias | Spatial mixing bias |
| 11 | 6,208 | decoder3_RB2_pw_expand_bias | Pointwise expand bias |
| 11 | 6,464 | decoder3_RB2_pw_contract_bias | Pointwise contract bias |
| 11 | 6,592 | decoder3_upscale_bias | Upscale transpose conv bias |
| 12 | 6,656 | decoder2_RB1_dw_bias | Depthwise conv bias |
| 12 | 6,720 | decoder2_RB1_pw_expand_bias | Pointwise expand bias |
| 12 | 6,848 | decoder2_RB1_pw_contract_bias | Pointwise contract bias |
| 13 | 6,912 | decoder2_RB2_dw_bias | Depthwise conv bias |
| 13 | 6,976 | decoder2_RB2_pw_expand_bias | Pointwise expand bias |
| 13 | 7,104 | decoder2_RB2_pw_contract_bias | Pointwise contract bias |
| 13 | 7,168 | decoder2_upscale_bias | Upscale transpose conv bias |

### FP8 Weight Zone (7,208 – 130,088 bytes): 38 Tensors

All weights are quantized uint8 (`QuantizedTensor4f8_HWNC` or `QuantizedTensor4f8_HWCN`).

| Pass | Offset | Shape | Layer |
|------|--------|-------|-------|
| **Encoder 2** | | | |
| 1 | 7,208 | [3,3,16,16] | RB0 depthwise weight |
| 1 | 9,512 | [1,1,16,32] | RB0 pw_expand weight |
| 1 | 10,024 | [1,1,32,16] | RB0 pw_contract weight |
| 2 | 10,536 | [3,3,16,16] | RB1 depthwise weight |
| 2 | 12,840 | [1,1,16,32] | RB1 pw_expand weight |
| 2 | 13,352 | [1,1,32,16] | RB1 pw_contract weight |
| 3 | 13,864 | [2,2,16,32] | DownscaleStridedConv2x2 weight |
| **Encoder 3** | | | |
| 4 | 15,912 | [3,3,16,16] | RB0 spatial_mixing weight |
| 4 | 18,216 | [1,1,32,64] | RB0 pw_expand weight |
| 4 | 20,264 | [1,1,64,32] | RB0 pw_contract weight |
| 5 | 22,312 | [3,3,16,16] | RB1 spatial_mixing weight |
| 5 | 24,616 | [1,1,32,64] | RB1 pw_expand weight |
| 5 | 26,664 | [1,1,64,32] | RB1 pw_contract weight |
| 6 | 28,712 | [2,2,32,64] | DownscaleStridedConv2x2 weight |
| **Bottleneck** | | | |
| 7 | 36,904 | [3,3,16,32] | RB0 spatial_mixing weight |
| 7 | 41,512 | [1,1,64,128] | RB0 pw_expand weight |
| 7 | 49,704 | [1,1,128,64] | RB0 pw_contract weight |
| 8 | 57,896 | [3,3,16,32] | RB1 spatial_mixing weight |
| 8 | 62,504 | [1,1,64,128] | RB1 pw_expand weight |
| 8 | 70,696 | [1,1,128,64] | RB1 pw_contract weight |
| 9 | 78,888 | [3,3,16,32] | RB2 spatial_mixing weight |
| 9 | 83,496 | [1,1,64,128] | RB2 pw_expand weight |
| 9 | 91,688 | [1,1,128,64] | RB2 pw_contract weight |
| 9 | 119,336 | [2,2,32,64] | UpscaleConvTranspose weight (HWCN) |
| **Decoder 3** | | | |
| 10 | 99,880 | [3,3,16,16] | RB1 spatial_mixing weight |
| 10 | 102,184 | [1,1,32,64] | RB1 pw_expand weight |
| 10 | 104,232 | [1,1,64,32] | RB1 pw_contract weight |
| 11 | 106,280 | [3,3,16,16] | RB2 spatial_mixing weight |
| 11 | 108,584 | [1,1,32,64] | RB2 pw_expand weight |
| 11 | 110,632 | [1,1,64,32] | RB2 pw_contract weight |
| 11 | 127,528 | [2,2,16,32] | UpscaleConvTranspose weight (HWCN) |
| **Decoder 2** | | | |
| 12 | 112,680 | [3,3,16,16] | RB1 depthwise weight |
| 12 | 114,984 | [1,1,16,32] | RB1 pw_expand weight |
| 12 | 115,496 | [1,1,32,16] | RB1 pw_contract weight |
| 13 | 116,008 | [3,3,16,16] | RB2 depthwise weight |
| 13 | 118,312 | [1,1,16,32] | RB2 pw_expand weight |
| 13 | 118,824 | [1,1,32,16] | RB2 pw_contract weight |
| 13 | 129,576 | [2,2,8,16] | UpscaleConvTranspose weight (HWCN) |

### 4.1.0 Extra Zone (130,088 – 130,976): 444 FP16 Values

> ⚠️ **Observed but purpose unconfirmed.**

Present only in 4.1.0. Not referenced by any named tensor in the 4.0.2 HLSL source. Hypothesis: per-layer quantization scale factors, based on correlation with improved FP8 range (122→255 unique values). **This hypothesis has not been verified through shader tracing.**

## Offset Delivery

| Version | Mechanism | Evidence |
|---------|-----------|----------|
| 4.0.2 | Hardcoded in HLSL as `threadGroupStorageByteOffset` constants | ✅ Direct source observation |
| 4.1.0 | Loaded from cbuffer at runtime via `cbufferLoadLegacy(i32 59, ...)` | ✅ DXIL disassembly confirms cbuffer loads |

Despite the runtime mechanism, the actual offset values are *assumed identical* to 4.0.2 based on structural equivalence. See caveat above.

## Machine-Readable Format

The complete 78-tensor table: [`spec/tensor-map.json`](../spec/tensor-map.json)

## Tools

- `scripts/parse_offsets.py` — Extract tensor offsets from 4.0.2 HLSL source
- `scripts/trace_cbuffer.py` — Trace cbuffer loads in 4.1.0 DXIL
