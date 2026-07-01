# Runtime Validation

This directory defines what a native D3D12 runtime capture must contain to upgrade the repository's static claims to runtime-observed status. No valid runtime capture currently exists.

## What a valid capture requires

- Operating system: native Windows with D3D12 (no Proton, no VKD3D translation layer).
- GPU: AMD Radeon RX 9000-series or better (FSR 4 upscaling is gated to this hardware class).
- A game or sample running FSR 4.1.0 via `amd_fidelityfx_upscaler_dx12.dll`.
- A capture tool that resolves D3D12 descriptor heaps and records per-dispatch state: RenderDoc (D3D12 mode), PIX, or an equivalent.

## Why the current capture is insufficient

The capture attempts in `runtime-capture/` and `tools/` were performed on Linux via Proton/VKD3D. All three methods (FFX proxy DLL, Vulkan `LD_PRELOAD` shim, RenderDoc full capture) failed to capture the FSR4 neural-network dispatches. The Vulkan translation layer either did not route the hooks or captured auxiliary post-processing shaders rather than the FSR4 model core. A Linux/Proton path captures the wrong shaders and cannot validate the static D3D12 analysis.

## What schema.json defines

`schema.json` is the minimum field set a capture must provide. The required fields are:

- `dispatch_index`, `pso_hash`, `root_signature_hash`
- `descriptor_table_handles`, `cbv_values` (GPU VA + hex dump)
- `srv_resource_ids`, `uav_resource_ids`
- `barriers`, `dispatch_dimensions`, `timestamp_ns`

Plus `frame_metadata` (GPU, driver, game, DLL SHA-256 hashes, capture tool). `sample-capture.redacted.json` shows the schema applied to three illustrative dispatches (prepass, pass1, pass1_post) with PLACEHOLDER values.

## How to submit a capture

1. Capture one or more frames on native Windows D3D12 hardware.
2. Export per-dispatch state conforming to `schema.json`.
3. Open a GitHub issue using the "Native D3D12 Capture" template.
4. Attach the capture log/JSON and the DLL SHA-256 hashes from your system.

Do not attach the original DLLs or decompiled source. Only the dispatch logs and constant-buffer dumps are needed.
