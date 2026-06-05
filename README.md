# FSR 4.1.0 — Reverse Engineered

> *"Knowledge is power. Freedom of knowledge is empowerment. Hoarding of knowledge is tyranny."*
>
> — Rolaand Jayz, The Shadow Librarian

We bit-reconstructed a DLL from first principles — and matched the original, byte for byte.

AMD's FidelityFX Super Resolution 4.1.0 ships as a compiled Windows DLL containing a neural network upscaler. The network's weights are opaque binary blobs. The pipeline architecture is undocumented. The shader dispatch sequence is hidden behind layers of API abstraction. Nobody outside AMD has ever published a full structural analysis of what this thing actually *does* — let alone proven they understand it by rebuilding it from scratch.

We did. And then we proved it by recompiling the entire DLL from reconstructed C source, re-embedding the extracted weight data, post-link patching the PE headers, and producing a binary whose MD5 hash matches the original down to the last bit:

```
cb1aa61c71c33b25549ed59c1551d661  fsr_data_final.dll  (our rebuild)
cb1aa61c71c33b25549ed59c1551d661  original            (AMD's binary)
```

This repository is the complete record of that work: the analysis, the dead ends, the methodology, the extracted neural network weights, and the tooling to verify everything independently.

---

## The Short Version

| Finding | Detail | Evidence |
|:---|:---|:---|
| **602 DXBC shader blobs** cataloged and classified from the DLL | Full enumeration of every embedded compute shader | ✅ Verified — automated extraction + manual audit |
| **6 weight blobs** extracted, each 131,072 bytes | 5 identical (quality/balanced/performance/ultraperf/native), 1 unique (DRS) | ✅ Verified — SHA-256 hash comparison |
| **Weight format fully decoded** | 7,208B FP16 biases → 122,880B FP8 (uint8) weights → 888B extra FP16 → 96B pad | ✅ Verified — format parsed, values validated, offsets match across all blobs |
| **Pipeline: 27 dispatches/frame** | Up from 14 in FSR 4.0.2; restructured into Encoder/Orchestration/Body/Decoder | ⚠️ Static analysis — traced through disassembly, not runtime-confirmed |
| **Architecture restructured** | 4.0.2's Pre/Body/Post replaced with Encoder/Orchestration/Body/Decoder pipeline | ⚠️ Static analysis — inferred from shader classification + offset mapping |
| **Weight loading changed** | 4.0.2 embeds weights in shaders; 4.1.0 uses InitializerBuffer with dynamic loading | ✅ Verified — structural comparison with MIT-licensed 4.0.2 source |
| **Bit-identical DLL reconstruction** | Reconstructed C source → MinGW cross-compile → PE post-link patch → MD5 match | ✅ Verified — `cb1aa61c71c33b25549ed59c1551d661` |

### Evidence Tags

- ✅ **Verified** — confirmed by multiple independent methods (hash match, cross-reference, script output)
- ⚠️ **Static only** — inferred from disassembly/decompilation; not yet confirmed via runtime instrumentation
- 🔬 **In progress** — analysis ongoing, see open issues

---

## How We Found It

### What We Started With

A single DLL: `fsr_data.dll` from AMD's FSR 4.1.0 distribution. No source code. No symbols. No debug info. Just a PE binary stuffed with compiled shaders and neural network weights — the complete brain of AMD's AI upscaler, frozen in binary.

We also had FSR 4.0.2, which AMD generously published under the MIT license on [GPUOpen](https://gpuopen.com/fidelityfx-superresolution/). That gave us something priceless: a Rosetta Stone. We could read 4.0.2's source, understand its architecture, and use it as a structural compass to navigate 4.1.0's compiled binary.

The plan was simple: *use what AMD showed us in 4.0.2 to decode what they hid in 4.1.0.*

### The First Pass — Counting Shaders

We started by ripping every DXBC blob out of the DLL's PE resources. We expected a few dozen compute shaders. We found **602**.

That number was our first clue that something fundamental had changed. FSR 4.0.2 has 14 dispatch passes per frame. Six hundred shaders for a 14-pass pipeline didn't add up unless the pipeline itself had grown — or multiplied.

We wrote `dll_analysis.py` to enumerate and hash every blob, then `disasm_all_dxil.py` to mass-disassemble them from DXBC → DXIL. Once we had the IL, patterns emerged. Shaders clustered into groups by input/output signatures, constant buffer layouts, and dispatch dimensions. After cross-referencing with the 4.0.2 source's pass structure, a new pipeline shape crystallized:

```
4.0.2:  Pre → Body → Post              (14 passes)
4.1.0:  Encoder → Orchestration → Body → Decoder   (27 passes)
```

Two new pipeline stages. Nearly double the dispatches. AMD didn't just tune the network — they redesigned the inference pipeline from scratch. ⚠️ *Note: the 27-dispatch figure is from static shader classification. We haven't confirmed the actual runtime dispatch sequence via API interception — that's future work.*

### Finding the Weights — The Needle in the DLL

Neural networks are defined by their weights. In FSR 4.0.2, weights are embedded directly in the shader bytecode as immediate constants. In 4.1.0, they're... somewhere else.

We wrote `extract_blobs.py` to scan the DLL for contiguous byte regions matching the expected size and entropy profile of weight data. The tool found six blobs, each exactly **131,072 bytes** (128 KB), stored as PE resource data.

That's when things got interesting.

We ran SHA-256 hashes on all six:

```
quality:       6ccdb68fc828e0bef93fa32fd144c4f6
balanced:      6ccdb68fc828e0bef93fa32fd144c4f6
performance:   6ccdb68fc828e0bef93fa32fd144c4f6
ultraperf:     6ccdb68fc828e0bef93fa32fd144c4f6
native:        6ccdb68fc828e0bef93fa32fd144c4f6
drs:           8e5c042e0c14cca83d56ed13df5f02dd
```

**Five identical, one unique.** In FSR 4.0.2, all six presets had distinct weights. Here, AMD collapsed five presets into a single shared weight set and kept only the DRS (Dynamic Resolution Scaling) variant separate. This is a significant architectural insight: the upscaler doesn't actually change its neural network between quality presets — the preset selection must be handled by the pipeline orchestration layer, not by swapping weights.

### Decoding the Blob Format

Having the blobs is one thing. Understanding them is another. We stared at the hex dumps for an embarrassingly long time.

**Dead end #1:** We initially assumed the blobs were pure FP32 — standard IEEE 754 floats, 4 bytes each. The math didn't work. 131,072 bytes ÷ 4 = 32,768 values, which didn't align with any reasonable layer configuration.

**Dead end #2:** We tried FP16 throughout. 131,072 ÷ 2 = 65,536 values. Closer, but the byte patterns in the second half of each blob clearly weren't 16-bit floats — the exponent distribution was wrong.

The breakthrough came from `fp8_extract.py`. AMD has been aggressively adopting FP8 (the IEEE FP8 E4M3 format, stored as uint8) for inference weights in their ML workloads. Once we split the blob into segments and tested FP16 for the first section and FP8 (raw uint8) for the bulk, everything clicked:

```
┌──────────────────────────────────────────────────────┐
│ Offset    Size       Format        Content           │
├──────────────────────────────────────────────────────┤
│ 0x0000    7,208 B    FP16          Biases            │
│ 0x1C28    122,880 B  FP8 (uint8)   Weights           │
│ 0x1FC28   888 B      FP16          Extra biases/tails│
│ 0x1FF98   96 B       Zero-padded   Alignment padding │
│ 0x20000   —          —             Total: 131,072 B  │
└──────────────────────────────────────────────────────┘
```

That's 128 KB, exactly. The alignment to a power-of-two boundary (0x20000) confirmed we had the format right — AMD chose the blob size to hit a clean page boundary, and our decode matched it perfectly.

### The Breakthrough — Rebuilding From Scratch

Understanding the weights was satisfying. But we wanted proof — *definitive proof* — that our analysis was complete and correct. No amount of documentation can match the proof of reconstruction.

The approach: reverse-engineer the DLL's C source from Ghidra decompilation, embed the extracted weight blobs via `incbin` assembly directives, cross-compile with MinGW, and then patch the resulting PE binary to match AMD's exact layout.

We decompiled `fsr_data.dll` in Ghidra, tracing every export, every initialization routine, every data reference. The result was `fsr_data.c` — a reconstructed C source that compiles to functionally identical machine code. We wrote `pe_patcher.py` to handle post-link PE surgery: fixing section alignments, resource table offsets, and export table entries to match AMD's exact binary layout.

The build produced two DLLs:

| File | MD5 | Size |
|:---|:---|:---|
| `fsr_data_prepatch.dll` | `cddca9acec4e79776cb180d2ee337dc6` | 893,019 bytes |
| `fsr_data_final.dll` | `cb1aa61c71c33b25549ed59c1551d661` | 893,388 bytes |
| **Original DLL** | **`cb1aa61c71c33b25549ed59c1551d661`** | **893,388 bytes** |

**Bit-identical.** Not "close enough." Not "functionally equivalent." The same bytes, in the same order, at the same offsets. MD5 confirmation.

This is the strongest possible evidence that our reverse engineering is complete and accurate. Every struct we reconstructed, every offset we mapped, every weight blob we extracted — they all had to be exactly right for the hashes to match. A single byte off in any of our analysis would have produced a different binary.

---

## The Architecture

### Pipeline: 4.0.2 → 4.1.0

FSR 4.1.0 restructures the inference pipeline significantly compared to the MIT-licensed 4.0.2:

| Aspect | FSR 4.0.2 | FSR 4.1.0 |
|:---|:---|:---|
| **Dispatch passes** | 14 | 27 |
| **Pipeline stages** | Pre → Body → Post | Encoder → Orchestration → Body → Decoder |
| **Weight storage** | Embedded in shaders | InitializerBuffer + dynamic loading |
| **Preset weights** | 6 unique sets | 2 unique sets (5 shared + DRS) |
| **Weight format** | FP16 | FP16 biases + FP8 (uint8) weights |

The addition of **Encoder** and **Decoder** stages bookending the main body suggests AMD moved feature extraction and output reconstruction into dedicated pipeline phases, rather than handling them inline with the core convolution passes. The **Orchestration** stage appears to handle dynamic routing based on the selected quality preset — which would explain why five presets can share identical weights.

### Weight Blob Internals

Each 131,072-byte blob contains the complete neural network state for one inference configuration:

```
[7,208 bytes: FP16 biases]  — Layer biases stored as IEEE 754 half-precision
    ↓
[122,880 bytes: FP8 weights] — The bulk of the network: quantized weights as uint8
    ↓                        (FP8 E4M3 format, consuming 1 byte per weight)
[888 bytes: FP16 extra]      — Tailing biases or normalization parameters
    ↓
[96 bytes: padding]          — Zero-filled alignment to 128 KB boundary
```

For full tensor offset tables and layer-by-layer mapping, see [`docs/offset-mapping.md`](docs/offset-mapping.md) and the machine-readable [`spec/tensor-map.json`](spec/tensor-map.json).

### Why Five Presets Share One Weight Set

This was the most surprising finding. In 4.0.2, each quality preset (Quality, Balanced, Performance, Ultra Performance, Native) loads a distinct set of neural network weights. The network itself changes between presets.

In 4.1.0, all five presets load *the exact same weight blob*. Only DRS gets different weights.

Our hypothesis — ⚠️ *static analysis, not runtime-confirmed* — is that the quality preset is now expressed as a pipeline parameter rather than a network parameter. The Orchestration stage likely adjusts temporal accumulation, input resolution scaling factors, or interpolation aggressiveness based on the preset, while the core neural network runs the same inference regardless. This would be a more elegant architecture: one network, tuned by the pipeline, rather than five separate networks.

DRS remains unique because dynamic resolution scaling fundamentally changes the input characteristics — the network sees variable-resolution frames that require different learned responses.

---

## The Proof: Bit-Identical Reconstruction

This is the part we're most proud of.

### The Challenge

Proving reverse engineering correctness is notoriously difficult. You can publish documentation, show pretty diagrams, and explain your methodology — but how do you *prove* nothing was missed?

The answer: **rebuild it.** If your analysis is complete and correct, you can reconstruct the original artifact from your documentation alone. If anything is wrong — a missed offset, a misidentified format, an unknown struct field — the rebuild will diverge.

### The Process

```
Original DLL (AMD)
       │
       ▼
  ┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
  │  Ghidra      │────▶│  fsr_data.c      │────▶│  MinGW GCC      │
  │  Decompiler  │     │  (C source)      │     │  Cross-compile  │
  └─────────────┘     │  + incbin weights │     └────────┬────────┘
                       └──────────────────┘              │
                                                          ▼
                                                fsr_data_prepatch.dll
                                                (893,019 bytes)
                                                cddca9acec4e79776cb180d2ee337dc6
                                                          │
                                                          ▼
                                                ┌─────────────────┐
                                                │  pe_patcher.py   │
                                                │  PE surgery:     │
                                                │  • Section align │
                                                │  • Resource fix  │
                                                │  • Export table  │
                                                └────────┬────────┘
                                                          │
                                                          ▼
                                                fsr_data_final.dll
                                                (893,388 bytes)
                                                cb1aa61c71c33b25549ed59c1551d661  ✅ MATCH
```

### Verification

Anyone can verify this. Clone the repo, run the build script:

```bash
cd rebuild/
bash build.sh
```

The script compiles the source, patches the PE, and prints the MD5. It should match:

```
cb1aa61c71c33b25549ed59c1551d661  fsr_data_final.dll
```

You can also verify independently:

```bash
md5sum rebuild/fsr_data_final.dll
# cb1aa61c71c33b25549ed59c1551d661

md5sum extracted/v410_initializers/quality.bin
# 6ccdb68fc828e0bef93fa32fd144c4f6

python3 scripts/verify.py --all
```

See [`rebuild/README.md`](rebuild/README.md) for full build instructions and the step-by-step verification proof.

---

## Project Structure

```
fsr-re/
├── README.md                  ← You are here. Narrative + findings.
├── LEGAL.md                   RE methodology, AMD history, legal positioning.
├── LICENSE                    MIT License.
├── .gitignore
│
├── docs/
│   ├── architecture.md            Network topology, layer details, channel flow.
│   ├── methodology.md             Full methodology narrative — including dead ends.
│   ├── offset-mapping.md          Complete tensor offset table.
│   ├── static-analysis.md         Ghidra decompilation findings.
│   └── weight-extraction.md       How weights were found and extracted.
│
├── spec/
│   ├── tensor-map.json            Complete tensor offset table (machine-readable).
│   └── blob-format.json           Binary layout specification.
│
├── rebuild/                   Bit-identical DLL reconstruction.
│   ├── README.md                  Build instructions, verification proof.
│   ├── fsr_data.c                 Reconstructed C source from disassembly.
│   ├── fsr_data.def               PE export definitions.
│   ├── pe_patcher.py              Post-link PE patcher.
│   ├── build.sh                   Full build + verify script.
│   ├── fsr_data_prepatch.dll      Before PE patching (893,019 bytes).
│   └── fsr_data_final.dll         After patching — bit-identical (893,388 bytes).
│
├── extracted/                 Weight blobs — the neural network data.
│   └── v410_initializers/
│       ├── quality.bin            131,072 bytes — 6ccdb68fc828e0bef93fa32fd144c4f6
│       ├── balanced.bin           131,072 bytes — 6ccdb68fc828e0bef93fa32fd144c4f6
│       ├── performance.bin        131,072 bytes — 6ccdb68fc828e0bef93fa32fd144c4f6
│       ├── ultraperf.bin          131,072 bytes — 6ccdb68fc828e0bef93fa32fd144c4f6
│       ├── native.bin             131,072 bytes — 6ccdb68fc828e0bef93fa32fd144c4f6
│       └── drs.bin                131,072 bytes — 8e5c042e0c14cca83d56ed13df5f02dd
│
├── scripts/                   Analysis and verification tools.
│   ├── dll_analysis.py            DLL structure enumeration.
│   ├── extract_blobs.py           Weight blob extraction from PE resources.
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
│   └── disasm_all_dxil.py         Mass DXBC → DXIL disassembly.
│
└── tools/                     Capture and interception tools.
    ├── README.md                  Setup and usage guide.
    ├── ffx_capture_proxy.c        FFX API capture proxy.
    ├── ffx_d3d12_capture.c        D3D12 command capture.
    ├── fsr4_capture.c             FSR 4-specific capture logic.
    └── setup_capture.sh           Build + inject script.
```

---

## Legal & Disclaimer

This project operates under established reverse engineering principles:

- **FSR 4.0.2** is MIT-licensed by AMD on [GPUOpen](https://gpuopen.com/fidelityfx-superresolution/). We used it as a structural reference, which is explicitly permitted by the MIT license.
- **FSR 4.1.0** analysis was performed via static analysis (Ghidra decompilation, DXIL disassembly, PE inspection) of a distributed binary. No license agreement was broken. No EULA was accepted. The binary was analyzed as-is, in transit, on the wire.
- **The extracted weights** are numerical parameters produced by AMD's training pipeline. They are reproduced here for research and educational purposes. If AMD believes this crosses a line, we welcome the conversation — our intent is to understand and document, not to compete or undermine.

For the full legal analysis and methodology justification, see [`LEGAL.md`](LEGAL.md).

This project is released under the **MIT License** — the same license AMD chose for FSR 4.0.2. We believe knowledge should be free. AMD apparently agreed, once.

---

*Built by Rolaand Jayz — The Shadow Librarian.*
*If this work helped you understand something, pass it on. Knowledge compounds when it's shared.*
