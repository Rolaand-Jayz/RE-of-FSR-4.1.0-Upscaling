# Current Status

A one-glance summary of what is proven, what is static-only, what is inferred, what is not done, and legal risk.
Evidence tags: VERIFIED = confirmed by multiple independent methods; STATIC = inferred from disassembly/decompilation only; INFERENCE = derived indirectly; NOT DONE = no evidence gathered; LEGAL = risk posture.

| Finding | Status | Evidence | Gap |
|---|---|---|---|
| Weight blob extraction (6 blobs, 131072 B each) | VERIFIED | `scripts/verify.py` 87 PASS / 0 FAIL; MD5 + SHA-256 match across re-extraction | Source DLL not redistributed; reproduction needs local DLL |
| DXIL entrypoint inventory (27 model passes) | VERIFIED | `spec/dxil-entrypoint-inventory.json`; binary-hash comparison; `reports/dxil-ir-evidence.json` | Covers upscaler only; frame generation excluded |
| Pipeline dispatch order (27-loop + optional RCAS/SPD/Debug) | STATIC | Ghidra decompilation of `FUN_18000d5b0`; raw x86-64 disasm of `FUN_180025990` | Never observed at runtime; Proton blocked all capture |
| Tensor offset map (78 tensors) | STATIC / PLAUSIBLE | `reports/tensor-offset-verification.json` (78/78 plausibility pass); 4.0.2-derived | Plausibility parse, not runtime offset use |
| Runtime pass order | NOT DONE | No capture data | Needs native Windows D3D12 capture (see `runtime-validation/`) |
| Runtime CBV values | NOT DONE | Static register map only | Needs dispatch-level constant-buffer dump |
| Runtime descriptor bindings | NOT DONE | Static createHandle analysis | Needs descriptor-heap resolution at runtime |
| Data DLL reconstruction | BOUNDED / STATIC | `rebuild/` per-section comparison; no copy-bytes proof | Byte equality not claimed; runtime equivalence untested |
| Neural architecture topology | INFERENCE | DXIL atomics/allocas/phi counts; activation patterns | Kernel sizes and U-Net label hedged per adversarial review |
| FP8 decode via atomicCompareExchange | INFERENCE | 256-byte stride, constant offsets | Mechanism described as "appears to function as" |
| Legal status | EXPOSED / UNREVIEWED | `LEGAL.md` documents risk; no attorney review | No legal opinion obtained; jurisdiction-dependent |

See `claims.json` for machine-queryable confidence values and `REPRODUCING.md` to reproduce these results.
