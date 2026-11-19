# Contributing to the FSR 4.1.0 Static Reverse-Engineering Notes

This repository is a static-analysis research record. The most useful contributions are evidence: reproductions of the verification results, native D3D12 runtime captures, counter-evidence against a claim, and corrections where a document says more than its evidence supports.

## Before you start

Read these first. Contributions are reviewed against them:

- [`README.md`](README.md): scope and claim ceiling.
- [`CURRENT_STATUS.md`](CURRENT_STATUS.md): one-glance truth table. Each finding has an evidence tag and a stated gap.
- [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md): the canonical source for claim status. If another file conflicts with it, the more conservative assessment wins.
- [`claims.json`](claims.json): machine-readable claim registry with confidence values.
- [`REPRODUCING.md`](REPRODUCING.md): how to rerun the verification suite.
- [`HOSTILE_REVIEWER_START_HERE.md`](HOSTILE_REVIEWER_START_HERE.md) and [`VALIDATORS_START_HERE.md`](VALIDATORS_START_HERE.md): the shortest paths for checking the claims.
- [`LEGAL.md`](LEGAL.md) and [`RISK.md`](RISK.md): what may be contributed and what must not be redistributed.

## Legal boundaries

These come from `LEGAL.md` and `RISK.md`. A contribution that crosses them will not be merged.

- Contribute only your own original work, material derived from publicly available MIT-licensed source (with its origin documented), or factual analysis that does not reproduce proprietary source code. By contributing, you certify that your contribution meets this rule.
- Do not contribute decompiled or disassembled AMD source, copies of AMD binaries, Ghidra projects, DXIL disassembly, or material obtained under NDA.
- Do not attach the original DLLs or decompiled source to issues. For runtime captures, share only dispatch logs and constant-buffer dumps.
- Extracted weight data and compiled DLLs are AMD-derived and are not MIT-licensed. See the per-directory table in `LEGAL.md`. Do not add them to a pull request.
- Keep `extracted/NOTICE.md` and `extracted/SPDX_LICENSES.md` in place.
- If you are not sure whether something is allowed, open an issue before you open a pull request.

Nothing in this repository is legal advice. No attorney has reviewed it.

## Label every claim

Use the evidence tags defined in `CURRENT_STATUS.md` and `VALIDATION_STATUS.md`:

- **STATIC-REPRODUCIBLE**: reproducible from committed static artifacts (hash match, binary parse, automated check).
- **STATIC-INFERRED**: derived from disassembly or decompilation; not runtime-confirmed.
- **PLAUSIBILITY-CHECK**: checks internal consistency, not runtime behavior.
- **RUNTIME-NOT-OBSERVED**: no runtime evidence; needs a native D3D12 capture.
- **BOUNDED-REBUILD**: partial reconstruction with explicit scope limits.

Static evidence is not runtime evidence. Do not move a claim toward runtime-observed without a capture that meets [`runtime-validation/README.md`](runtime-validation/README.md). State what your evidence does not prove.

When a claim's status or confidence changes, update `claims.json`, `CURRENT_STATUS.md`, and `VALIDATION_STATUS.md` together.

## Ways to contribute

- **Reproduce the results.** Run `make verify-public` (or the three commands in `REPRODUCING.md`). Open a *Reproduction or correction* issue with your environment and the full result, including any FAIL or SKIP lines. If you used a local DLL, record its SHA-256.
- **Submit a runtime capture.** Native Windows D3D12 only. Use the *Native D3D12 Capture* issue template. Requirements are in `runtime-validation/README.md`.
- **Challenge a claim.** Use the *Claim Challenge* template with the `claim_id` from `claims.json`, or the *Reproduction or correction* form.
- **Report a verification bug.** Use the *Verification Bug* template.
- **Ask a question.** Use the *Question* form.

## Pull request rules

1. **Label your claims** with the tags above.
2. **Respect the legal boundaries** above.
3. **Keep failed and negative results.** Failed capture attempts and hostile-review material are part of the evidence. Add new evidence and change the status; do not delete the old record.
4. **Update `REPRODUCING.md`** if commands, inputs, or expected outputs change.
5. **Run `make verify-public` before you open the pull request.** CI runs the same checks, plus guards for overclaim phrases and for Markdown lines of 450 characters or more. If `scripts/validate_claims.py` fails, fix the wording. Never edit the guardrail to silence a real overclaim.

## Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
