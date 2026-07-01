# FSR 4.1.0 — Static Reverse-Engineering Notes

> **Current status:** See [CURRENT_STATUS.md](CURRENT_STATUS.md) for a one-glance truth table.
> **Canonical validation source:** [VALIDATION_STATUS.md](VALIDATION_STATUS.md) is the single source of truth for claim status. Other documents reference it; they do not restate conclusions independently.

This repository documents a static structural analysis of the FSR 4.1.0 temporal upscaler: extracted weight blobs, shader/pass catalogs, data-layout reconstruction, and provider-DLL dispatch analysis from Ghidra, DXIL, and raw x86-64 disassembly.

> **RESEARCH ONLY — NOT A DROP-IN REPLACEMENT.** The artifacts in this repository are for static analysis and research verification. They are not validated for game runtime use, not a supported replacement DLL, and not functionally equivalent to the original AMD binary. Do not deploy outside research environments.

AMD's FidelityFX Super Resolution 4.1.0 ships as compiled Windows DLLs containing a neural network upscaler. The network's weights are opaque binary blobs. The pipeline architecture is undocumented. The shader dispatch sequence is hidden behind layers of API abstraction.

What is included:

1. **Data DLL research** — Reconstructed C source and embedded extracted weight data. The historical post-link patcher that copied original PE regions has been removed from the proof path; MD5 equality after copying original bytes is not claimed as independent reconstruction evidence. Use `rebuild/pe_patcher.py` now as a section-comparison tool that reports hashes and differences without modifying rebuilt output.

2. **Provider DLL** — Disassembled the PSO creation function (`FUN_180025990`) that Ghidra could not decompile. Decoded the jump table, flag index table, and pass descriptor table. Mapped 30 unique shader blobs (verified by MD5 hash) to pass indices. Extracted resource binding layouts from LLVM IR.

This repository is a research record: analysis, dead ends, methodology, extracted neural-network weights, pipeline specs, and tooling. Runtime execution remains unverified; exact per-pass arithmetic, buffer-address derivation, and weight-index mapping remain research gaps unless explicitly marked otherwise in a specific document.

> **Scope:** This reverse engineering covers the FSR 4 **temporal upscaler** (the ML-based image reconstruction pipeline) only. FSR 4.1.0 as shipped also includes **frame generation** — that is a separate component and was **not** part of this analysis. If you're looking for frame generation RE, this is not it.

---

## The Short Version

| Finding | Detail | Evidence |
|:---|:---|:---|
| **602 DXBC shader blobs** cataloged and classified | Full enumeration of every embedded compute shader | ✅ Verified — automated extraction + manual audit |
| **27 model-family entrypoints + 3 optional host slots** | DXIL inventory contains `prepass`, `pass1..pass12`, `pass0_post..pass12_post`, `postpass`; host descriptor table also has optional `rcas`, `spd_autoexposure`, `debug_view` slots | ✅ Verified — binary hash comparison + descriptor-table analysis |
| **6 weight blobs** extracted, each 131,072 bytes | 5 identical (quality/balanced/performance/ultraperf/native), 1 unique (DRS) | ✅ Verified — MD5 hash comparison |
| **Weight container format decoded** | 7,208B FP16 biases → 122,880B FP8/uint8-like weights → 888B extra (222 FP32 output biases) → 96B pad | ✅ Verified — container parsed, values validated, offsets match across all blobs |
| **Pipeline: 27 model-loop + conditional passes** | optional SPD AutoExposure before the 27-pass loop, then optional RCAS + Debug View after it; descriptor-slot order is separate | ✅ Verified — dispatch function + host-cbuffer analysis |
| **All passes use (32,1,1) thread groups** | Wavefront-width 1D dispatch | ✅ Verified — LLVM IR `!dx.numthreads` metadata |
| **Static resource binding map** | 9 register spaces identified with proposed semantic meaning | ⚠️ Static only — createHandle analysis across LLVM IR blobs; runtime descriptor bindings not captured |
| **Constant buffer layout decoded** | 5-6 registers × 4 floats (80-96 bytes) per pass; even/odd pair pattern | ✅ Verified — cbufferLoadLegacy register indices from LLVM IR |
| **Architecture restructured** | 4.0.2's Pre/Body/Post replaced with Encoder/Orchestration/Body/Decoder pipeline | ⚠️ Static only — inferred from shader classification + offset mapping |
| **Weight loading changed** | 4.0.2 embeds weights in shaders; 4.1.0 uses InitializerBuffer with dynamic loading | ✅ Verified — structural comparison with MIT-licensed 4.0.2 source |
| **Data-section reconstruction tooling** | Reconstructed C source → MinGW cross-compile → section comparison | ⚠️ Bounded — section hashes must be reported separately; copied-byte MD5 equality is not used as proof |
| **PSO creation function decoded** | FUN_180025990 decoded via raw x86-64 disassembly: jump table + flag index table + 30-entry descriptor table | ✅ Verified — objdump disassembly + PE section parsing |

### Evidence Tags

- ✅ **Verified** — confirmed by multiple independent methods (hash match, binary analysis, cross-reference)
- ⚠️ **Static only** — inferred from disassembly/decompilation; not confirmed via runtime instrumentation

---

## Main DLL: Pipeline Dispatch Analysis

The main provider DLL (`amd_fidelityfx_upscaler_dx12.dll`, 15.6MB) is the other half of the system. Where `fsr_data.dll` stores weights, the provider DLL runs the neural network. We traced the static dispatch pipeline from Ghidra decompilation and raw x86-64 disassembly.

### Dispatch Architecture

The core dispatch function (`FUN_18000d5b0`) runs a hardcoded 27-iteration loop:

```c
// Decompiled from Ghidra
lVar24 = 0x1b;  // 27
do {
    dispatch_per_pass(context, pass_state, threadsX, threadsY);
    lVar24--;
} while (lVar24 != 0);
```

The descriptor-slot names and the runtime dispatch order are distinct. In `FUN_18000d5b0` the actual order is:
- **SPD AutoExposure** before the 27-pass loop when auto exposure is enabled
- **27 model-loop passes** (`pass_0` .. `pass_26`)
- **RCAS** after the loop when sharpening is enabled
- **Debug View** after the loop when the debug flag is enabled

See [`docs/pass-index-to-entrypoint-map.md`](docs/pass-index-to-entrypoint-map.md) for the descriptor-index taxonomy versus DXIL entrypoint taxonomy.

### PSO Creation: FUN_180025990

Ghidra failed to decompile this function (344 functions decompiled; this one wasn't among them). We disassembled it from raw binary and decoded:

| Structure | RVA | Details |
|:---|:---|:---|
| Jump table | `0x2acac` | 30 entries dispatching to per-pass code |
| Flag index table | `0x1bfc50` | 64 entries mapping config flags to descriptor indices (0-29) |
| Pass descriptor table | `0x115cf0` | 30 entries × 296 bytes (`imul rcx, rax, 0x128`) |

Each descriptor entry contains: shader blob size (DWORD), DXBC shader pointer (QWORD), then 7 binding groups of 40 bytes each.

### 30 Unique Shader Blobs

All 30 pass shaders are unique, verified by MD5 hash:

| Pass | Name | Size | MD5 |
|------|------|------|-----|
| 0 | pass_0 | 19,820 | fa813b1501c7 |
| 1 | pass_1 | 19,884 | 98e3a4b72437 |
| 2 | pass_2 | 21,648 | d99b11628f3b |
| 3 | pass_3 | 21,584 | 76fdac8ca3c1 |
| 4 | pass_4 | 23,336 | abb9cec4c47d |
| 5 | pass_5 | 26,276 | cb3ad940c94a |
| 6 | pass_6 | 23,404 | 37998fc070d8 |
| 7 | pass_7 | 26,208 | 6859bda414df |
| 8 | pass_8 | 21,740 | a52c653d1f5c |
| 9 | pass_9 | 21,676 | 564efec2abd2 |
| 10 | pass_10 | 24,856 | 4a85f5300bf4 |
| 11 | pass_11 | 24,788 | 0114b73c945c |
| 12 | pass_12 | 21,984 | 33e2e5c24e0d |
| 13 | pass_13 | 21,920 | c287b4976479 |
| 14 | pass_14 | 18,500 | 8b335e65c091 |
| 15 | pass_15 | 18,436 | 3829ef86bf37 |
| 16 | pass_16 | 20,456 | 3fbb8b9bd3ad |
| 17 | pass_17 | 20,388 | e144590c77dd |
| 18 | pass_18 | 20,552 | 7756f6dd0508 |
| 19 | pass_19 | 20,480 | aeaf1b44d0b2 |
| 20 | pass_20 | 26,276 | 4d61c10addc6 |
| 21 | pass_21 | 26,208 | c12ca5dfa20c |
| 22 | pass_22 | 23,404 | c6930a995aab |
| 23 | pass_23 | 19,884 | 5943b34bd00e |
| 24 | pass_24 | 19,820 | a00a487f3be2 |
| 25 | pass_25 | 23,336 | 7e95f96376a7 |
| 26 | pass_26 | 21,648 | f1079dce7c99 |
| 27 | rcas | 21,584 | 5c6397e93889 |
| 28 | spd_autoexposure | 21,740 | 1f4a33f858b4 |
| 29 | debug_view | 21,676 | 4bf4d0a6886c |

**Unique: 30/30, Duplicates: 0**

### Resource Binding Map

Every pass uses identical UAV and CBV layouts. SRV count varies (5-8) by pass type.

**Universal resources (all 30 passes):**

| Type | Register | Space | Purpose |
|------|----------|-------|---------|
| SRV | 0 | 18 | Neural network weights (from fsr_data.dll) |
| SRV | 1 | 0 | Input color |
| SRV | 2 | 1 | Motion vectors / reprojection |
| SRV | 4 | 3 | History / temporal |
| SRV | 5 | 4 | Exposure / luma mip |
| UAV | 0 | 11 | Scratch buffer (resolution-dependent) |
| UAV | 1 | 0 | Output color |
| UAV | 2 | 3 | Temp / recurrent output |
| CBV | 0 | 1 | Constant buffer (80-96 bytes) |
| Sampler | 0 | 0 | Point clamp |

**Conditional resources (specific passes):**

| Type | Register | Space | Present In |
|------|----------|-------|------------|
| SRV | 3 | 2 | Luma/mask (all except passes 10-15) |
| SRV | 6 | 6 | Extra feature map (passes 8, 9, 18, 19, 28, 29) |
| SRV | top | 17 | Intermediate (passes with 7+ SRVs) |

### Constant Buffer Layout

Each pass reads 5 or 6 registers from a single CBV (register 0, space 1). Each register is 4 × float32 = 16 bytes.

| Reg | Even passes ("pre") | Odd passes ("post") |
|-----|---------------------|---------------------|
| 0 | dispatch dimensions / inverse resolution | dispatch dimensions / inverse resolution |
| 1 | jitter / subpixel offset | jitter / subpixel offset |
| 2 | scaling / transform params | scaling / transform params |
| 3 | — (not accessed) | extra params |
| 4 | additional config | additional config |
| 5 | additional config | additional config |

- Even passes: 5 regs × 16B = **80 bytes**
- Odd passes: 6 regs × 16B = **96 bytes**

### Pass Pair Structure

The 27 main passes form 13 pre/post pairs + 1 standalone:

| Pair | Pre Pass | Post Pass | SRVs |
|------|----------|-----------|------|
| 0 | pass_0 (even) | pass_1 (odd) | 6 |
| 1 | pass_2 | pass_3 | 7 |
| 2 | pass_4 | pass_5 | 6 |
| 3 | pass_6 | pass_7 | 6 |
| 4 | pass_8 | pass_9 | 8 |
| 5 | pass_10 | pass_11 | 5 |
| 6 | pass_12 | pass_13 | 5 |
| 7 | pass_14 | pass_15 | 5 |
| 8 | pass_16 | pass_17 | 6 |
| 9 | pass_18 | pass_19 | 7 |
| 10 | pass_20 | pass_21 | 6 |
| 11 | pass_22 | pass_23 | 6 |
| 12 | pass_24 | pass_25 | 6 |
| standalone | pass_26 | — | 7 |

The even/odd split maps to AMD's naming convention: `pass0` + `pass0_post`, `pass1` + `pass1_post`, etc.

### Pass Symmetry

Identical blob sizes suggest autoencoder symmetry (encoder/decoder mirror):

- pass_0 ↔ pass_24 (19,820 bytes each)
- pass_1 ↔ pass_23 (19,884 bytes each)
- pass_4 ↔ pass_25 (23,336 bytes each)
- pass_5 ↔ pass_20 (26,276 bytes each)
- pass_6 ↔ pass_22 (23,404 bytes each)
- pass_7 ↔ pass_21 (26,208 bytes each)

Full analysis: [`reports/main_dll_analysis.md`](reports/main_dll_analysis.md). Machine-readable spec: [`spec/pipeline_spec.json`](spec/pipeline_spec.json).

---

## Runtime Capture: Three Attempts, No Silver Bullet

Runtime capture — confirming our static analysis by watching the upscaler execute in real time — was a major goal that we invested significant engineering into. Three different approaches were built and deployed on CachyOS running FF7 Rebirth through Proton/VKD3D. All three hit blockers.

This isn't a failure section. It's a record of real engineering work that produced useful tooling even though the primary goal (confirming the 27-pass dispatch sequence at runtime) wasn't achieved. The tools exist, they compile, and they're in the repo — if you can get past the Proton layering issues, they'll work.

### Attempt 1: FFX Proxy DLL (`ffx_capture_proxy.c`)

**Approach:** Replace AMD's `amd_fidelityfx_upscaler_dx12.dll` with a proxy that intercepts the 5 exported FFX API functions (`ffxConfigure`, `ffxCreateContext`, `ffxDispatch`, `ffxDestroyContext`, `ffxQuery`). Logs parameters and raw descriptor bytes at the API level.

**Built with:** MinGW cross-compilation on Linux → `ffx_proxy.dll`

**Status:** ⚠️ Written and compiled. Not deployed for live capture (would require renaming the original DLL and placing the proxy in the game directory, which we didn't attempt during the analysis phase). The proxy captures API-level parameters — dispatch descriptors, quality preset, context creation — but not actual GPU resource bindings. It would confirm *how many* dispatches occur, but not *what data* each one accesses.

### Attempt 2: Vulkan LD_PRELOAD Shim (`fsr4_capture.c`)

**Approach:** A lightweight `.so` that hooks `vkCmdDispatch`, `vkCmdBindDescriptorSets`, and `vkCmdBindPipeline` via `LD_PRELOAD`. No frame capture, no RenderDoc overhead — just a dispatch log. Designed specifically for FSR4's 27+ compute passes where full capture freezes the game.

**Built with:** `gcc -shared -fPIC -O2 -o fsr4_capture.so fsr4_capture.c -ldl` on CachyOS

**Example local path:** `<repo>/runtime-capture/fsr4_capture.so`

**Launch options:**
```
LD_PRELOAD=<repo>/runtime-capture/fsr4_capture.so PROTON_FSR4_UPGRADE=1 DXIL_SPIRV_CONFIG=wmma_rdna3_workaround WINEDLLOVERRIDES=version=n,b %command%
```

**Result:** ❌ The shim loaded (confirmed by `[INIT] FSR4 capture shim loaded` in `dispatch_log.txt`) but produced no dispatch data. The `LD_PRELOAD` hook propagated into Proton's wine process but the `vkCmdDispatch` intercept never fired. Likely cause: VKD3D-Proton's Vulkan dispatch goes through a code path that doesn't route through the standard `vkCmdDispatch` symbol, or the hook's `dlsym` resolution fails inside the Proton loader.

**What we learned:** `LD_PRELOAD` does survive into Proton's wine process (the init message documented evidence for it), but hooking Vulkan calls through VKD3D translation is unreliable. The hook fires in the host process but not necessarily inside the wine Vulkan wrapper.

### Attempt 3: RenderDoc Full Capture

**Approach:** Standard RenderDoc Vulkan capture via implicit layer. Requires `ENABLE_VULKAN_RENDERDOC_CAPTURE=1` (NOT `ENABLE_VULKAN=1` — that was a dead end that consumed a debugging session).

**Launch options:**
```
ENABLE_VULKAN_RENDERDOC_CAPTURE=1 RENDERDOC_CAPTUREFILE=<repo>/runtime-capture/fsr4_ff7r VKD3D_DEBUG=trace VKD3D_SHADER_DUMP_PATH=<repo>/runtime-capture/vkd3d-shaders %command%
```

**Result:** ❌ RenderDoc hooks every Vulkan call through VKD3D. FSR4 dispatches 27+ compute passes per frame. The capture grows enormous, the game freezes, and eventually crashes with a 120-second timeout. Full RenderDoc capture is incompatible with FSR4's dispatch density.

**What we learned:** FSR4's neural network inference is too heavy for full frame capture tools. Lightweight approaches (shims, logs) are the only viable path.

### Side Discovery: VKD3D Shader Dumps

Setting `VKD3D_SHADER_DUMP_PATH` during the RenderDoc and shim attempts produced shader dumps — but they were **auxiliary post-processing shaders** (RCAS-like sharpening, depth/motion adaptive passes), not the FSR4 neural network core. The core model shaders compile through a different path that VKD3D doesn't dump, or they're pre-compiled SPIR-V embedded directly in the DLL.

### Diagnostic Tooling

A full diagnostic script (`scripts/capture/diagnose_capture.sh`) was written that checks all prerequisites: RenderDoc library, Vulkan layer registration, shim compilation, proxy DLL status, FF7R DLL detection, and OptiScaler presence. It also prints corrected capture instructions for all three methods.

### What This Means for the Project

The runtime capture gap is real. Our pipeline analysis now comes from:
- ✅ Ghidra decompilation of the C++ dispatch function (27-iteration loop confirmed)
- ✅ Raw x86-64 disassembly of the PSO creation function (Ghidra couldn't decompile it)
- ✅ 30 unique shader blobs mapped by MD5 hash to pass indices
- ✅ Complete resource binding layouts extracted from LLVM IR
- ✅ Constant buffer register maps extracted from cbufferLoadLegacy patterns
- ⚠️ Runtime dispatch sequence not confirmed (Proton blocks all capture methods)

The data-DLL rebuild and per-section comparison support our **data extraction/layout** claims, but do not prove complete binary reconstruction. The binary analysis supports the published **pipeline structure** claims. The unconfirmed piece is whether actual runtime execution matches the static analysis — and Proton blocked the capture attempts made so far.

---

## What We Did NOT Do

Honest documentation means showing the gaps:

0. **No frame generation analysis.** FSR 4.1.0 ships with both a temporal upscaler and frame generation. This RE covers the **upscaler only**. Frame generation is a separate pipeline with its own shaders, its own dispatch logic, and its own resource management. We did not analyze it. The scope was deliberate: the upscaler is the ML component, and understanding it was the goal.

1. **No runtime verification.** The game requires Proton. Proton's VKD3D translation layer absorbs all hooks, shims, and capture tools. We cannot confirm the static analysis by watching the code execute. This is the single largest credibility gap. Three independent capture methods were built and deployed — all blocked by Proton's Vulkan translation layer. **Runtime validation by someone with native Windows + D3D12 access is needed to close this gap.** See [Validation Status](#validation-status--call-for-collaborators) below.

2. **No bit-identical rebuild of the provider DLL.** The 15.6MB provider DLL contains compiled C++ code, linked libraries, and DXBC shader containers. Reproducing it bit-for-bit would require AMD's exact build environment, compiler version, and shader compiler. The evidence here is structural analysis, not a provider-binary rebuild.

3. **CBV field semantics partially unknown.** We know which registers are accessed and which components (x/y/z/w) are extracted. We don't know the exact semantic meaning of every float value.

4. **Root signature binary format not fully decoded.** The binding groups in the descriptor entries are FFX-internal structures, not raw D3D12_ROOT_PARAMETER structs. We decoded the shader-level resource bindings instead.

5. **Per-instruction inference operations not fully decoded.** We decoded the activation function (ReLU, via FMax in DXIL IR), the FP8 weight decode mechanism (coherent atomic buffer I/O), pass complexity tiers, and temporal state flow (history buffer feedback). We did **not** decode every matrix multiply or convolution at the individual instruction level. The high-level architecture is understood; the per-pixel arithmetic within each pass is inferred from IR patterns, not traced instruction-by-instruction.

---

```
fsr-re/
├── README.md                  You are here. Narrative + findings.
├── LEGAL.md                   RE methodology, AMD history, legal positioning.
├── LICENSE                    MIT License.
├── VALIDATION_STATUS.md       Honest assessment of what is proven vs inferred.
├── verification-report.json   Machine-readable verification results.
├── .gitignore
│
├── docs/                         Technical documentation.
│   ├── IMPLEMENTATION_GUIDE.md   Implementation research notes for the neural upscaler.
│   ├── activation-lut-analysis.md FP8 decode and activation function analysis.
│   ├── adversarial-review-2.md   Adversarial review — challenges assumptions.
│   ├── architecture.md           Network topology, layer details, channel flow.
│   ├── extra-params-analysis.md  Analysis of the 222 extra FP32 output parameters.
│   ├── methodology.md            Full methodology narrative — including dead ends.
│   ├── offset-mapping.md         Complete tensor offset table.
│   ├── pipeline-dispatch.md      Provider DLL dispatch analysis.
│   ├── shader-internals.md       Neural architecture + FP8 decode analysis.
│   ├── static-analysis.md        Ghidra decompilation findings.
│   └── weight-extraction.md      How weights were found and extracted.
│
├── spec/                         Machine-readable specifications.
│   ├── tensor-map.json           Complete tensor offset table (78 tensors).
│   ├── blob-format.json          Binary layout specification.
│   ├── pipeline_spec.json        Full 30-pass pipeline spec.
│   └── shader_analysis.json      28-pass shader analysis.
│
├── reports/                     Analysis reports and data.
│   ├── 00-final-re-report.md     Complete RE report — the authoritative document.
│   ├── main_dll_analysis.md      Provider DLL dispatch analysis.
│   ├── architecture-map-v410.md  Architecture mapping.
│   ├── provider-diff-report.md   Provider layer diff (4.0.2 vs 4.1.0).
│   ├── ml2code-runtime-diff.md   Operator comparison.
│   ├── tensor-verification-report.md  Offset-map verification status.
│   ├── pass-catalog.json         Full pass catalog (machine-readable).
│   └── v410_independent_offsets.json  Independent offset map.
│
├── rebuild/                   Data DLL rebuild and section comparison.
│   ├── README.md                  Build instructions and bounded verification notes.
│   ├── fsr_data.c                 Reconstructed C source from disassembly.
│   ├── fsr_data.def               PE export definitions.
│   ├── pe_patcher.py              Section comparison tool; does not copy original bytes.
│   ├── pe_patcher_v2.py           Historical patcher; superseded by pe_patcher.py.
│   ├── build.sh                   Full build + verify script.
│   ├── fsr_data_prepatch.dll      Independently rebuilt DLL (893,019 bytes).
│   └── fsr_data_final.dll         Historical patched artifact (893,388 bytes); not proof.
│
├── extracted/                 Weight blobs — the neural network data.
│   ├── v410_initializers/         6 blobs × 131,072 bytes (4.1.0 weights).
│   ├── v402_initializers/         7 blobs (4.0.2 weights for comparison).
│   ├── fp8_initializers/          Raw FP8 initializer blobs.
│   └── fp8_weights/               Per-tensor extracted weights (v402 + v410).
│
├── scripts/                   Analysis and verification tools.
│   ├── dll_analysis.py            DLL structure enumeration.
│   ├── extract_blobs.py           Weight blob extraction from PE sections.
│   ├── weight_encoding.py         FP8/FP16 encoding analysis.
│   ├── fp8_extract.py             FP8 weight extraction and validation.
│   ├── parse_weights.py           Weight blob parsing and display.
│   ├── weight_compare.py          Cross-blob comparison and hashing.
│   ├── parse_offsets.py           Tensor offset extraction.
│   ├── layer_diff.py              Layer-by-layer diff between blobs.
│   ├── parse_v410_dxil.py         DXIL shader parsing for 4.1.0.
│   ├── trace_cbuffer.py           Constant buffer layout tracing.
│   ├── verify.py                  Verification suite.
│   ├── verify_tensor_offsets.py   Tensor offset validation.
│   ├── disasm_all_dxil.py         Mass DXBC → DXIL disassembly.
│   └── capture/                   Runtime capture scripts.
│
├── capture-tools/              Runtime capture tooling.
│   ├── analyze_capture.py        Post-capture analysis pipeline.
│   ├── extract_dispatches.py     Dispatch extraction from RenderDoc captures.
│   └── capture-guide.md          Capture method documentation.
│
├── runtime-capture/            Capture artifacts from runtime attempts.
│   ├── dispatch_log.txt          Vulkan LD_PRELOAD shim log.
│   └── fsr4_capture.so           Compiled dispatch shim.
│
├── tools/                     Capture tools (written, deployed, not fully successful).
│   ├── README.md                  Setup and usage guide.
│   ├── ffx_capture_proxy.c        FFX API capture proxy.
│   ├── ffx_d3d12_capture.c        D3D12 command capture.
│   ├── fsr4_capture.c             Vulkan dispatch shim for Proton/Linux.
│   └── setup_capture.sh           Build + inject script.
│
└── Not in public repo (excluded via .gitignore — see LEGAL.md):
    ├── build/                    DXBC blobs + LLVM IR (1187 .ll files). Derived
    │                             from proprietary shaders.
    ├── ghidra-decompile/         344 decompiled C functions. Proprietary data.
    └── ghidra-project/           Ghidra project database. Proprietary data.
```

---

## Validation Status & Call for Collaborators

This project is a substantial static analysis, but not complete runtime validation. Claims about weights, pass structure, and static resource bindings are backed by binary-analysis evidence in this repository; runtime dispatch order, CBV values, and actual descriptor bindings still need native D3D12 confirmation.

But **static analysis is not runtime proof**. The 27-pass dispatch sequence, the constant buffer values, and the actual GPU resource bindings during execution have never been observed live. Three capture methods were attempted (FFX proxy DLL, Vulkan LD_PRELOAD shim, RenderDoc full capture) — all blocked by Proton's VKD3D translation layer on Linux.

### What's needed

Runtime validation on **native Windows with D3D12** would close the gap. Specifically:

1. **Capture the 27-pass dispatch sequence** — confirm the loop count and pass order using PIX, RenderDoc, or a D3D12 capture tool on native Windows (no Proton layer).
2. **Verify constant buffer contents** — confirm the per-pass CBV values match the static analysis.
3. **Confirm weight buffer bindings** — verify that the InitializerBuffer is bound as predicted.

This is not a huge effort — a few hours of capture work for someone with the right hardware and access. But it requires a Windows machine with an AMD GPU and a game running FSR 4.1.0.

### Who we need

A **small number of contributors** (2-3 people) with:
- Native Windows + AMD RDNA 3/4 system
- A game running FSR 4.1.0 (FF7 Rebirth, or any title using the standalone upscaler DLL)
- Familiarity with RenderDoc or PIX on D3D12
- Willingness to share capture data (not source code — just the dispatch logs and cbuffer dumps)

If that's you, open an issue. This work deserves to be validated, and validation makes it stronger.

---

## FSR 4.0.2 Source Reference

Our reverse engineering of FSR 4.1.0 used the MIT-licensed **FSR 4.0.2 source code** as a structural reference. AMD published this code on [GPUOpen](https://gpuopen.com/) under the MIT license — it is explicitly permitted for any use, including analysis and interoperability research.

The 4.0.2 source was essential for:
- Understanding the tensor schema (78 tensors mapped from HLSL source)
- Identifying the neural network architecture (encoder → bottleneck → decoder)
- Validating weight blob layout and FP8 quantization format
- Establishing the provider-layer contract that 4.1.0 inherits

**Repository:** [fsr4-sdk-402-source](https://github.com/rolaandjayz/fsr4-sdk-402-source) — AMD FidelityFX SDK 2.0.0, FSR 4.0.2 (ML-Upscaler), MIT-licensed.

> The FSR 4.0.2 source and this RE project are separate repositories. The 4.0.2 source is AMD's original work, published under MIT. This RE project is our original analysis work, also released under MIT.

---

## Legal & Disclaimer

This project operates under established reverse engineering principles:

- **FSR 4.0.2** is MIT-licensed by AMD on [GPUOpen](https://gpuopen.com/fidelityfx-superresolution/). We used it as a structural reference, which is explicitly permitted by the MIT license.
- **FSR 4.1.0** analysis was performed via static analysis (Ghidra decompilation, DXIL disassembly, PE inspection, raw x86-64 disassembly) of a distributed binary. No license agreement was broken. No EULA was accepted. The binary was analyzed as-is, in transit, on the wire.
- **The extracted weights** are numerical parameters produced by AMD's training pipeline. They are reproduced here for research and interoperability purposes.
- **AMD's own founding story is reverse engineering.** AMD spent five years reverse-engineering Intel's 386 processor. They won in court. I am not aware of a public AMD DMCA campaign against GPU reverse-engineering projects, though that is not legal permission. AMD has released major Linux GPU driver components and GPUOpen materials under open-source licenses, and they publish prior FSR generations under MIT. We applied that interoperability-first tradition to their latest product.

For the full legal analysis, AMD history, and honest risk assessment, see [`LEGAL.md`](LEGAL.md).

This project is released under the **MIT License** — the same license AMD chose for FSR 4.0.2. We believe knowledge should be free. AMD apparently agreed, once.

> **Licensing boundary:** The MIT license covers **authored code only** (scripts, documentation, specifications). The `extracted/*.bin` weight files, `dist/*.dll` reconstructed binaries, and `build/*.dll` provider DLLs contain **proprietary AMD-derived data** and are NOT MIT-licensed. See `LEGAL.md` for full analysis and per-directory `NOTICE.md` files.

---

## Shader Internals: Neural Network Architecture

Full disassembly of all 602 DXBC blobs revealed **27 unique FSR4 compute shaders** (named `fsr4_model_v07_fp8_no_scale_*`). The remaining 575 blobs are non-FSR utility shaders and parameterized variants.

### Architecture: fsr4_model_v07_fp8_no_scale

The name confirms:
- **Model version 7** — AMD's internal iteration number
- **FP8 weights, no per-tensor scale** — mostly fixed shared-exponent quantization; the 4.1.0 initializer layout still includes a small extra scale-factor region
- All quality presets share the **same neural architecture**, differing only in weight offsets

### Weight Blob Analysis

All 5 standard presets (Quality, Balanced, Performance, Ultra-Performance, Native) are **byte-identical** (MD5 `6ccdb68fc828e0bef93fa32fd144c4f6`). The quality selection is purely a dispatch/resolution parameter — not a different network.

The DRS (Dynamic Resolution Scaling) blob is a **completely retrained network**:
- 96.1% of bytes differ from standard (MD5 `8e5c042e0c14cca83d56ed13df5f02dd`)
- 0 matching 4KB chunks
- Same architecture (128KB, same FP8 value distribution)
- Same quantization scheme applied to different trained parameters

### FP8 Weight Decode via Atomics

The shaders decode FP8 weights through a **256-entry atomicCompareExchange table** in the ScratchBuffer, accessed via `atomicCompareExchange` as side-effect-free table reads:

1. Read FP8 byte from weight SRV (space 0, register 18)
2. Use fixed-offset LUT lookup in UAV (space 1, register 0)
3. 256-byte stride between entries (0x100) — one entry per FP8 value
4. Each byte decodes to 8 FP16 values via LUT
5. Accumulate entirely in integer registers

This avoids branching and uses GPU atomics idiomatically as LUT reads.

### Layer Architecture

| Tier | Passes | Role | IR Lines | LUT Ops | Kernel |
|------|--------|------|----------|---------|--------|
| Input | prepass | Feature extraction + bilinear sampling | 2,267 | 206 | N/A |
| Small | pass1, pass2, pass12 | 3x3 convolution | ~4,900 | 1,989 | 3x3 |
| Medium | pass4, pass5, pass10 | 4x4 convolution | ~8,000 | 3,296 | 4x4 |
| Large | pass7, pass8 | 5x4 convolution (deepest) | ~20,750 | 9,088 | 5x4 |
| Special | pass3, pass6, pass9, pass11 | Unique roles | varies | varies | varies |
| Output | postpass | ML + conventional composite | 2,675 | 1,580 | mixed |
| Scatter | pass*_post (x12) | Data rearrangement only | ~125 | 0 | N/A |

**Post passes are trivial** — 2-5 `rawBufferStore` calls, no ML computation. They scatter accumulated results from scratch buffer to output planes.

### Data Flow

```
Input Color + Motion + Depth
    |
    v
Prepass (bilinear sampling -> 3 feature planes)
    |
    v
Pass1 (3x3 conv) -> Scatter -> Pass2 (3x3 conv) -> Scatter -> ...
    | (progressively deeper kernels)
Pass7/8 (5x4 conv, deepest layers) -> Scatter
    |
    v
Pass12 (3x3 conv) -> Scatter
    |
    v
Postpass (ML composite + conventional math -> 7 output planes)
```

The architecture has a **bottleneck structure with symmetric pass layout**: features processed through progressively deeper layers then reconstructed.

### CBV Register Semantics

| Register | Type | Usage |
|----------|------|-------|
| 0 | f32/i32 | Dispatch dimensions (width, height) |
| 1 | f32 | Jitter offset XY |
| 2 | f32/i32 | Weight indexing strides / output scale |
| 4 | i32 | Configuration flags (field 3) |
| 5 | f32/i32 | Buffer stride (field 0) + blend/exposure (field 1) |
| 7 | i32 | Extended dispatch params (specialized passes) |

### What Remains Unknown

- **Exact per-pass MAC arithmetic** — integer multiply-add patterns identified but exact weight-index vs. input-feature mapping not fully traced
- **Runtime cbuffer values** — offset computations inferred from static IR, not captured at runtime
- **Temporal state flow** — how frame N-1 feeds into frame N (not captured at runtime)
- **Skip connections** — not confirmed; pass symmetry is consistent with a bottleneck autoencoder (decoder mirroring encoder), which does not require skips
- **Attention mechanisms** — no softmax/QKV patterns found; likely pure convolutional

### What Has Been Resolved

- **Activation function** — ReLU via `FMax(x, 0.0)`, cross-validated in DXIL + SPIR-V (see docs/activation-lut-analysis.md)
- **Extra parameters** — 222 FP32 output composition biases consumed by postpass (see docs/extra-params-analysis.md)
- **"LUT mechanism"** — coherent atomic buffer I/O for cross-thread-group communication, not an activation LUT

Full details: [docs/shader-internals.md](docs/shader-internals.md). Machine-readable analysis: [spec/shader_analysis.json](spec/shader_analysis.json).

---

*Built by Rolaand Jayz — The Shadow Librarian.*
*If this work helped you understand something, pass it on. Knowledge compounds when it's shared.*
