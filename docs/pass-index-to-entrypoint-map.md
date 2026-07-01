# Pass Index to DXIL Entrypoint Map

This repo tracks two different naming systems that were previously blurred together:

1. Descriptor-slot / host-dispatch labels from the provider DLL: `pass_0` .. `pass_26`, `rcas`, `spd_autoexposure`, `debug_view`
2. DXIL model-family entrypoints from the extracted shader corpus: `prepass`, `pass1` .. `pass12`, `pass0_post` .. `pass12_post`, `postpass`

They are both real. They are not currently proven to be a one-to-one rename of the same 30 host-dispatched slots.

## What is directly backed by committed artifacts

| Artifact | What it proves |
|---|---|
| `reports/main_dll_analysis.md` | Host/provider descriptor table at RVA `0x115cf0`, 30 slots, labels `pass_0` .. `pass_26`, `rcas`, `spd_autoexposure`, `debug_view` |
| `reports/host-cbuffer-dispatch.json` | Actual static dispatch order in `FUN_18000d5b0`: optional SPD/AutoExposure before the 27-pass loop, optional RCAS/debug after |
| `spec/dxil-entrypoint-inventory.json` | DXIL model-family taxonomy contains `prepass`, `pass1..pass12`, `pass0_post..pass12_post`, `postpass`; no main `pass0`; no `pass13` entrypoint |
| `reports/dxil-ir-pass-mapping.json` | Concrete blob-to-entrypoint mapping for the 27 model-family entrypoints |
| `spec/shader_analysis.json` | Per-entrypoint resource/shape summaries for the model-family shaders |

## Current bridge status

A committed artifact that proves descriptor index -> DXBC blob -> DXIL entrypoint for every host slot is not in this repo yet.

That means the table below intentionally separates confirmed facts from unresolved bridge claims instead of pretending the mapping is already proven.

| Descriptor index | Current host label | Runtime dispatch class | Proven DXIL entrypoint | Status |
|---:|---|---|---|---|
| 0-26 | `pass_0` .. `pass_26` | 27-slot model loop in `FUN_18000d5b0` | Not yet bridged one-to-one in committed evidence | Unresolved bridge |
| 27 | `rcas` | Optional post-loop sharpen pass | Not part of the 27-entrypoint model-family inventory | Separate host slot |
| 28 | `spd_autoexposure` | Optional pre-loop SPD/AutoExposure pass | Not part of the 27-entrypoint model-family inventory | Separate host slot |
| 29 | `debug_view` | Optional post-loop debug visualization pass | Not part of the 27-entrypoint model-family inventory | Separate host slot |

## Confirmed DXIL model-family inventory

| DXIL entrypoint class | Names | Count | Evidence |
|---|---|---:|---|
| Prepass | `fsr4_model_v07_fp8_no_scale_prepass` | 1 family | `spec/dxil-entrypoint-inventory.json` |
| Main passes | `fsr4_model_v07_fp8_no_scale_pass1` .. `pass12` | 12 families | `reports/dxil-ir-pass-mapping.json` |
| Scatter/post companions | `fsr4_model_v07_fp8_no_scale_pass0_post` .. `pass12_post` | 13 families | `reports/dxil-ir-pass-mapping.json` |
| Postpass | `fsr4_model_v07_fp8_no_scale_postpass` | 1 family | `reports/dxil-ir-pass-mapping.json` |

Total model-family entrypoints: 27.

## Order taxonomy

These four orderings should not be conflated:

| Ordering type | Current evidence |
|---|---|
| PSO/descriptor-slot index order | `pass_0` .. `pass_26`, `rcas`, `spd_autoexposure`, `debug_view` in the 30-slot descriptor table |
| Actual dispatch order | Optional SPD/AutoExposure -> 27-slot model loop -> optional RCAS -> optional Debug View |
| Conditional execution order | SPD gate checked before the loop; RCAS and debug gates checked after the loop |
| DXIL entrypoint naming order | `prepass`, `pass1..pass12`, `pass0_post..pass12_post`, `postpass` |

Until a direct bridge artifact is committed, validators should treat descriptor-slot names and DXIL entrypoint names as separate taxonomies with an unresolved join.
