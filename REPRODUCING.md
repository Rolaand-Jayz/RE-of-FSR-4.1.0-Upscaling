# Reproducing the Verification Results

This guide reproduces the static verification suite results committed in `verification-report.json` (87 PASS, 0 FAIL, 1 SKIP on the reference environment). All checks are static: they operate on committed artifacts and, optionally, on a locally supplied DLL.

## Required Tools

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.10+ | Runs the verification suite |
| MinGW-w64 GCC (`x86_64-w64-mingw32-gcc`) | 13+ | Rebuild steps only; optional |
| Ghidra | 11+ | Optional; manual re-decompilation |
| RenderDoc  PIX | any | Optional; runtime capture only |

The verification suite has no third-party Python dependencies for its core path. `scriptsextract_blobs.py` and `scripts/fp8_extract.py` optionally require `pefile`/`pefile`.

## Expected Inputs

The original proprietary DLLs are NOT redistributed. Place a local copy under `build` or pass the path explicitly:

| File | Known size | SHA-256 | MD5 |
|---|---|---|---|
| `amd_fidelityfx_upscaler_dx12.dll` | 15,605,520 bytes | SHA-256 not published — source packages vary by distribution; record your local SHA-256 in replication reports | not recorded |
| `fsr_data.dll` | 893,388 bytes | `9190608e7f5edcdec060e8b00f3eb6bc4c675feee94d687162da6968f26c0491` | `cb1aa61c71c33b25549ed59c1551d661` |

The `WEIGHTS_DIR` environment variable points at a directory holding a locally extracted blob set (default: `extractedv410_initializers`). Set it to validate a non-default extraction path:

```
export WEIGHTS_DIR=path/to/your/extracted/v410_initializers
```

## Commands

1. Run the static verification suite:
   ```
   python scriptsverify.py
   ```
2. Run the blob-lookup verification (requires MinGW-rebuilt DLL):
   ```
   python rebuildtest_blob_lookup.py
   ```
3. Run the claim-honesty guardrail:
   ```
   python scriptsvalidate_claims.py
   ```

## Expected Outputs

- `scriptsverify.py` produces `verification-report.json`: 87 PASS, 0 FAIL, 1 SKIP. The SKIP is `Optional HLSL source directory not supplied`.
- `scriptsvalidate_claims.py` exits 0 with `Claim validation passed`.
- Any test counting NM requires N == M to be a PASS (self-validation guard in `verify.py`).

## Failure Modes

| Symptom | Cause | Action |
|---|---|---|
| Tests SKIP with "DLL not found" | DLL absent from `build` | Expected without proprietary input. Supply a local DLL or accept SKIP. |
| Rebuild steps SKIP | MinGW not installed | Install `mingw-w64` or skip rebuild checks; core suite still passes. |
| `scriptsverify.py` FAIL on blob size | Blob corrupted or wrong preset | Re-extract from your local DLL via `scripts/extract_blobs.py`. |
| `validate_claims.py` FAIL | Overclaim language detected | Fix wording; never edit the guardrail to silence a real overclaim. |

## Reproducing Extraction Independently

```
python scriptsextract_blobs.py --dll /path/to/amd_fidelityfx_upscaler_dx12.dll --output-dir extracted/v410_initializers
python scriptsfp8_extract.py --blob extracted/v410_initializers/quality.bin
```

Compare your re-extracted MD5 against the values in `evidence-manifest.json`. The five standard presets share MD5 `6ccdb68fc828e0bef93fa32fd144c4f6`; the DRS preset is `8e5c042e0c14cca83d56ed13df5f02dd`.
