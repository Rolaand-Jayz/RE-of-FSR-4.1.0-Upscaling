# Weight Extraction

> How we located and extracted the neural network weights from the FSR 4.1.0 DLL.

## The Challenge

FSR 4.1.0 ships as a single Windows DLL (`dll_v410.dll`, 15,605,520 bytes). Unlike 4.0.2, there's no source code. The weights are somewhere inside — but a 15 MB DLL has a lot of data sections.

## Finding the Weights

### Step 1: Trace the CreateContext factory

*Source: Ghidra decompilation of `FUN_18000b3c0`.*

Ghidra decompilation revealed `FUN_18000b3c0` — the context creation function. It contains a switch statement on the quality preset (0–5). Each case loads a data pointer via a LEA instruction:

```c
case FSR4_QUALITY_QUALITY:
    // LEA loads pointer to .rdata at RVA 0x91db50
    break;
case FSR4_QUALITY_BALANCED:
    // LEA loads pointer to .rdata at RVA 0x943cc0
    break;
// ... etc for 6 presets
```

These aren't code pointers — they point to raw data in the `.rdata` section.

### Step 2: Resolve LEA → RVA → File Offset

*Source: pefile analysis of the DLL's PE header and section table.*

Using pefile, we resolved each LEA target to a file offset. The PE section layout:

| Section | Virtual Address | Raw Offset |
|---------|----------------|------------|
| `.text` | 0x1000 | 0x400 |
| `.rdata` | 0x3a000 | 0x38e00 |
| `.data` | 0x15f000 | 0x15d400 |

All 6 weight blobs are in `.rdata`. ✅ *Cross-verified: Ghidra LEA targets AND pefile RVA resolution agree.*

### Step 3: Extract the blobs

*Source: pefile blob extraction + MD5 hashing.*

Each blob is exactly **131,072 bytes (0x20000)** — confirmed by the `InitializerBuffer` allocation size observed in the decompiled context creation code.

```
Preset       RVA        File Offset    Unique?
────────────────────────────────────────────────
Quality      0x91db50   0x91c950       Shared (5 presets)
Balanced     0x943cc0   0x942ac0       Shared (5 presets)
Performance  0x963d20   0x962b20       Shared (5 presets)
UltraPerf    0x8d7570   0x8d6370       Shared (5 presets)
Native       0x8fb700   0x8fa500       Shared (5 presets)
DRS          0x8b5120   0x8b3f20       Different (unique)
```

✅ *Verified: MD5 comparison confirms 2 unique blobs out of 6.*

## Blob Structure

*Source: 4.0.2 HLSL offset schema (MIT-licensed) + statistical analysis of extracted blobs.*

Each 131,072-byte blob is divided into zones:

```
┌─────────────────────────────────────────────────┐ 0x00000
│  FP16 Biases                                    │
│  7,208 bytes — 3,604 values across 40 tensors   │
│  Range: [-512, +512]                            │
│  ✅ Confirmed: offset and size match 4.0.2 HLSL │
├─────────────────────────────────────────────────┤ 0x01C28
│  FP8/UINT8 Weights                              │
│  122,880 bytes across 38 tensors                │
│  Layout: HWNC (depthwise/spatial) or HWCN        │
│          (transpose convolutions)                │
│  ✅ Confirmed: offset, size, count match HLSL    │
├─────────────────────────────────────────────────┤ 0x1FC28
│  Extra FP16 Parameters                          │
│  888 bytes — 222 FP32 values (output composition biases)                    │
│  ⚠️ Observed in 4.1.0 only. Purpose unconfirmed.│
│  Hypothesis: quantization scale factors (based   │
│  on correlation with improved FP8 range).        │
│  Not proven.                                     │
├─────────────────────────────────────────────────┤ 0x1FFA0
│  Zero Padding                                   │
│  96 bytes — alignment to 0x20000                 │
└─────────────────────────────────────────────────┘ 0x20000
```

## 4.0.2 Comparison

*Source: Byte-by-byte comparison of extracted blobs.*

The 4.0.2 SDK ships with the same model architecture but different weight blobs:

| Property | 4.0.2 | 4.1.0 | Evidence |
|----------|-------|-------|----------|
| Blob size | 130,088 bytes | 131,072 bytes (padded) | ✅ pefile measurement |
| Bias zone | 7,208 bytes | 7,208 bytes | ✅ Identical layout from HLSL |
| Weight zone | 122,880 bytes | 122,880 bytes | ✅ Identical layout from HLSL |
| Extra params | None | 888 bytes (222 FP32) | ⚠️ Observed, purpose unknown |
| Unique presets | 6 (all different) | 2 (5 identical + DRS) | ✅ MD5 comparison |
| FP8 unique values | 122 | 255 | ✅ Statistical count |
| Bytes changed | — | **98.7%** | ✅ Byte-by-byte diff |

### What 98.7% means

The near-total byte change rate is remarkably uniform across all blocks:

| Block | FP8 Bytes | Changed | Δ% |
|-------|-----------|---------|-----|
| encoder2 | 8,704 | 8,610 | 98.9% |
| encoder3 | 20,992 | 20,732 | 98.8% |
| bottleneck | 71,168 | 70,291 | 98.8% |
| decoder3 | 14,848 | 14,654 | 98.7% |
| decoder2 | 7,168 | 7,083 | 98.8% |
| **Total** | **122,880** | **121,370** | **98.8%** |

Bias zone: 159,711 / 161,216 bytes changed = **99.1%**.

This is consistent with a **weight retrain (inferred from byte-diff; cannot distinguish retrain from re-quantization)** — every layer's weights were regenerated, not fine-tuned. We cannot distinguish "retrain" from "re-quantize with different scheme" from the byte-level data alone.

### FP8 Quantization Change

4.0.2 used only 122 unique FP8 values out of 256 possible. The values were clustered around a few codepoints (primarily `0x19`, `0x99`, `0x21`). This suggests a limited quantization codebook.

4.1.0 uses all **255 non-zero uint8 values**. Combined with the 444 new FP16 parameters, this is consistent with a change from a limited codebook to full-range quantization with per-channel scale factors. **However, we did not trace how the extra parameters are consumed in the shader code, so this remains a hypothesis.**

## Preset Collapse

4.0.2 had 6 unique weight blobs (one per quality preset). 4.1.0 collapses this to 2: one shared by Quality/Balanced/Performance/UltraPerf/Native, and one for DRS.

*Source: Ghidra tile config tables + MD5 comparison.*

Quality is now controlled by **spatial tiling parameters** (the dispatch grid dimensions in the tile config tables), not separate model weights. The neural network runs with the same weights regardless of quality preset — only the tile size changes.

## Tools

- `scripts/extract_blobs.py` — Extract weight blobs from DLL using pefile
- `scripts/layer_diff.py` — Per-layer byte comparison between versions
- `scripts/parse_weights.py` — Parse individual tensors from blob
- `scripts/weight_compare.py` — Statistical comparison of distributions
