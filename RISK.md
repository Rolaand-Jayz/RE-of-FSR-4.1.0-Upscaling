# Risk Assessment

This document is a threat model for redistributed binary data in this repository. It is not legal advice. No attorney has reviewed this document. Consult a qualified attorney before any redistribution or commercial use.

Severity and likelihood are engineering estimates based on public information. They are not legal determinations.

---

## Risk Matrix

| Risk | Category | Severity | Likelihood | Mitigation |
|------|----------|----------|------------|------------|
| Redistribution of extracted neural network weights (`.bin` files under `extracted/`) constitutes distribution of AMD proprietary data and potential derivative works. | Copyright | High | High if redistributed; N/A if local-only | Do not redistribute. Use local extraction only. Treat all `.bin` files as non-redistributable research data. |
| AMD files a DMCA § 1201 circumvention claim asserting that extraction bypassed a technological protection measure. | DMCA 1201 | Medium | Low–Medium | We rely on the § 1201(f) interoperability exemption as a legal argument. No TPM is known to protect the DLL beyond standard PE packaging. Do not redistribute extracted data. |
| AMD asserts EULA violation for reverse engineering the driver-packaged DLL. | EULA | Low–Medium | Depends on acquisition path | Review the EULA applicable to your acquisition path. Statutory interoperability rights may override contractual anti-RE clauses in some jurisdictions. Do not redistribute. |
| AMD asserts trade secret misappropriation over extracted weights and internal architecture. | Trade Secret | Medium | Low–Medium | Weights are embedded in a publicly distributed binary and require no breach of confidentiality to extract. Architecture is substantially derivable from MIT-licensed 4.0.2 source. Do not redistribute. |
| Using the rebuilt DLL as a production replacement for AMD's official FSR 4.1.0 runtime. | Security/Operational | High | Medium | Do not use the rebuilt DLL in production. It is a research artifact, not a validated production replacement. Per-region comparison reports do not prove functional equivalence of the full runtime. |
| Capture and extraction tooling produces unstable, incomplete, or incorrect output across driver versions or environments. | Security/Operational | High | Medium | Treat tooling output as research-grade. Validate results against independent methods. Do not rely on output for production decisions. |
| Jurisdictional law differs from U.S. assumptions, restricting or permitting activities differently than documented here. | Jurisdiction | Medium | Medium | Users must understand their own local laws. EU Directive 2009/24/EC may apply differently than U.S. law. Consult local counsel. |
| Same individuals who analyzed the binary wrote the reconstruction (no clean-room process), weakening independent-creation arguments. | Copyright | Medium | Already realized | Acknowledge in all disclosures. Reconstruction is in C, not AMD's C++. No copied source included. Consult counsel before redistribution. |
| Extracted data is republished by a downstream fork without the proprietary-data notice, creating attribution and liability exposure for the original project. | Copyright / DMCA 1201 | Medium | Medium | Keep `extracted/NOTICE.md` and `extracted/SPDX_LICENSES.md` attached to all copies. Include license headers in tooling. Document redistribution restrictions prominently. |

---

## Usage Guidance

- Local-only extraction and analysis carries lower risk than redistribution.
- Redistribution of any file under `extracted/` carries the highest risk in this matrix.
- The rebuilt DLL is a research artifact. Do not deploy it as a production replacement.
- Tooling output is research-grade. Validate independently before relying on it.

For the full legal context, see [LEGAL.md](LEGAL.md). If you need legal advice, consult a qualified attorney.
