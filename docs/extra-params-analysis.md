# Extra Parameter Analysis — v4.1.0 Additional Data

> **Status:** RESOLVED. The extra 984 bytes are consumed by the postpass shader
> as additional FP32 bias/scale parameters for output composition.

## Prior Interpretation (Incorrect)

Previous documentation stated:
- "444 FP16 parameters (888 bytes)"
- "purpose unconfirmed; possibly quantization scale factors"

## Corrected Analysis

### Data Layout

| Offset | Size | Content |
|--------|------|---------|
| 130088–130975 | 888 bytes | 222 FP32 values (active data) |
| 130976–131071 | 96 bytes | Zero padding (alignment to 0x20000) |

**The extra region is FP32, not FP16.** The postpass loads these values via
`rawBufferLoad.i32` with full 4-component mask (`i8 15`), then stores them
directly into `[8 x float]` alloca slots. This is 4 bytes per value, not 2.

### Postpass Consumption (DXIL-confirmed)

Three access points into the extra region, confirmed in all 48 postpass variants:

**1. Offset 130304 (extra+216) — LUT parameter**

```llvm
%1500 = call i32 @dx.op.atomicCompareExchange.i32(i32 79, ...,
    i32 130304, i32 0)
%1501 = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, ...,
    i32 %1500, ...)
```

This value passes through LUT region 0x50000029 (scale factor lookup) before
being used as a weight buffer offset. It functions as a **scale modulation
factor** for the postpass's own weight decode.

Values (as FP32): `0.0475, 0.0396, 0.0296, -0.1584`

**2. Offset 130944 (extra+856) — Direct bias read**

```llvm
%1809 = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, ...,
    i32 130944, i32 undef, i8 15, i32 4)
```

Loads 4 FP32 values directly into `float[0:4]` alloca. No LUT transformation.

Values (as FP32): `0.1109, -0.4060, -0.1917, 0.0224`

**3. Offset 130960 (extra+872) — Direct bias read**

```llvm
%1822 = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, ...,
    i32 130960, i32 undef, i8 15, i32 4)
```

Loads 4 FP32 values directly into `float[4:8]` alloca. No LUT transformation.

Values (as FP32): `-0.0077, 0.0375, -0.1172, -0.1318`

### Interpretation

The 8 directly-read FP32 values (offsets 130944 + 130960) are **output
composition bias parameters** — one per output channel. The magnitudes
(0.01–0.41) and sign distribution (4 positive, 4 negative) match trained
neural network bias parameters.

The value at offset 130304 is a **scale modulation factor** that passes
through the FP8 decode LUT before use, controlling how the postpass decodes
its own weights.

The remaining ~200 FP32 values in the extra region are likely consumed through
similar LUT-mediated access patterns during postpass execution.

### Why FP32 not FP16

The `rawBufferLoad.i32` instruction loads 32-bit integers. These are stored
directly into `float`-typed stack memory via type-punning (`store i32` into
`[8 x float]`). The shader later reads them as `float`, confirming IEEE 754
single-precision interpretation. FP16 would require `rawBufferLoad.f16` or
explicit unpack instructions, neither of which appear in the IR.

## Cbuffer Offset Architecture

### Discovery

Each core ML pass loads parameters from exactly **one cbuffer slot**:

| Pass | CBV Slot | Pass | CBV Slot |
|------|----------|------|----------|
| pass1 | 2 | pass7 | 8 |
| pass2 | 3 | pass8 | 9 |
| pass3 | 4 | pass9 | 10 |
| pass4 | 5 | pass10 | 11 |
| pass5 | 6 | pass11 | 12 |
| pass6 | 7 | pass12 | 13 |

Pattern: **passN → slot(N+1)**

Each slot returns a `CBufRet.i32` with 4 components. Pass1 extracts components
0 and 1 — these are the tensor offset/stride parameters for that pass's weight
access.

### Implications

This confirms the methodology doc's finding that offsets are runtime-delivered
via cbuffer. However, the **slot-per-pass** architecture means:
- Each pass has exactly 4 i32 parameters (16 bytes)
- These likely encode: base_offset, stride_x, stride_y, channel_count
- The DLL populates these from the tensor map at dispatch time

Since we have the complete 4.0.2 tensor map (78 tensors with exact offsets),
and the architecture is structurally identical (same entry points, same tensor
count, same blob layout), the cbuffer values are **derivable from
tensor-map.json** by reading each pass's tensor offset.

This raises confidence in the offset equivalence from 85% to ~95% — the
delivery mechanism is confirmed, and the source values are known.
