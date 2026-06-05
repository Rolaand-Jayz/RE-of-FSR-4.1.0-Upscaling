# Adversarial Review #2 — Shader Internals

**Reviewer:** Adversarial (automated)
**Date:** 2026-06-05
**Scope:** Shader internals analysis, weight blob claims, neural architecture characterization

---

## Verdict: STRONG with 4 issues and 2 caveats

The analysis is thorough and well-evidenced for the most part. The data-driven approach (counting atomics, allocas, phi nodes, IR lines across all 602 blobs) provides solid statistical backing for the architectural claims. However, several statements cross from evidence-backed into speculation territory without adequate hedging.

---

## Issue 1: "atomicCompareExchange is a LUT lookup" — UNVERIFIED MECHANISM

**Claim:** The 1989+ `atomicCompareExchange` calls per pass are side-effect-free LUT lookups, not real atomics.

**Evidence provided:** Constant byte offsets with 256-byte stride matching FP8 value range.

**Problem:** This is inferred from pattern analysis, not confirmed. Three alternative explanations were not ruled out:

1. **Actual atomics with persistent state.** The scratch buffer could be used as a real atomic workspace where the LUT values are populated on first use and read back.
2. **Compiler artifact.** The DXC shader compiler might emit `atomicCompareExchange` as a code generation artifact for buffer access patterns that don't have a clean DXIL representation.
3. **Mixed read-write.** Some of the 1989 atomic calls could be real writes (accumulation) while others are LUT reads.

**Recommendation:** State as "appears to function as" rather than "is" a LUT lookup.

---

## Issue 2: Kernel sizes are INFERRED, not extracted

**Claim:** Pass1/2/12 use 3x3 convolutions, pass4/5/10 use 4x4, pass7/8 use 5x4.

**Evidence provided:** Phi node counts of 12, 16, and 20 correspond to iteration counts.

**Problem:** Phi node count is total across the entire function, not just innermost loops. The correspondence is suggestive but not proven. 20 phi nodes could be 4x5, 2x10, or a non-rectangular pattern.

**Recommendation:** State as "consistent with" rather than "are" specific kernel sizes.

---

## Issue 3: "No attention mechanism" is a negative claim

**Claim:** No attention mechanism found; the architecture is likely pure convolutional.

**Problem:** The entire computation goes through the FP8 LUT/atomic mechanism. If attention weights are stored as FP8 and decoded through the same LUT path, there would be no distinguishable softmax pattern. You can't rule out attention by the absence of float-arithmetic softmax when all computation is integer-based.

**Recommendation:** Change to "Attention cannot be ruled out — integer-only computation could encode any operation through LUT values."

---

## Issue 4: "U-Net-like architecture" is speculative

**Claim:** The architecture resembles a U-Net.

**Problem:** U-Net specifically requires skip connections. The analysis found no evidence of skip connections (listed as unknown). Without skip connections, this is a bottleneck autoencoder, not a U-Net. The pass symmetry could also indicate parameter sharing or symmetric training loss.

**Recommendation:** Replace "U-Net-like" with "bottleneck architecture with symmetric pass structure."

---

## Well-Evidenced Claims

| Claim | Verdict |
|-------|---------|
| 5 standard presets byte-identical | ✅ Ironclad — MD5 match + 0 diff bytes |
| DRS fully retrained (96.1% diff) | ✅ Well-evidenced — 0 matching 4KB chunks |
| Post passes are trivial scatter | ✅ Well-evidenced — 0 atomics, 2-5 stores each |
| 28 unique FSR4 shaders | ✅ Well-evidenced — function name extraction |
| 3-tier complexity model | ✅ Well-supported by data |

## Claims Needing Hedging

| Claim | Verdict |
|-------|---------|
| FP8 LUT via atomics | ⚠️ Likely correct but mechanism unverified |
| 3x3/4x4/5x4 kernel sizes | ⚠️ Inferred from phi counts, not proven |
| No attention mechanism | ⚠️ Cannot be ruled out |
| U-Net architecture | ❌ Speculative — no skip connection evidence |
| CBV register semantics | ⚠️ Reasonable inference, not runtime-verified |

---

## Missed Items

1. **Prepass variant count.** 90 variants unexplained — why so many for a single pass type?
2. **"no_scale" designation.** FP8 E4M3/E5M2 have per-value exponents, not shared. The "no_scale" might mean no separate scale tensor, not shared exponent.
3. **Channel counts.** Alloca sizes + loop iteration counts should enable dimensional analysis to reverse-engineer channel dimensions. Not attempted.
