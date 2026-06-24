# FSR 4.1.0 Independent Tensor Offset Verification Report

## Methodology

This report independently verifies the tensor structure of the FSR 4.1.0 weight blob
by analyzing the compiled shader LLVM IR from `ffx_fsr4_api_x64.dll` v4.1.0.

### Analysis Chain
1. **Ghidra decompilation** confirms blob size = 131072 bytes (0x20000) for `FSR4UPSCALER_InitializerBuffer`
2. **602 LLVM IR shader blobs** extracted from the DLL's DXIL container
3. **Pass-specific shaders** identified: `fsr4_model_v07_fp8_no_scale_pass{0..13}`, `prepass`, `postpass`
4. **Weight buffer handle**: SRV range 0, index 18 (bound to the 131072-byte InitializerBuffer)
5. **Offset extraction**: Traced `rawBufferLoad` calls back through `atomicCompareExchange` coordination
   to find constant base offsets for each weight/bias tensor per pass

## Blob Layout (Ghidra + LLVM IR confirmed)

| Zone | Start | End | Size | Format |
|------|-------|-----|------|--------|
| Biases | 0 | 7208 | 7208 | FP16 |
| FP8 Weights | 7208 | 130088 | 122880 | UINT8 (FP8) |
| Extra FP16 | 130088 | 130976 | 888 | FP16 |
| Padding | 130976 | 131072 | 96 | Zeros |

## Offset Comparison Summary

- **Assumed map tensor count**: 78
- **Matched offsets**: 1
- **In assumed map only** (not seen in LLVM IR): 77
- **In LLVM IR only** (not in assumed map): 92

**CONCLUSION: The 4.0.2 tensor schema does NOT directly transfer. Significant differences detected.**

## Per-Pass Detailed Comparison

| Pass | LLVM IR Offsets | Assumed Offsets | Matched | LLVM Only | Assumed Only |
|------|----------------|-----------------|---------|-----------|-------------|
| postpass | 16, 130432 | — | 0 | 2 | 0 |
| prepass | — | — | 0 | 0 | 0 |
| pass0 | — | 0, 1024 | 0 | 0 | 2 |
| pass1 | 16, 3456, 3584, 4096, 4160, 4224 (+2) | 1088, 1280, 7208, 9512, 10024, 1152 | 1 | 7 | 5 |
| pass2 | 16, 4864, 7168, 7296, 7808, 7872 (+2) | 1344, 1408, 1536, 10536, 12840, 13352 | 0 | 8 | 6 |
| pass3 | 16, 8576, 10624 | 1600, 13864 | 0 | 3 | 2 |
| pass4 | 16, 10752, 13056, 13184, 15232, 15360 (+3) | 1728, 1792, 2048, 15912, 18216, 20264 | 0 | 9 | 6 |
| pass5 | 16, 17664, 19968, 20096, 22144, 22272 (+3) | 2176, 2240, 2496, 22312, 24616, 26664 | 0 | 9 | 6 |
| pass6 | 16, 24576, 32768 | 2624, 28712 | 0 | 3 | 2 |
| pass7 | 16, 33024, 37632, 37760, 45952, 46208 (+5) | 2880, 3008, 3520, 36904, 41512, 49704 | 0 | 11 | 6 |
| pass8 | 16, 54912, 59520, 59648, 67840, 68096 (+5) | 3776, 3904, 4416, 57896, 62504, 70696 | 0 | 11 | 6 |
| pass9 | 81408, 89728, 89984, 90048, 90112, 90176 (+1) | 4672, 4800, 5312, 5568, 78888, 83496 (+2) | 0 | 7 | 8 |
| pass10 | 16, 107008, 109312, 109440, 111488, 111616 (+3) | 5696, 5760, 6016, 99880, 102184, 104232 | 0 | 9 | 6 |
| pass11 | 116224, 118400, 118528, 118592, 120704 | 6144, 6208, 6464, 6592, 106280, 108584 (+2) | 0 | 5 | 8 |
| pass12 | 16, 123008, 125312, 125440, 125952, 126016 (+2) | 6656, 6720, 6848, 112680, 114984, 115496 | 0 | 8 | 6 |
| pass13 | — | 6912, 6976, 7104, 7168, 116008, 118312 (+2) | 0 | 0 | 8 |

## Detailed Pass Analysis

### postpass
- **Shader variants analyzed**: 48
- **Tertiary strides**: [256, 15392, 30752, 61472]
- **Constant buffer indices**: [0, 1, 4, 5]
- **Bias offsets** (0-7208): [16]
- **Extra offsets** (130088+): [130432]
- **Alloca sizes** (→ channel dims): {16: 1}

### prepass
- **Shader variants analyzed**: 90
- **Tertiary strides**: [15392, 30752, 61472]
- **Constant buffer indices**: [0, 1, 2, 4, 5]

### pass0
- **Shader variants analyzed**: 3
- **Tertiary strides**: [15392, 30752, 61472]
- **Constant buffer indices**: [0]

### pass1
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 768, 15392, 30752, 61472]
- **Constant buffer indices**: [2]
- **Bias offsets** (0-7208): [16, 1152, 3456, 3584, 4096, 4160, 4224, 4736]
- **Alloca sizes** (→ channel dims): {16: 2, 32: 3, 64: 2, 72: 1}

### pass2
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 768, 15392, 30752, 61472]
- **Constant buffer indices**: [3]
- **Bias offsets** (0-7208): [16, 4864, 7168]
- **Weight offsets** (7208-130088): [7296, 7808, 7872, 7936, 8448]

### pass3
- **Shader variants analyzed**: 6
- **Tertiary strides**: [1024, 7712, 15392, 30752, 61472, 2097664, 8342464, 33273664]
- **Constant buffer indices**: [4]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [8576, 10624]

### pass4
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 512, 768, 1024, 7712, 15392, 30752, 2097664, 8342464, 33273664]
- **Constant buffer indices**: [5]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [10752, 13056, 13184, 15232, 15360, 15424, 15488, 17536]

### pass5
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 512, 768, 1024, 7712, 15392, 30752, 2097664, 8342464, 33273664]
- **Constant buffer indices**: [6]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [17664, 19968, 20096, 22144, 22272, 22336, 22400, 24448]
- **Alloca sizes** (→ channel dims): {32: 1, 64: 4, 72: 1, 128: 2}

### pass6
- **Shader variants analyzed**: 6
- **Tertiary strides**: [2048, 4128, 7712, 15392, 30752, 565536, 2097664, 8342464]
- **Constant buffer indices**: [7]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [24576, 32768]
- **Alloca sizes** (→ channel dims): {64: 1}

### pass7
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 768, 1024, 2048, 2304, 4128, 7712, 15392, 565536, 2097664, 8342464]
- **Constant buffer indices**: [8]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [33024, 37632, 37760, 45952, 46208, 46272, 46336, 46400, 46464, 54656]

### pass8
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 768, 1024, 2048, 2304, 4128, 7712, 15392, 565536, 2097664, 8342464]
- **Constant buffer indices**: [9]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [54912, 59520, 59648, 67840, 68096, 68160, 68224, 68288, 68352, 76544]

### pass9
- **Shader variants analyzed**: 6
- **Tertiary strides**: [4128, 7712, 15392, 30752, 565536, 2097664, 8342464, 33273664]
- **Constant buffer indices**: [10]
- **Weight offsets** (7208-130088): [81408, 89728, 89984, 90048, 90112, 90176, 98432]

### pass10
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 512, 768, 1024, 7712, 15392, 30752, 2097664, 8342464, 33273664]
- **Constant buffer indices**: [11]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [107008, 109312, 109440, 111488, 111616, 111680, 111744, 113792]
- **Alloca sizes** (→ channel dims): {32: 1, 64: 4, 72: 1, 128: 2}

### pass11
- **Shader variants analyzed**: 6
- **Tertiary strides**: [7712, 15392, 30752, 61472]
- **Constant buffer indices**: [12]
- **Weight offsets** (7208-130088): [116224, 118400, 118528, 118592, 120704]

### pass12
- **Shader variants analyzed**: 6
- **Tertiary strides**: [256, 768, 15392, 30752, 61472]
- **Constant buffer indices**: [13]
- **Bias offsets** (0-7208): [16]
- **Weight offsets** (7208-130088): [123008, 125312, 125440, 125952, 126016, 126080, 126592]
- **Alloca sizes** (→ channel dims): {16: 2, 32: 3, 64: 2, 72: 1}

## Extra FP16 Parameters (offset 130088+)

- **postpass**: accesses extra FP16 at offsets [130432]

## Tertiary Stride Analysis

The `dx.op.tertiary.i32(i32 49, stride, a, b)` instruction computes `stride * a + b`.
This is used for HWNC/HWCN weight tensor addressing. The stride values reveal the
inner dimension of each weight tensor:

- **Stride 256** (0x100): Used for weight addressing
- **Stride 512** (0x200): Used for weight addressing
- **Stride 768** (0x300): Used for weight addressing
- **Stride 1024** (0x400): Used for weight addressing
- **Stride 2048** (0x800): Used for weight addressing
- **Stride 2304** (0x900): Used for weight addressing
- **Stride 4128** (0x1020): Used for weight addressing
- **Stride 7712** (0x1e20): Used for weight addressing
- **Stride 15392** (0x3c20): Used for weight addressing
- **Stride 30752** (0x7820): Used for weight addressing
- **Stride 61472** (0xf020): Used for weight addressing
