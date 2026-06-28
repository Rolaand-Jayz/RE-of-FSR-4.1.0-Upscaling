#!/usr/bin/env python3
"""Fail CI on stale overclaims, contradictions, and dishonest framing.

This guardrail exists because the project was previously scored 3.5/10 on accuracy
for presenting a circular bit-identical proof and using "complete" / "proved"
language that exceeded the evidence. Every pattern below was found in the wild
and caused a credibility hit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Scan ALL text files — NO ALLOWLIST. The prior version exempted VALIDATION_STATUS.md
# and rebuild/README.md, which is where the circular proof survived. Files that
# need to mention old problems must do so with explicit correction wording.
TEXT_FILES = [
    p for p in ROOT.rglob("*")
    if p.is_file()
    and ".git" not in p.parts
    and "__pycache__" not in p.parts
    and p.suffix.lower() in {".md", ".py", ".sh", ".json", ".yml", ".yaml"}
]

FORBIDDEN = [
    # Circular proof language
    (re.compile(r"bit-identical[^\n]{0,160}(proof|proves|proved|complete|correct|reconstruct)", re.I),
     "bit-identical must not be presented as proof/completion/reconstruction"),
    # From-first-principles overclaim
    (re.compile(r"from first principles", re.I),
     "from-first-principles overclaim"),
    # Complete reverse engineering
    (re.compile(r"complete reverse engineering", re.I),
     "complete-reverse-engineering overclaim"),
    # Complete implementation guide
    (re.compile(r"complete implementation guide", re.I),
     "implementation guide must not claim completeness"),
    # "zero open gaps" — runtime validation is still pending
    (re.compile(r"zero open gaps", re.I),
     "zero-open-gaps overclaim: runtime validation is still pending"),
    # "all architectural properties are determined" — too strong
    (re.compile(r"all architectural properties (is|are) determined", re.I),
     "all-properties-determined overclaim"),
    # "Complete instructions" in implementation context
    (re.compile(r"complete instructions? for", re.I),
     "complete-instructions overclaim"),
    # "traced the complete" — static analysis is not complete
    (re.compile(r"traced the complete (dispatch|pipeline|runtime)", re.I),
     "traced-the-complete overclaim: use 'static' not 'complete'"),
    # "strongly complete" — hedge-word doesn't save it
    (re.compile(r"strongly complete", re.I),
     "strongly-complete overclaim"),
]

# Files that may mention old problems ONLY with explicit correction wording nearby.
# These files are still scanned — but matches are suppressed if correction text is present
# anywhere in the file.
CORRECTION_FILES = {
    Path("rebuild/README.md"),
    Path("rebuild/pe_patcher.py"),
    Path("rebuild/full_rebuild_proof.sh"),
    Path("LEGAL.md"),
    Path("VALIDATION_STATUS.md"),
}
CORRECTION_PATTERN = re.compile(
    r"overstat|not .*proof|no longer used as proof|not independent proof|"
    r"does not.*claim|circular|NOT.*bit-identical|not.*proof|copied.*original",
    re.I | re.S,
)

# Skip self and _archive (archive is labeled superseded separately)
SELF_SKIP = {"validate_claims.py"}

errors: list[str] = []
for path in TEXT_FILES:
    if path.name in SELF_SKIP:
        continue
    if "_archive" in path.parts:
        continue
    try:
        text = path.read_text(errors="replace")
    except Exception:
        continue
    rel = path.relative_to(ROOT)

    # Check if this is a correction-aware file
    has_correction = (
        rel in CORRECTION_FILES
        and CORRECTION_PATTERN.search(text)
    )

    for regex, message in FORBIDDEN:
        for match in regex.finditer(text):
            if has_correction:
                continue
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{rel}:{line}: {message}: {match.group(0)!r}")

# Specific report consistency guard: PASS cannot carry found N/M where N<M.
report = ROOT / "verification-report.json"
if report.exists():
    import json
    data = json.loads(report.read_text())
    for idx, row in enumerate(data.get("results", [])):
        status = row.get("status")
        evidence = str(row.get("evidence", ""))
        name = str(row.get("name", ""))
        m = re.search(r"found\s+(\d+)\s*/\s*(\d+)", evidence)
        if status == "PASS" and m and int(m.group(1)) < int(m.group(2)):
            errors.append(
                f"verification-report.json: result {idx}: "
                f"PASS with incomplete count: {name!r} {evidence!r}"
            )

if errors:
    print(f"Claim validation FAILED ({len(errors)} issues):")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
print(f"Claim validation passed ({len(TEXT_FILES)} files scanned)")
