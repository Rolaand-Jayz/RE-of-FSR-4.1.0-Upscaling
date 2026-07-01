# Validators Start Here

If you want the shortest honest path through this repo, start with these artifacts in order:

1. `verification-report.json` — current verification-suite output with PASS / FAIL / SKIP / WARN status.
2. `README.md` — bounded high-level summary and artifact index.
3. `docs/pass-index-to-entrypoint-map.md` — explains the descriptor-slot taxonomy versus the DXIL entrypoint taxonomy.
4. `reports/host-cbuffer-dispatch.json` — static dispatch order and cbuffer evidence.
5. `spec/blob-format.json` — current weight-blob zone definitions, including the 222-FP32 tail.
6. `reports/dxil-ir-pass-mapping.json` and `spec/dxil-entrypoint-inventory.json` — model-family entrypoint inventory.
7. `rebuild/README.md` and `rebuild/test_blob_lookup.py` — bounded `fsr_data.dll` reconstruction evidence and blob-name verification.

Public verification commands:

```bash
python scripts/verify.py --report verification-report.ci.json
python scripts/static_re_closure.py --repo-root . --sdk-root ../fsr4-sdk-402-source --out reports/
python rebuild/test_blob_lookup.py
python scripts/validate_claims.py
```

Important caveats:

- `PASS` means the exact scripted predicate succeeded.
- `SKIP` means a check was intentionally not run because an optional input was not supplied.
- `WARN` is reserved for bounded caveats that should not be misread as proof.
- The tensor-offset artifact is a plausibility check, not runtime proof of live offset use.
- Descriptor-slot names (`pass_0` .. `pass_26`) and DXIL entrypoint names (`prepass`, `pass1` .. `pass12`, `pass0_post` .. `pass12_post`, `postpass`) are separate taxonomies until a direct bridge artifact is committed.
