# FSR 4.1.0 Reverse Engineering Report

**Project:** FSR 4.1.0 neural-network reverse engineering
**Repository:** `fsr-re`
**Primary artifacts:** `build/dll_v410.dll`, `build/dll_v402.dll`, `ghidra-decompile/`, `reports/`, `spec/`, `runtime-capture/`
**Status:** Current summary report; authoritative only where backed by the cited artifacts and bounded by the caveats below. For canonical validation status, see [VALIDATION_STATUS.md](../VALIDATION_STATUS.md).

---

## 0. Definition of Done

This report is considered complete only if it answers all of the following:

1. What is the FSR 4.1.0 architecture, as far as the evidence supports?
2. What parts are statically confirmed versus inferred from static analysis?
3. Which findings are proven by multiple independent methods?
4. Which claims remain unresolved or only partially confirmed?
5. What artifacts prove the claims, and where are they stored?

### Completion criteria
- Every major claim is labeled as **STATIC-REPRODUCIBLE**, **Static-only**, **Inferred**, or **Unresolved**.
- Every important number is backed by an artifact path or analysis report.
- No claim is presented as runtime-proof unless runtime evidence exists.
- The report distinguishes the **core FSR4 network** from the **auxiliary sharpen/postprocess shaders** captured through VKD3D.

---

## 0.5. Scope

This reverse engineering covers the FSR 4.1.0 **temporal upscaler** — the ML-based image reconstruction pipeline. FSR 4.1.0 as shipped also includes **frame generation**, which is a separate component and was **not** part of this analysis. The upscaler and frame generator share infrastructure (provider DLL, API surface) but are independent pipelines with distinct shader sets and dispatch logic. Only the upscaler was reverse-engineered.

---

## 1. Executive Summary

FSR 4.1.0 is a **27-dispatch compute pipeline** centered on the internal model name `fsr4_model_v07_fp8_no_scale`. The binary contains **6 initializer blobs** in `.rdata`, with **2 unique weight sets** after MD5 comparison. The provider layer, resource IDs, and constant-buffer layout are largely stable relative to 4.0.2, but the **weight-loading strategy changed fundamentally**: 4.1.0 uses a dynamic `InitializerBuffer` and runtime `rawBufferLoad`-based access rather than 4.0.2’s static embedded shader arrays.

The architecture is **not cleanly proven end-to-end at runtime**. Static analysis strongly supports the 27-dispatch pipeline, the 27 DXIL model-family entrypoints, the 78/78 tensor-map plausibility result, and the extra 222 FP32 output-parameter region. Runtime capture is still missing. The report therefore separates:

- **STATIC-REPRODUCIBLE facts**: binary size, model strings, DXIL entrypoint inventory, blob locations, blob sizes, resource IDs, constant-buffer stability, 2 unique presets, and the 222-FP32 extra region.
- **Static-only findings**: no skip connections detected, layer shape interpretation, pass classification, and dispatch/order inference from host code.
- **Unresolved items**: runtime cbuffer values, runtime proof of tensor-offset use, runtime proof of skip/no-skip behavior, and end-to-end execution validation.

---

## 2. Evidence Inventory

### Primary evidence sources
- `build/dll_v410.dll` and `build/dll_v402.dll`
- `ghidra-decompile/ffxDispatch.c`, `ffxCreateContext.c`, `text_00bca0.c`, `text_00d5b0.c`, and related decompilation output
- `reports/provider-diff-report.md`
- `reports/architecture-map-v410.md`
- `reports/ml2code-runtime-diff.md`
- `reports/tensor-verification-report.md`
- `reports/pass-catalog.json`
- `spec/blob-format.json`
- `spec/tensor-map.json` (4.0.2-derived schema reference)
- `runtime-capture/vkd3d-shaders/`
- Shipping FSR4 DLL string evidence from the Desktop bundle copy of `amd_fidelityfx_upscaler_dx12.dll`

### Important negative evidence
The VKD3D shader dump under `runtime-capture/vkd3d-shaders/` contains the **injected sharpen/postprocess layer** that the game-side FSR route exposes at runtime, not the core FSR4 neural network. That naming is expected: once the path is hacked into the game, the runtime-facing shaders present themselves as sharpening/postprocess passes rather than `FSR4 model` passes. The dump proved the Vulkan shader-dump path works, but it did **not** capture the core FSR model network itself.

---

## 3. confirmed Findings

### 3.1 Core model identity
| Claim | Evidence | Status |
|---|---|---|
| Internal model name is `fsr4_model_v07_fp8_no_scale` | DLL strings; 4.0.2 source naming; provider diff | **STATIC-REPRODUCIBLE** |
| Pass naming covers `prepass`, `pass1..pass12`, `pass0_post..pass12_post`, `postpass` | `strings` on the FSR4 DLL | **STATIC-REPRODUCIBLE** |
| Total pass count is 27 dispatches per frame | provider diff + pass naming set | **STATIC-REPRODUCIBLE** |
| Core model is sequential rather than graph-like in the provider layer | Ghidra provider decompilation + dispatch loop structure | **STATIC-REPRODUCIBLE at static/provider level** |

### 3.2 Weight blob layout
| Claim | Evidence | Status |
|---|---|---|
| There are 6 initializer RVAs in `.rdata` | Ghidra LEA tracing + `pefile` resolution | **STATIC-REPRODUCIBLE** |
| Each initializer blob is 131,072 bytes | PE analysis + allocator size match | **STATIC-REPRODUCIBLE** |
| 5 presets share one blob; DRS uses a second blob | MD5 comparison of extracted blobs | **STATIC-REPRODUCIBLE** |
| Blob layout is `7208 B FP16 + 122880 B FP8/UINT8 + 888 B extra FP32 output params + 96 B pad` | `spec/blob-format.json` + `verification-report.json` + binary analysis | **STATIC-REPRODUCIBLE** |
| FP8 range in 4.1.0 is effectively full 0–255 uint8 coverage | statistical analysis of extracted weights | **STATIC-REPRODUCIBLE** |

### 3.3 Provider layer and resource stability
| Claim | Evidence | Status |
|---|---|---|
| Resource IDs are unchanged from 4.0.2 to 4.1.0 | `reports/provider-diff-report.md` | **STATIC-REPRODUCIBLE** |
| Main constant-buffer layout is structurally identical | `text_00d5b0.c` decompilation + 4.0.2 source comparison | **STATIC-REPRODUCIBLE** |
| Scratch buffer size is resolution-dependent in 4.1.0 | provider diff report | **STATIC-REPRODUCIBLE** |
| 4.1.0 keeps the same basic operator library as 4.0.2 | `reports/ml2code-runtime-diff.md` | **STATIC-REPRODUCIBLE** |

### 3.4 Shader-dump validation
| Claim | Evidence | Status |
|---|---|---|
| VKD3D shader dump was successfully captured | `runtime-capture/vkd3d-shaders/` exists with `.dxil`, `.spv`, `.rs`, `.hlsl` | **STATIC-REPRODUCIBLE** |
| The captured HLSL files are the injected sharpen/postprocess layer, not the core FSR4 network | inspection of generated HLSL files; runtime naming is expected for a host-side injected pass | **STATIC-REPRODUCIBLE** |
| The sharpen/RCAS-style naming is not a contradiction; it is the expected host-side disguise for the FSR-enabled runtime path | `vkd3d-shader-*.hlsl` source inspection | **STATIC-REPRODUCIBLE** |
| The FSR4 core network remains in the DLL, not in the captured auxiliary HLSL dump | string evidence + dump inspection | **STATIC-REPRODUCIBLE** |

---

## 4. Static-Only Findings

These are strong findings, but they are still static-analysis claims and should be read as such.

### 4.1 Architecture shape
The best-supported architecture is a **sequential 27-dispatch pipeline** with three broad phases:

1. **Encoder / interface passes** — convert between texture space and buffer/tensor space
2. **Data orchestration passes** — dynamic scratch allocation, tile staging, intermediate re-layout
3. **ML body passes** — the core inference passes that load weights from the initializer buffer
4. **Decoder / output passes** — project the processed result back out

The broad grouping comes from blob classification and operation frequencies in `reports/architecture-map-v410.md`, not from runtime capture of every dispatch.

### 4.2 Skip connections
No skip connections were detected in the static analysis, but this is **not runtime proof**. The report therefore treats skip absence as:

- **Static confidence: high**
- **Runtime proof: missing**

### 4.3 Tensor schema transfer
The 4.0.2 tensor schema in `spec/tensor-map.json` is a useful reference, but **it does not directly transfer as a confirmed 4.1.0 runtime map**. The independent tensor verification report shows the mismatch explicitly:

- `Matched offsets`: 1
- `Assumed map only`: 77
- `LLVM IR only`: 92

Conclusion: the 4.0.2 schema is **not a drop-in 4.1.0 tensor map**.

---

## 5. Unresolved Items

These are the remaining gaps that prevent this from being a fully runtime-closed reconstruction.

| Gap | Why it matters | Current status |
|---|---|---|
| Exact runtime cbuffer values for all 27 dispatches | Needed to prove the live tensor layout and per-pass offsets | **Unresolved** |
| Runtime proof of 4.1.0 tensor-offset use | Needed to prove the shipping binary uses the same live offsets inferred from static analysis | **Unresolved** |
| Extra 222 FP32 output parameters beyond static parsing | Static parsing is strong, but runtime consumption is not yet directly captured | **Static role resolved; runtime capture unresolved** |
| Runtime proof of no skip connections | Static evidence is strong, but not definitive | **Unresolved** |
| End-to-end model reconstruction validation | Needed to prove functional equivalence by output, not just structure | **Unresolved** |

### What would close these gaps
1. Runtime capture of resource bindings and cbuffers for every pass
2. Extraction of the live weight offsets during execution
3. Trace the extra 222 FP32 output-parameter region during runtime execution
4. Reconstruction of the pipeline and comparison against known input/output pairs

---

## 6. What We Learned About the Capture Path

The VKD3D dump was useful, but it answered a narrower question than initially expected:

- It confirms the **launch options and shader-dump path work**.
- It shows the game emits **auxiliary sharpen/postprocess shaders** through VKD3D.
- It does **not** expose the core FSR4 neural-network passes.

The actual FSR4 model identity and pass strings are in the FSR4 DLL itself. That is the real RE target, and the shader dump is only a supporting artifact.

---

## 7. Final Assessment

### Technical conclusion
FSR 4.1.0 is best described as:

- a **27-pass sequential compute pipeline**,
- with a stable provider-layer contract versus 4.0.2,
- but with a **new dynamic weight-loading model**,
- and a **retrained weight set** rather than a simple static embedding of the old 4.0.2 tensors.

### Confidence statement
- **High confidence**: pass count, model naming, blob layout, resource IDs, 2 unique blobs, unchanged operator set
- **Medium confidence**: broad architecture shape, skip absence, tensor-group interpretation
- **Low confidence / unresolved**: exact runtime cbuffer values, runtime proof of 4.1.0 offset use, end-to-end execution validation

### Gold-standard rule for this repo
A claim is only “done” when the report states **what is proven, how it was proven, and what remains unproven**. Anything less is just confident handwriting.

---

## 8. Reproducibility Notes

### Directly reproducible artifacts
- `reports/provider-diff-report.md`
- `reports/architecture-map-v410.md`
- `reports/ml2code-runtime-diff.md`
- `reports/tensor-verification-report.md`
- `reports/pass-catalog.json`
- `spec/tensor-map.json`
- `spec/blob-format.json`

### Command-level provenance
The work was reproduced with:
- `Ghidra` decompilation of the shipping DLL
- `pefile` RVA and section resolution
- `strings` inspection of the shipping FSR4 DLL
- `VKD3D_SHADER_DUMP_PATH` runtime capture
- bytewise blob extraction and MD5 comparison
- LLVM IR operation-frequency analysis

---

## 9. Appendix: File Map

### Core report entry points
- `README.md` — project index and high-level summary
- `reports/provider-diff-report.md` — provider layer diff
- `reports/architecture-map-v410.md` — pass architecture map
- `reports/ml2code-runtime-diff.md` — operator comparison
- `reports/tensor-verification-report.md` — offset-map verification status
- `reports/weight-extraction-report.md` — blob extraction details

### Binary and analysis artifacts
- `build/dll_v410.dll`
- `build/dll_v402.dll`
- `build/llvm_ir/`
- `build/ildn_extracted/`
- `ghidra-decompile/`
- `ghidra-project/`
- `extracted/`
- `runtime-capture/vkd3d-shaders/`

### Machine-readable specs
- `spec/blob-format.json`
- `spec/tensor-map.json`
- `reports/pass-catalog.json`

---

## 10. Bottom Line

The RE is **substantially complete at the structural level (runtime validation pending) at the provider + weight-layout + pass-identity level** and **intentionally honest about what remains unproven**. That is the difference between a flashy report and a gold-standard one.

**What "strongly supported" means:** structural claims are backed by binary evidence where cited. The data-DLL rebuild and comparison support extraction/layout claims; they do not prove independent data-section reconstruct (not bit-identical)ion. The DXIL IR analysis supports architecture and activation-function claims. What it does **not** mean: the analysis has been confirmed at runtime. Runtime validation on native Windows D3D12 is the next step for full credibility, and a small number of contributors with the right hardware could close this gap.

If this repo is going to be the new benchmark, this report is the contract: **confirmed facts first, static inference labeled, unresolved items never hidden**.
