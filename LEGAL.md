# Legal Notice

This is not legal advice. No attorney has reviewed this document. The authors are engineers, not lawyers. Read this document in full before making any decisions. If you need legal advice, consult a qualified attorney licensed in your jurisdiction.

---

## License

All original work in this repository is released under the MIT License:

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

This license applies only to original work. AMD's proprietary data — extracted neural network weights, original binary structures, and the functional design of FSR 4.1.0 — remains the intellectual property of Advanced Micro Devices, Inc.

---

## Per-Directory Licensing

| Directory | Contents | License | Redistributable? |
|-----------|----------|---------|-------------------|
| `scripts/` | Analysis and extraction scripts (original work) | MIT | Yes |
| `docs/` | Documentation and analysis (original work) | MIT | Yes |
| `tools/` | Build tooling and patcher (original work) | MIT | Yes |
| `rebuild/` | Rebuild source and comparison tooling | MIT for source/tooling | No for compiled DLLs |
| `extracted/` | Extracted weight blobs and initializers | AMD proprietary (LicenseRef-AMD-Derived-Research-Data) | No |
| `spec/` | Architecture specifications (original, derived from MIT-licensed 4.0.2 source) | MIT | Yes |
| `reports/` | Validation and verification reports (original work) | MIT | Yes |
| `capture-tools/` | Capture utilities (original work) | MIT | Yes |
| `runtime-capture/` | Runtime traces | Mixed — logs are user data; tooling is MIT | Logs: user discretion |

**Not included in this repository:** the original AMD FSR 4.1.0 DLL, Ghidra decompilation projects, and DXIL disassembly files. These are AMD proprietary and are not redistributed here.

---

## AMD Open-Source History

AMD has released major Linux GPU driver components and GPUOpen materials under open-source licenses. The FidelityFX SDK, published through GPUOpen, includes FSR versions 1.0 through 4.0.2 under the MIT license. In August 2025, AMD briefly published FSR 4 source code on GPUOpen under MIT before confirming it was a mistake and removing the files. This project does not rely on that publication as a primary legal basis. I am not aware of a public AMD DMCA campaign against GPU reverse-engineering projects, but absence of public enforcement is not legal permission.

---

## Legal Argument

We believe the following legal arguments apply to this repository, stated as arguments we believe apply rather than as settled fact:

- **DMCA 17 U.S.C. § 1201(f)** provides an exemption for reverse engineering for the purpose of achieving interoperability. We believe our handling of the minimum data necessary for interoperability — including neural network weights — falls within this exemption. This is a legal argument, not a proven fact in this specific context.
- **Sega v. Accolade**, 977 F.2d 1510 (9th Cir. 1992), and **Sony v. Connectix**, 203 F.3d 596 (9th Cir. 2000), established fair-use reasoning for disassembly aimed at interoperability. We believe these cases support our methodology.
- **EU Directive 2009/24/EC, Article 5** permits decompilation for interoperability under certain conditions, which may apply to users in EU member states.

These arguments are untested in this specific context. Courts may reach different conclusions based on jurisdiction, facts, and applicable contracts.

---

## Risk Matrix

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Copyright infringement** — Extracted weights and rebuilt DLLs are arguably derivative works of AMD's proprietary binary. | High | Do not redistribute. Use local extraction only. Assert interoperability and fair-use arguments; acknowledge they are untested. |
| **Trade secret misappropriation** — Neural network weights and internal architecture may qualify as AMD trade secrets. | Medium | Weights are embedded in a publicly distributed binary; architecture is substantially derivable from MIT-licensed 4.0.2 source. Do not redistribute. |
| **EULA violation** — AMD driver EULA may prohibit reverse engineering. Enforceability varies by jurisdiction. | Low–Medium | Review the EULA terms applicable to your acquisition path. Statutory interoperability rights may override contractual restrictions in some jurisdictions. |
| **DMCA § 1201(a) anti-circumvention** — If a technological protection measure protects the DLL, extraction may implicate anti-circumvention rules. | Medium | We rely on the § 1201(f) interoperability exemption, which is a legal argument we believe applies. No TPM is known to protect the DLL beyond standard PE packaging. |
| **Jurisdictional variability** — Legal status of reverse engineering differs across jurisdictions. | Medium | Users must understand their own local laws. EU Directive 2009/24/EC may apply differently than U.S. law. |
| **No clean-room process** — The same individuals who examined the binary wrote the reconstruction code. | Medium | We acknowledge this weakens independent-creation arguments. No copied source code is included; reconstruction is in C, not AMD's C++. |
| **No legal review** — No attorney has reviewed this repository. | High | Treat all legal arguments as engineering analysis, not legal opinion. Consult counsel before relying on them. |

A more detailed threat model for redistributed binary data is in [RISK.md](RISK.md).

---

## What This Repository Contains

The repository includes: original MIT-licensed analysis scripts, documentation, reconstructed C source, a PE analysis tool, architecture specifications derived from MIT-licensed FSR 4.0.2 source, extracted neural network weight blobs (~6 x 131 KB, AMD proprietary), and rebuild/comparison tooling that emits per-region comparison reports. The extracted weight blobs are included for research disclosure; redistribution rights are not granted by AMD and remain legally exposed.

The original AMD FSR 4.1.0 DLL is not included. Ghidra decompilation projects and DXIL disassembly files are not included.

---

## Methodology

1. Parsed MIT-licensed FSR 4.0.2 source as an architectural reference.
2. Performed static binary analysis of the FSR 4.1.0 DLL using Ghidra.
3. Mapped PE structure to locate embedded neural network weight sections.
4. Extracted six weight blobs from the binary's data sections.
5. Wrote C code implementing the observed API/data structure, embedding extracted weights in the expected layout. The rebuild tooling emits per-region comparison reports and does not copy original bytes.

We did not use clean-room techniques. The same individuals who analyzed the binary wrote the reconstruction code. No attorney has reviewed this methodology.

---

## Contributing

By contributing, you certify that your contribution is your own original work, derived from publicly available MIT-licensed source (with origin documented), or factual analysis that does not reproduce proprietary source code. You must not contribute decompiled or disassembled AMD source, copies of AMD binaries, or material obtained under NDA. If unsure, open an issue before submitting a pull request.

---

This document is a transparent disclosure of what this repository contains and what risks remain. If you need legal advice, consult a qualified attorney.
