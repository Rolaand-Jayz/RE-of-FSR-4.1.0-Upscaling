# Synthetic D3D12 Capture Test Plan

**Goal:** Validate the capture hooks on a minimal compute-shader application with fully known state before deploying them against FSR 4.1.0. A synthetic app removes ambiguity: if the capture output does not match the known inputs, the hook is broken, not the target.

## Test Application Specification

A minimal Direct3D 12 compute application with no graphics dependencies:

- A single root signature with known bindings:
  - Root parameter 0: CBV (b0), 64 bytes, known contents.
  - Root parameter 1: SRV (t0), a 256-element structured buffer with known contents.
  - Root parameter 2: UAV (u0), a 256-element structured buffer output.
- A trivial compute shader: reads t0, adds the CBV value, writes u0.
- A single dispatch: `Dispatch(7, 1, 1)` — 7 thread groups. This exact dimension is the assertion target.

## Expected Capture Output

The capture must produce a JSON object conforming to `runtime-validation/schema.json` with these exact values:

| Field | Expected Value |
|---|---|
| `dispatch_index` | 0 |
| `dispatch_dimensions` | [7, 1, 1] |
| `cbv_values.cbv_0.size_bytes` | 64 |
| `cbv_values.cbv_0.hex_dump` | matches the 64 known bytes |
| `srv_resource_ids` | 1 entry resolving to the input buffer |
| `uav_resource_ids` | 1 entry resolving to the output buffer |
| `pso_hash` | SHA-256 of the compiled CS bytecode |
| `root_signature_hash` | SHA-256 of the serialized root signature |
| `barriers` | UAV transition to UNORDERED_ACCESS before, to COMMON after |

## Pass / Fail Criteria

- PASS: every expected field matches. The hook is trusted for FSR4 deployment.
- FAIL on dispatch dimensions: hook miscounts thread groups — do not use on FSR4.
- FAIL on CBV hex dump: hook does not resolve constant-buffer contents — CBV-value claims cannot be upgraded.
- FAIL on resource IDs: hook does not resolve descriptor heaps — descriptor-binding claims cannot be upgraded.

## Purpose

This plan proves the hooks work against a controlled target. Only after a clean synthetic run should the same hooks be pointed at FSR 4.1.0. Captures taken with an unvalidated hook are not admissible as runtime evidence.
