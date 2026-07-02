# Hostile Reviewer Start Here

You think this repo overclaims. Fair. Check these artifacts first, in this order:

1. **`CURRENT_STATUS.md`** — one-glance truth table. Every finding has a status label (STATIC-REPRODUCIBLE, STATIC-INFERRED, PLAUSIBILITY-CHECK, RUNTIME-NOT-OBSERVED, BOUNDED-REBUILD) and an explicit gap.

1b. **`VALIDATION_STATUS.md`** — canonical validation source. Defines evidence tiers, confidence values, and what each status label means. If any file conflicts with this one, the more conservative assessment wins.

2. **`claims.json`** — machine-readable claim registry. Each claim has a confidence value, supporting files, what additional evidence would upgrade it, and known open counterexamples. If a claim says `confidence: 0.0` and `status: unresolved`, that is a disclosure of ignorance, not an overclaim.

3. **`verification-report.json`** — automated verification output. 88 checks, each with PASS/FAIL/SKIP status and evidence string. Checks are categorized by evidence strength (`summary_by_kind`): hash identity, static inventory, static consistency, plausibility, and runtime observed.

4. **`runtime-validation/README.md`** — defines what a native D3D12 capture requires and why runtime validation is future work, not a release failure.

5. **`rebuild/section-comparison.json`** — per-section hash comparison of the rebuilt DLL against the original. No byte-equality claim.

5b. **`rebuild/section-comparison-explainer.md`** — plain-language explanation of what the section comparison does and does not prove.

6. **`docs/adversarial-review-resolution.md`** — prior adversarial review findings and how each was addressed.

## What this repo does NOT claim

- It does not claim runtime-observed pass order, CBV values, or descriptor bindings.
- It does not claim byte-exact binary reconstruction.
- It does not claim functional equivalence or deployability.
- It does not claim a runtime-observed one-to-one bridge between descriptor-slot indices and DXIL entrypoint names.

If you find a claim that exceeds what `claims.json` and `CURRENT_STATUS.md` support, that is a bug. Open an issue.

## Verification

```bash
make verify-public
```

Or individually:

```bash
python scripts/verify.py --report verification-report.ci.json
python rebuild/test_blob_lookup.py
python scripts/validate_claims.py
```

The `validate_claims.py` guardrail scans all text files for overclaim language. It exits non-zero on any match. It is deliberately strict.
