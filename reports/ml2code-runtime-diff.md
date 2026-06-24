# FSR 4.1.0 ml2code Runtime Operator Comparison

**Date:** 2026-06-01
**Method:** LLVM IR operation frequency analysis across all ML-related blobs

## Summary

**No new ML operators were introduced in 4.1.0.** The core inference pipeline uses the same operator set as 4.0.2. The changes are quantitative (more passes, more data orchestration), not qualitative (new operator types).

## Operation Frequency Comparison (ML blobs only)

| Operation | 4.0.2 | 4.1.0 | Delta | Significance |
|-----------|-------|-------|-------|-------------|
| fmul | 33,060 | 40,344 | +22% | More convolution ops (27 vs 14 passes) |
| fadd | 22,047 | 25,344 | +14% | More accumulations |
| atomicCompareExchange | 153,387 | 227,034 | +48% | Much more data orchestration |
| getelementptr | 7,812 | 23,880 | +205% | More complex memory addressing |
| rawBufferLoad | 5,271 | 6,294 | +19% | More weight/activation reads |
| cbufferLoad | 1,440 | 1,722 | +19% | More dispatch parameter reads |
| min | 90 | 1,008 | +1020% | More coordinate clamping in spatial passes |
| mul (integer) | 9,177 | 6,336 | -31% | Less integer arithmetic |
| select | 3,696 | 4,476 | +21% | More conditional operations |
| fcmp | 2,676 | 3,456 | +29% | More float comparisons |
| lshr | 69 | 159 | +130% | More bit extraction |
| sdiv | 0 | 6 | NEW | Tile coordinate division (not ML op) |
| sitofp | 720 | 720 | 0% | Dequantization count unchanged |
| rsqrt | 180 | 180 | 0% | No change |
| bitcast | 2,991 | 3,042 | +1% | Negligible change |

## Operator Map

### Unchanged operators:
- **Conv2D**: rawBufferLoad + fmul chains (increased count, same pattern)
- **DequantizeLinear**: bitcast + sitofp/uitofp + fmul (identical pattern, same frequency)
- **Relu/Activation**: icmp + select (pattern unchanged)
- **Residual Add**: fadd (pattern unchanged)
- **FP8 decode**: and + lshr + bitcast (pattern unchanged)

### What changed:
1. **22% more fmul operations** — the 27 passes simply contain more convolution work than 14 passes
2. **48% more atomicCompareExchange** — entirely from data orchestration passes, not ML inference
3. **205% more getelementptr** — more complex buffer addressing due to dynamic weight loading
4. **min operations +1020%** — all from spatial processing passes (coordinate clamping), not new ML ops

### New in 4.1.0:
- **sdiv** (6 instances): Used for tile coordinate division in spatial processing. Not an ML operator.
- Dynamic weight loading pattern: rawBufferLoad from scratch buffer with cbuffer-computed offsets

## Conclusion

The ml2code_runtime operator library is unchanged between 4.0.2 and 4.1.0. The same float8_NHWC operators (Conv2D, ConvNextBlock, FasterNetBlock, DequantizeLinear) are used. The architectural differences are:
1. More passes (deeper/wider pipeline)
2. Dynamic weight loading instead of static embedding
3. Significant data orchestration infrastructure (atomic buffer management)
4. No new fused operators or operator types

For Temporal Forge: the 4.0.2 ml2code_runtime operators can be used directly. The pipeline needs to be extended to 27 passes, and the weight loading needs to switch from static arrays to buffer-based dynamic access.
