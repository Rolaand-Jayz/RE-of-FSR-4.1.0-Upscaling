# Current Status

A one-glance summary of what is proven, what is static-only, what is inferred, what is not done, and legal risk.
Evidence tags:

- **STATIC-REPRODUCIBLE** — reproducible from committed static artifacts (hash match, binary parse, automated check)
- **STATIC-INFERRED** — derived from disassembly/decompilation; high confidence but not runtime-confirmed
- **PLAUSIBILITY-CHECK** — parse or structural check that validates internal consistency, not runtime behavior
- **RUNTIME-NOT-OBSERVED** — no runtime evidence gathered; requires native D3D12 capture
- **BOUNDED-REBUILD** — partial reconstruction with explicit scope limits
- **LEGAL** — risk posture, not a technical claim

| Finding | Status | Evidence | Gap |
|---|---|---|---|
| Weight blob extraction (6 blobs, 131072 B each) | STATIC-REPRODUCIBLE | `scripts/verify.py` 87 PASS / 0 FAIL; MD5 + SHA-256 match across re-extraction | Source DLL not redistributed; reproduction needs local DLL |
| DXIL entrypoint inventory (27 model passes) | STATIC-REPRODUCIBLE | `spec/dxil-entrypoint-inventory.json`; binary-hash comparison; `reports/dxil-ir-evidence.json` | Covers upscaler only; frame generation excluded |
| Pipeline dispatch order (27-loop + optional RCAS/SPD/Debug) | STATIC-INFERRED | Ghidra decompilation of `FUN_18000d5b0`; raw x86-64 disasm of `FUN_180025990` | Never observed at runtime; Proton blocked all capture |
| Tensor offset map (78 tensors) | PLAUSIBILITY-CHECK | `reports/tensor-offset-verification.json` (78/78 plausibility pass); 4.0.2-derived | Plausibility parse, not runtime offset use |
| Runtime pass order | RUNTIME-NOT-OBSERVED | No capture data | Needs native Windows D3D12 capture (see `runtime-validation/`) |
| Runtime CBV values | RUNTIME-NOT-OBSERVED | Static register map only | Needs dispatch-level constant-buffer dump |
| Runtime descriptor bindings | RUNTIME-NOT-OBSERVED | Static createHandle analysis | Needs descriptor-heap resolution at runtime |
| Data DLL reconstruction | BOUNDED-REBUILD | `rebuild/` per-section comparison; no copy-bytes proof | Byte equality not claimed; runtime equivalence untested |
| Neural architecture topology | STATIC-INFERRED | DXIL atomics/allocas/phi counts; activation patterns | Kernel sizes and U-Net label hedged per adversarial review |
| FP8 decode via atomicCompareExchange | STATIC-INFERRED | 256-byte stride, constant offsets | Mechanism described as "appears to function as" |
| Legal status | EXPOSED / UNREVIEWED | `LEGAL.md` documents risk; no attorney review | No legal opinion obtained; jurisdiction-dependent |

See `claims.json` for machine-queryable confidence values and `REPRODUCING.md` to reproduce these results.
