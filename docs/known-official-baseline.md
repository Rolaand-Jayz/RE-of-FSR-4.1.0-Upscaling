# Known Official Baseline

This document records AMD's official SDK context for FSR 4.x and separates it from this repository's research goals. It exists to prevent confusion between supported product behavior and unsupported reverse-engineering analysis.

## AMD FidelityFX SDK 2.0

- AMD FidelityFX SDK 2.0 provides SDK 2.0 technologies as prebuilt, signed DLLs. Integrators consume these binaries; the SDK 2.0-era sources for FSR 4 were not published as open source through the standard SDK distribution (FSR 1.0 through 4.0.2 were previously released under the MIT license via GPUOpen).
- FSR 4 upscaling is gated to AMD Radeon RX 9000-series GPUs or better. This is a hardware and driver requirement enforced by the shipped binaries.

## Relationship to This Repository

This repository is an independent static analysis of the FSR 4.1.0 upscaler binaries. It is not affiliated with, endorsed by, or derived from AMD's SDK distribution. The research goals (weight extraction, pipeline dispatch analysis, architecture characterization) are separate from AMD's supported integration path.

## What This Repository Is Not

- Not validated for game runtime use.
- Not a supported replacement DLL.
- Not a drop-in substitute for the signed AMD binaries.
- Not affiliated with the AMD FidelityFX SDK.

Any functional use of artifacts in this repository is unsupported and unverified at runtime.
