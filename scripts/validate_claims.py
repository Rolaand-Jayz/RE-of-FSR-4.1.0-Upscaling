#!/usr/bin/env python3
"""Fail CI on stale overclaims that caused the prior audit failure."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_FILES = [
    p for p in ROOT.rglob("*")
    if p.is_file()
    and ".git" not in p.parts
    and p.suffix.lower() in {".md", ".py", ".sh", ".json", ".yml", ".yaml"}
]

FORBIDDEN = [
    (re.compile(r"bit-identical[^\n]{0,160}(proof|proves|proved|complete|correct)", re.I), "bit-identical must not be presented as proof/completion"),
    (re.compile(r"from first principles", re.I), "from-first-principles overclaim"),
    (re.compile(r"complete reverse engineering", re.I), "complete reverse-engineering overclaim"),
    (re.compile(r"complete implementation guide", re.I), "implementation guide must not claim completeness"),
]

# Files allowed to mention the old problem while explicitly correcting it.
ALLOWLIST = {
    ROOT / "rebuild/README.md",
    ROOT / "rebuild/pe_patcher.py",
    ROOT / "rebuild/full_rebuild_proof.sh",
    ROOT / "LEGAL.md",
    ROOT / "VALIDATION_STATUS.md",
    ROOT / "scripts/validate_claims.py",
}

errors: list[str] = []
for path in TEXT_FILES:
    text = path.read_text(errors="replace")
    for regex, message in FORBIDDEN:
        for match in regex.finditer(text):
            if path in ALLOWLIST and re.search(r"overstat|not .*proof|no longer used as proof|not independent proof|does not.*claim", text, re.I | re.S):
                continue
            rel = path.relative_to(ROOT)
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
            errors.append(f"verification-report.json: result {idx}: PASS with incomplete count: {name!r} {evidence!r}")

if errors:
    print("Claim validation failed:")
    print("\n".join(errors))
    sys.exit(1)
print("Claim validation passed")
