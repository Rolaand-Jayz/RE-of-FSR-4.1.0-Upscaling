#!/usr/bin/env python3
"""
PE section comparison tool for fsr_data.dll rebuilds.

This is the canonical comparison tool. The historical pe_patcher.py
has been moved to _archive/ -- it copied original bytes and produced
a circular MD5 match that proved nothing.

This tool intentionally does NOT produce a bit-identical output by copying bytes
from the original DLL. Earlier versions did that and the resulting MD5 equality
was circular: if differing sections, headers, and overlay bytes are replaced with
original bytes, an identical hash is inevitable and proves nothing about an
independent rebuild.

Use this script to compare an independently built DLL against the original and
emit per-region hashes/differences. A rebuilt artifact may be useful if its data
sections and exported API are correct, but byte-for-byte equality is only valid
when every region matches without being patched from the original.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Section:
    name: str
    header_offset: int
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int


@dataclass
class RegionResult:
    region: str
    original_sha256: str
    rebuilt_sha256: str
    original_size: int
    rebuilt_size: int
    matches: bool
    differing_bytes: int | None = None
    first_difference: int | None = None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_sections(data: bytes) -> tuple[int, int, list[Section]]:
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    nsec = struct.unpack_from("<H", data, pe_off + 6)[0]
    optsz = struct.unpack_from("<H", data, pe_off + 20)[0]
    sections: list[Section] = []
    for i in range(nsec):
        off = pe_off + 24 + optsz + i * 40
        name = data[off:off + 8].rstrip(b"\x00").decode("ascii", errors="replace")
        virtual_size = struct.unpack_from("<I", data, off + 8)[0]
        virtual_address = struct.unpack_from("<I", data, off + 12)[0]
        raw_size = struct.unpack_from("<I", data, off + 16)[0]
        raw_offset = struct.unpack_from("<I", data, off + 20)[0]
        sections.append(Section(name, off, virtual_address, virtual_size, raw_offset, raw_size))
    header_end = pe_off + 24 + optsz + nsec * 40
    return pe_off, header_end, sections


def compare_bytes(region: str, original: bytes, rebuilt: bytes) -> RegionResult:
    common = min(len(original), len(rebuilt))
    first_diff = None
    diff_count = abs(len(original) - len(rebuilt))
    for i in range(common):
        if original[i] != rebuilt[i]:
            diff_count += 1
            if first_diff is None:
                first_diff = i
    if first_diff is None and len(original) != len(rebuilt):
        first_diff = common
    matches = original == rebuilt
    return RegionResult(
        region=region,
        original_sha256=sha256(original),
        rebuilt_sha256=sha256(rebuilt),
        original_size=len(original),
        rebuilt_size=len(rebuilt),
        matches=matches,
        differing_bytes=0 if matches else diff_count,
        first_difference=None if matches else first_diff,
    )


def section_map(sections: list[Section]) -> dict[str, Section]:
    return {s.name: s for s in sections}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original", default=os.environ.get("ORIGINAL_DLL"), help="Original AMD fsr_data.dll")
    ap.add_argument("--rebuilt", default="fsr_data_prepatch.dll", help="Independently rebuilt DLL to compare")
    ap.add_argument("--json-out", default="section-comparison.json", help="Comparison report path")
    ap.add_argument("--require-all-match", action="store_true", help="Exit non-zero unless every compared region matches without patching")
    args = ap.parse_args()

    if not args.original:
        ap.error("--original or ORIGINAL_DLL is required")
    original_path = Path(args.original)
    rebuilt_path = Path(args.rebuilt)
    if not original_path.exists():
        ap.error(f"original not found: {original_path}")
    if not rebuilt_path.exists():
        ap.error(f"rebuilt not found: {rebuilt_path}")

    original = original_path.read_bytes()
    rebuilt = rebuilt_path.read_bytes()
    _, orig_header_end, orig_sections = parse_sections(original)
    _, rebuilt_header_end, rebuilt_sections = parse_sections(rebuilt)

    results: list[RegionResult] = []
    results.append(compare_bytes("headers", original[:orig_header_end], rebuilt[:rebuilt_header_end]))

    rebuilt_by_name = section_map(rebuilt_sections)
    for sec in orig_sections:
        rsec = rebuilt_by_name.get(sec.name)
        if rsec is None:
            results.append(RegionResult(sec.name, sha256(original[sec.raw_offset:sec.raw_offset + sec.raw_size]), "", sec.raw_size, 0, False, sec.raw_size, 0))
            continue
        odata = original[sec.raw_offset:sec.raw_offset + sec.raw_size]
        rdata = rebuilt[rsec.raw_offset:rsec.raw_offset + rsec.raw_size]
        results.append(compare_bytes(sec.name, odata, rdata))

    orig_overlay_start = max(s.raw_offset + s.raw_size for s in orig_sections)
    rebuilt_overlay_start = max(s.raw_offset + s.raw_size for s in rebuilt_sections)
    results.append(compare_bytes("overlay", original[orig_overlay_start:], rebuilt[rebuilt_overlay_start:]))

    report = {
        "original": str(original_path),
        "rebuilt": str(rebuilt_path),
        "original_sha256": sha256(original),
        "rebuilt_sha256": sha256(rebuilt),
        "all_regions_match_without_patching": all(r.matches for r in results),
        "regions": [asdict(r) for r in results],
        "note": "No bytes were copied from the original into the rebuilt file. This is a comparison report, not a patch proof.",
    }
    Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Original SHA256: {report['original_sha256']}")
    print(f"Rebuilt  SHA256: {report['rebuilt_sha256']}")
    print("Region comparison:")
    for r in results:
        status = "MATCH" if r.matches else "DIFF"
        detail = "" if r.matches else f" ({r.differing_bytes} bytes differ; first=0x{r.first_difference:x})"
        print(f"  {r.region:10s} {status}{detail}")
    print(f"Report: {args.json_out}")

    if args.require_all_match and not report["all_regions_match_without_patching"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())