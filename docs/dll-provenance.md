# DLL Provenance

This document records the source of the original FSR 4.1.0 binaries analyzed in this repository. It is a factual record, not a legal opinion.

## Original Binaries

| Field | Value |
|---|---|
| Package | `amd_fidelityfx_upscaler_dx12.dll` (FSR 4.1.0 upscaler provider) and `fsr_data.dll` (weight container) |
| Version | FSR 4.1.0 |
| amd_fidelityfx_upscaler_dx12.dll SHA-256 | [to be filled — confirm against your local copy] |
| fsr_data.dll SHA-256 | [to be filled — confirm against your local copy] |
| fsr_data.dll MD5 (recorded) | `cb1aa61c71c33b25549ed59c1551d661` |
| amd_fidelityfx_upscaler_dx12.dll size | 15,605,520 bytes |

## Acquisition Path

The binaries were acquired from a distribution context independent of an EULA-governed download for research purposes. The analysis was performed on the distributed binary as-is.

Note: No EULA was accepted during acquisition for research purposes.

## What Is and Is Not Redistributed

- The original DLLs are NOT committed to this repository.
- Extracted weight blobs (numerical parameters) ARE committed, with hashes recorded in `evidence-manifest.json` for independent verification.
- Rebuilt artifacts in `rebuild/` are reconstructed from RE'd source plus extracted data, not copies of the original binary.

See `LEGAL.md` for the full risk assessment and `docs/known-official-baseline.md` for AMD's supported product context.
