---
name: Native D3D12 Capture
about: Submit a native Windows D3D12 runtime capture to upgrade static claims to runtime-observed
title: "[CAPTURE] <GPU model> - <game>"
labels: runtime-capture
---

## Environment

- GPU model:
- Driver version:
- Game / sample:
- Capture tool used (and version):

## DLL Hashes (SHA-256)

- amd_fidelityfx_upscaler_dx12.dll:
- fsr_data.dll:

## Capture Summary

- Number of dispatches captured:
- Quality preset captured:
- Frames captured:

## Attachments

Attach the capture log/JSON conforming to `runtime-validation/schema.json`. Do not attach original DLLs or decompiled source — only dispatch logs and constant-buffer dumps.

## Checklist

- [ ] Capture taken on native Windows D3D12 (no Proton/VKD3D)
- [ ] GPU is RX 9000-series or better
- [ ] Output conforms to runtime-validation/schema.json
- [ ] All required fields populated (no PLACEHOLDER values)
