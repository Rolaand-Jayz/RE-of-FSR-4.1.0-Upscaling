# Legal Notice

> **This is not legal advice.** Nothing in this document constitutes legal advice, creates an attorney-client relationship, or should be relied upon as a legal opinion. The authors are software engineers and reverse engineers, not lawyers. If you need legal advice, consult a qualified attorney licensed in your jurisdiction. This document is a transparent disclosure of what this repository contains, why it exists, what legal arguments support it, and what risks remain. Read it in full before making any decisions.

---

## License

All **original work** in this repository — analysis scripts, documentation, the C source reconstructed from disassembly, the PE patcher, and all other authored content — is released under the **MIT License**:

```
MIT License

Copyright (c) 2025 Rolaand Jayz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

This license applies **only** to our original work. AMD's proprietary data — the neural network weights, the original binary structures, and the functional design of FSR 4.1.0 — remain the intellectual property of Advanced Micro Devices, Inc. We do not claim ownership over AMD's data. We assert that our handling of it is justified under established legal doctrines for interoperability, which we document below.

---

## AMD's DNA Is Reverse Engineering

AMD exists as we know it today because of reverse engineering. This isn't hyperbole — it's the company's origin story.

### The Am386: Five Years of Reverse Engineering (1988–1993)

In the late 1980s, Intel refused to share technical specifications for the 386 processor. AMD's survival depended on producing x86-compatible chips. So they did what any competitor in a free market would do: they reverse-engineered it. Five years of painstaking work produced the **Am386**, a clean-room implementation of Intel's architecture that AMD could sell independently.

This was not a grey-area activity. It was the foundation of AMD's entire processor business.

### AMD v. Intel: The Fight That Resolved It (1995)

The resulting legal battle culminated in **arbitration in 1995**, which produced a cross-license agreement between AMD and Intel. AMD's x86 business — the processors in millions of PCs today — was built on the foundation of that reverse engineering effort. The arbitration did not punish AMD for RE. It created the licensing framework that legitimized it.

### Intel Pays AMD $1.25 Billion (2009)

The story didn't end in 1995. AMD filed antitrust claims against Intel, alleging that Intel had abused its monopoly position to suppress competition — including AMD's reverse-engineered x86 products. In **November 2009, Intel paid AMD $1.25 billion** to settle these claims. The company that reverse-engineered its way into the market ultimately forced the dominant player to pay over a billion dollars.

**The point:** AMD understands reverse engineering better than almost any company in the semiconductor industry. They've lived it. They've fought for it. They've won with it. They know that interoperability through reverse engineering is a legitimate and often necessary activity in a competitive technology market.

---

## AMD's Public Commitment to Open Source

AMD's posture toward open source is not merely permissive — it is one of the most aggressive open-source strategies in the GPU industry.

### amdgpu: Full Open-Source GPU Driver Stack

AMD **open-sourced their entire GPU driver stack**. They replaced the proprietary Catalyst (fglrx) driver with the **amdgpu** open-source kernel driver, paired with MIT-licensed display code in Mesa. This wasn't a partial release or a neutered reference implementation — it was the production driver. AMD chose openness as a competitive strategy against NVIDIA's proprietary driver model.

### GPUOpen and the FidelityFX SDK

AMD publishes the **FidelityFX SDK** through [GPUOpen](https://gpuopen.com/), their open-source initiative for game development technology. Every version of FSR from **1.0 through 4.0.2** has been released under the **MIT license** — the most permissive open-source license in common use. This includes:

- Full shader source code (HLSL)
- Integration samples
- Effect framework code
- Build systems and tooling

AMD has published thousands of lines of FSR source code under a license that explicitly permits any use, including commercial use, modification, and redistribution.

### The FSR 4 Accidental Release (August 2025)

In **August 2025**, AMD accidentally published the **FSR 4 source code** on GPUOpen under the **MIT license**. AMD subsequently confirmed this was a mistake and removed the files. However, under copyright law, the MIT license is often argued to be irrevocable once granted, subject to jurisdiction and facts — those who obtained the source during the window it was publicly available may retain their license rights. We do not rely on this argument as a primary justification for this repository, but it is a factual data point: AMD's own open-source infrastructure published FSR 4 source under MIT, even if briefly.

### Zero DMCA Takedowns

AMD has **never** issued a DMCA takedown notice targeting reverse engineering of their products. Not once. In an industry where Nintendo, Sony, and others routinely use DMCA takedowns against RE projects, AMD's zero-takedown track record is notable. This is consistent with a company that was itself built on reverse engineering and has chosen open source as a competitive strategy.

---

## What This Repository Contains

We are explicit about what is and is not included, and the licensing status of each component:

| Category | License / Status | Included? |
|----------|-----------------|-----------|
| Original analysis and documentation | MIT (Copyright Rolaand Jayz) | ✅ Yes |
| Original Python scripts | MIT (Copyright Rolaand Jayz) | ✅ Yes |
| Original C source (reconstructed from disassembly) | MIT (Copyright Rolaand Jayz) | ✅ Yes |
| PE patcher script | MIT (Copyright Rolaand Jayz) | ✅ Yes |
| Architecture specs (JSON) | Original work derived from MIT-licensed 4.0.2 source | ✅ Yes |
| FSR 4.0.2 HLSL reference data | Already MIT licensed by AMD (GPUOpen) | ✅ Yes |
| **Extracted weight blobs** (6 × ~131KB `.bin` files) | AMD proprietary data, extracted for interoperability research | ✅ Yes |
| **Rebuilt DLLs / comparison artifacts** | Reconstructed from RE work + extracted data; not licensed as AMD data | ✅ Yes |
| Original FSR 4.1.0 DLL (AMD binary) | AMD proprietary | ❌ **Not included** |
| Ghidra project / decompiled C++ | Contains proprietary decompilation of AMD code | ❌ **Not included** |
| DXIL disassembly (`.ll` files) | Derived from proprietary shaders | ❌ **Not included** |

### What changed from previous versions

Previous releases of this RE project excluded the weight blobs and rebuilt DLLs. We now include them. The rationale for this decision is documented in [Why We Include Extracted Data and Rebuilt DLLs](#why-we-include-extracted-data-and-rebuilt-dlls) below.

---

## What We Did

This section describes our methodology with specificity. We believe transparency about process is both intellectually honest and legally relevant.

1. **Parsed MIT-licensed source.** FSR 4.0.2 source is published by AMD under the MIT license on GPUOpen. We used this as the architectural reference — understanding tensor dimensions, layer structure, activation functions, and the general neural network topology. This is unambiguously permitted by AMD's own license.

2. **Static binary analysis via Ghidra.** We performed static analysis (disassembly and decompilation) of the FSR 4.1.0 DLL using Ghidra. We examined PE structure, export tables, section layouts, and internal code flow. This is reverse engineering for the purpose of understanding interoperability — specifically, how the neural network inference engine is structured and how weight data is embedded in the binary.

3. **PE structure analysis.** We mapped the Portable Executable format of the DLL, identifying resource sections, data segments, and the specific locations where neural network weights are stored. This informed our understanding of how to extract and reconstruct the weight blobs.

4. **Weight blob extraction.** We identified and extracted 6 weight blobs (~131KB each) from the binary. These are the neural network parameters — the learned data that defines FSR 4.1.0's upscaling behavior. They are embedded in the DLL's data sections and are necessary for any functional reconstruction.

5. **DLL reconstruction research.** Using the architectural understanding from steps 1–4, we wrote C code that implements the observed API/data structure and embeds the extracted weight data in the expected layout. Earlier documentation overstated the historical post-link patcher's result: copying original sections/headers/overlay before comparing hashes is not independent proof of complete binary reconstruction. The current rebuild tooling emits per-region comparison reports without copying original bytes.

---

## What We Did NOT Do

Honesty requires stating the negative explicitly:

- **We did not copy AMD's C++ implementation code.** The original FSR 4.1.0 implementation is compiled C++ that we examined through disassembly. Our C source is reconstructed from our understanding of the disassembly — it is our original expression of the functional behavior, not a copy of AMD's source.

- **We do not redistribute AMD's original DLL.** The original FSR 4.1.0 binary is not included in this repository. We provide our own reconstructed version and the tools to verify it.

- **We do not claim ownership over AMD's data.** The neural network weights are AMD's proprietary data, produced by their training process. We extracted them for interoperability research. We do not pretend they are ours.

- **We did not use clean-room techniques.** We are transparent about this. The same individuals who examined the binary through Ghidra wrote the reconstruction code. A clean-room process (where one team analyzes and a separate, isolated team implements) provides stronger legal insulation. We did not follow that protocol. This is a known risk, documented below.

- **We did not obtain legal review.** No attorney has reviewed this repository, this document, or our methodology. We are engineers making our best good-faith assessment.

---

## Why We Include Extracted Data and Rebuilt DLLs

Previous releases of this project excluded the weight blobs and rebuilt DLLs. We have chosen to include them in this release. Here is why, stated plainly:

### The weight blobs are the proof

Without the extracted weight data, the analysis in this repository is unverifiable. Claims about tensor dimensions, layer count, and network architecture become assertions that readers must take on faith. Publishing the weights allows anyone to:

- **Verify** our architectural analysis independently
- **Reproduce** our DLL reconstruction from scratch
- **Develop** alternative implementations (e.g., Vulkan compute shaders, ONNX exporters, Linux-native inference)
- **Study** the relationship between architecture and upscaling quality

The weights are small (6 × ~131KB ≈ 786KB total) and constitute a factual record of the neural network's learned parameters. They are the data that makes the analysis real.

### The rebuilt DLLs are the verification

The rebuilt DLLs and comparison reports demonstrate a narrower claim: the extracted data layout and exported data-access API can be studied and checked. They do not, by themselves, prove complete binary reconstruction or functional equivalence of the full FSR runtime. Per-section hashes, differential API tests, and runtime traces are required for stronger claims.

### Interoperability requires the data

The practical purpose of this RE project is to enable **interoperability** — specifically, implementing FSR 4.1.0 on platforms AMD does not support (Vulkan, Linux, potentially older hardware). You cannot implement a neural network upscaler without the weights. Including them makes this repository functionally useful rather than merely academic.

### Legal basis

Section 1201(f) of the DMCA provides an exemption for reverse engineering for the purpose of achieving interoperability. *Sega v. Accolade* (9th Cir., 1992) established that disassembly of copyrighted software for interoperability is fair use. EU Directive 2009/24/EC explicitly permits reverse engineering for interoperability. We believe these doctrines support the inclusion of the minimum data necessary for interoperability — which, for a neural network, includes the weights.

---

## Known Legal Risks

We would rather be honest about risks than present a false sense of security. These are the legal vulnerabilities we are aware of:

### 1. EULA Restrictions

The FSR 4.1.0 DLL is distributed as part of AMD's driver package, which is governed by an End User License Agreement. Most EULAs prohibit reverse engineering, decompilation, and disassembly. If a court enforces the EULA's anti-RE provisions, this project could face legal challenge regardless of the copyright fair use arguments.

**Mitigating factor:** EULA anti-RE provisions have been challenged in court with mixed results. In some jurisdictions, statutory rights to reverse engineer for interoperability may override contractual restrictions. But this is not settled law.

### 2. Trade Secrets

The neural network weights and the internal architecture of FSR 4.1.0 may qualify as AMD trade secrets. Extraction and publication of trade secrets can be legally actionable even if copyright fair use applies.

**Mitigating factor:** FSR 4.1.0 is distributed publicly as part of AMD's driver package (though not in source form). Trade secret protection generally requires that the information not be readily ascertainable through lawful means. The weights are embedded in a publicly distributed binary; extracting them requires effort but no breach of physical security or confidentiality. Additionally, the architectural parameters are substantially derivable from the MIT-licensed FSR 4.0.2 source.

### 3. Derivative Works

The rebuilt DLLs and weight blobs are arguably derivative works of AMD's proprietary binary. Distribution of derivative works without authorization from the copyright holder is copyright infringement unless a defense (fair use, interoperability exemption, etc.) applies.

**Mitigating factor:** We assert that our handling falls within the interoperability exemption of DMCA § 1201(f) and the fair use doctrine established in *Sega v. Accolade*. The rebuilt DLL is our original expression of the functional behavior, and the weights are factual data necessary for interoperability. But the derivative works argument is real and untested in this specific context.

### 4. No Clean-Room Process

We did not use clean-room techniques. The same people who examined AMD's binary wrote the reconstruction. In a legal proceeding, this weakens the argument that our implementation is an independent creation rather than a copy. Clean-room RE has established legal precedent; non-clean-room RE is on less firm footing.

**Mitigating factor:** We reconstructed the binary from disassembly, not from source code. Our implementation is in C (not AMD's C++), follows our own structure, and includes no copied code. But we acknowledge this is not the gold-standard legal process.

### 5. No Attorney Review

No lawyer has reviewed this repository. All legal arguments in this document are our own analysis as engineers. They may be wrong in ways we cannot detect.

### 6. Jurisdictional Variability

The legal status of reverse engineering varies significantly by jurisdiction. What is permitted in the EU under Directive 2009/24/EC may be restricted elsewhere. Users of this repository should understand their own local laws.

---

## Precedent Comparison

Several high-profile reverse engineering projects in the GPU/driver space have operated publicly without legal action. We list them here for context, with an important caveat:

### Asahi Linux

The [Asahi Linux](https://asahilinux.org/) project reverse-engineered Apple's M1/M2 GPU to create an open-source Linux driver. The project involved extensive reverse engineering of Apple's proprietary GPU command stream, shader ISA, and firmware protocols. Apple has not taken legal action against the project.

### Nouveau

The [Nouveau](https://nouveau.freedesktop.org/) project reverse-engineered NVIDIA's proprietary GPU drivers to create an open-source driver for the Linux kernel. The project has operated openly since 2005, with NVIDIA's knowledge, without legal action. NVIDIA eventually began providing some documentation to the project.

### Panfrost

The [Panfrost](https://gitlab.freedesktop.org/mesa/mesa/-/tree/main/src/gallium/drivers/panfrost) project reverse-engineered ARM Mali GPUs to create an open-source Mesa driver. This involved RE of ARM's proprietary GPU command stream and shader ISA.

### Important Caveat

**Absence of legal action does not constitute legal approval.** The fact that Apple, NVIDIA, and ARM have not sued Asahi Linux, Nouveau, or Panfrost does not mean they approve of those projects, nor does it create legal precedent. It simply means no legal action has been taken. The same applies to AMD's zero-DMCA track record — it reflects AMD's choices to date, not a legal guarantee.

However, the pattern is meaningful: GPU reverse engineering projects have operated publicly for decades without successful legal challenge, suggesting that the legal risk, while real, is manageable in practice.

---

## Legal Framework Reference

The following legal authorities are relevant to this project:

| Authority | Jurisdiction | Relevance |
|-----------|-------------|-----------|
| **17 U.S.C. § 1201(f)** — Reverse Engineering Exemption | United States | Permits circumvention of technological measures and reverse engineering for interoperability |
| **Sega Enterprises Ltd. v. Accolade, Inc.**, 977 F.2d 1510 (9th Cir. 1992) | United States | Established that disassembly of copyrighted software for interoperability is fair use |
| **Sony Computer Entertainment, Inc. v. Connectix Corp.**, 203 F.3d 596 (9th Cir. 2000) | United States | RE of PlayStation BIOS for emulation was fair use; intermediate copying does not preclude fair use defense |
| **EU Directive 2009/24/EC, Article 5** | European Union | Explicitly permits decompilation for interoperability, provided certain conditions are met |
| **Lewis Galoob Toys, Inc. v. Nintendo of America, Inc.**, 964 F.2d 965 (9th Cir. 1992) | United States | Established that a product that does not alter the copyrighted work but interacts with it does not create a derivative work |

---

## Contributing

By contributing to this repository, you certify that:

1. **Your contribution is your own original work**, or
2. **Your contribution is derived from publicly available, MIT-licensed source code** (e.g., AMD's FSR 4.0.2 SDK on GPUOpen), with the origin clearly documented in your commit, or
3. **Your contribution is factual analysis** (e.g., documentation of observed behavior, architectural descriptions) that does not reproduce proprietary source code.

You must **not** contribute:
- Decompiled or disassembled source code from AMD's proprietary binaries (C++ output from Ghidra, IDA, or similar tools)
- Copies of AMD's original DLL or shader binaries
- Any material obtained under NDA or confidential disclosure

If you are unsure whether your contribution is appropriate, open an issue and ask before submitting a pull request.

---

## Summary

This repository exists because we believe that reverse engineering for interoperability is legitimate, that AMD's own history and public commitments support this belief, and that transparency about our process and risks is the right approach. We have been honest about what we did, what we did not do, what legal arguments support us, and what legal risks remain. The decision to use this repository is yours — made with full knowledge of the facts as we understand them.

**AMD built its x86 business on reverse engineering. The law recognized that right then. We believe it recognizes it now.**
