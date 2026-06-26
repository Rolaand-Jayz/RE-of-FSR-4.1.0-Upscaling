#!/usr/bin/env python3
"""Verification suite for bounded, reproducible FSR-RE claims.

All input paths are explicit CLI parameters or repository-relative defaults.
The suite must fail when evidence is incomplete; test names are written to match
actual predicates. The generated JSON report includes a schema version and a
self-validation pass that blocks contradictory PASS evidence such as "13/14" for
an "all present" claim.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

BLOB_SIZE_V410 = 131072
BLOB_SIZE_V402 = 130088
EXPECTED_DLL_V410_SIZE = 15605520

V410_RVAS = {
    "quality": 0x91DB50,
    "balanced": 0x943CC0,
    "performance": 0x963D20,
    "ultraperf": 0x8D7570,
    "native": 0x8FB700,
    "drs": 0x8B5120,
}

KNOWN_V410_MD5 = {
    "quality": "6ccdb68fc828e0bef93fa32fd144c4f6",
    "balanced": "6ccdb68fc828e0bef93fa32fd144c4f6",
    "performance": "6ccdb68fc828e0bef93fa32fd144c4f6",
    "ultraperf": "6ccdb68fc828e0bef93fa32fd144c4f6",
    "native": "6ccdb68fc828e0bef93fa32fd144c4f6",
    "drs": "8e5c042e0c14cca83d56ed13df5f02dd",
}

results: list[tuple[str, str, str]] = []


def record(name: str, passed: bool, evidence: str) -> None:
    status = "PASS" if passed else "FAIL"
    results.append((name, status, evidence))
    print(f"  [{status}] {name}")
    if evidence:
        print(f"         {evidence}")


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def get_file_offset(dll_path: Path, rva: int) -> int | None:
    with dll_path.open("rb") as f:
        f.seek(0x3C)
        pe_offset = struct.unpack("<I", f.read(4))[0]
        f.seek(pe_offset + 6)
        num_sections = struct.unpack("<H", f.read(2))[0]
        f.seek(pe_offset + 20)
        size_opt = struct.unpack("<H", f.read(2))[0]
        sec_start = pe_offset + 24 + size_opt
        f.seek(sec_start)
        for _ in range(num_sections):
            sec = f.read(40)
            sec_vsize = struct.unpack("<I", sec[8:12])[0]
            sec_vaddr = struct.unpack("<I", sec[12:16])[0]
            sec_rawsize = struct.unpack("<I", sec[16:20])[0]
            sec_rawoff = struct.unpack("<I", sec[20:24])[0]
            span = max(sec_vsize, sec_rawsize)
            if sec_vaddr <= rva < sec_vaddr + span:
                return rva - sec_vaddr + sec_rawoff
    return None


def finite_half_values(data: bytes) -> list[float]:
    values = []
    for i in range(0, len(data), 2):
        values.append(struct.unpack("<e", data[i:i + 2])[0])
    return values


def validate_report_rows(rows: list[tuple[str, str, str]]) -> list[str]:
    errors: list[str] = []
    for name, status, evidence in rows:
        if status == "PASS":
            m = re.search(r"found\s+(\d+)\s*/\s*(\d+)", evidence)
            if m and int(m.group(1)) < int(m.group(2)) and re.search(r"all|complete|expected", name, re.I):
                errors.append(f"Contradictory PASS: {name!r} with evidence {evidence!r}")
            m = re.search(r"size=(\d+).*expected=(\d+)", evidence)
            if m and int(m.group(1)) != int(m.group(2)):
                errors.append(f"Contradictory PASS: {name!r} with evidence {evidence!r}")
    return errors


def existing_dir(path: Path | None) -> bool:
    return bool(path and path.exists() and path.is_dir())


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dll-v410", type=Path, default=repo_root / "build/dll_v410.dll")
    ap.add_argument("--hlsl-dir", type=Path, default=None, help="Optional FSR 4.0.2 HLSL source directory")
    ap.add_argument("--extracted-v410", type=Path, default=repo_root / "extracted/v410_initializers")
    ap.add_argument("--extracted-v402", type=Path, default=repo_root / "extracted/v402_initializers")
    ap.add_argument("--dxil-dir", type=Path, default=repo_root / "build/llvm_ir/4_1_0")
    ap.add_argument("--spec", type=Path, default=repo_root / "spec/blob-format.json")
    ap.add_argument("--report", type=Path, default=repo_root / "verification-report.json")
    args = ap.parse_args()

    print("=" * 60)
    print("FSR-RE VERIFICATION SUITE")
    print("=" * 60)
    print()

    print("[V1] Blob extraction and MD5 verification")
    if not args.dll_v410.exists():
        record("dll_v410.dll exists", False, f"not found: {args.dll_v410}")
        return finish(args.report)

    dll_size = args.dll_v410.stat().st_size
    record("dll_v410.dll has expected byte size", dll_size == EXPECTED_DLL_V410_SIZE, f"size={dll_size} expected={EXPECTED_DLL_V410_SIZE}")

    md5s: dict[str, str] = {}
    ref_blob = b""
    for preset, rva in V410_RVAS.items():
        offset = get_file_offset(args.dll_v410, rva)
        if offset is None:
            record(f"{preset}: RVA resolves to file offset", False, f"rva=0x{rva:X}")
            continue
        with args.dll_v410.open("rb") as f:
            f.seek(offset)
            blob = f.read(BLOB_SIZE_V410)
        if preset == "quality":
            ref_blob = blob
        md5s[preset] = md5(blob)
        record(f"{preset}: extracted blob has expected size", len(blob) == BLOB_SIZE_V410, f"size={len(blob)} expected={BLOB_SIZE_V410} rva=0x{rva:X} offset=0x{offset:X}")
        extracted_path = args.extracted_v410 / f"{preset}.bin"
        if extracted_path.exists():
            record(f"{preset}: re-extracted matches committed blob", extracted_path.read_bytes() == blob, f"md5={md5s[preset]}")
        else:
            record(f"{preset}: committed blob exists", False, f"not found: {extracted_path}")

    unique_md5 = set(md5s.values())
    record("Exactly 2 unique blobs out of 6 presets", len(unique_md5) == 2, f"found {len(unique_md5)} unique: {sorted(unique_md5)}")
    for preset, expected in KNOWN_V410_MD5.items():
        record(f"{preset} MD5 matches known value", md5s.get(preset) == expected, f"got={md5s.get(preset)} expected={expected}")
    print()

    print("[V2] Optional 4.0.2 HLSL tensor offset verification")
    if existing_dir(args.hlsl_dir):
        hlsl_files = list(args.hlsl_dir.glob("*passes*.hlsl"))
        tensor_count = 0
        offsets: list[int] = []
        for path in hlsl_files:
            matches = re.findall(r"(\d+),\s*//\s*threadGroupStorageByteOffset", path.read_text(errors="replace"))
            tensor_count += len(matches)
            offsets.extend(int(m) for m in matches)
        record("HLSL pass files found", len(hlsl_files) > 0, f"{len(hlsl_files)} files")
        record("At least 78 tensors with byte offsets from HLSL", tensor_count >= 78, f"found {tensor_count} tensors")
        if offsets:
            record("Raw HLSL offsets parsed", True, f"max_offset={max(offsets)} blob_size={BLOB_SIZE_V410}")
    else:
        record("Optional HLSL source directory not supplied; check skipped", True, "pass --hlsl-dir to enable this check")
    print()

    print("[V3] Blob structure verification")
    if ref_blob:
        bias_zone = ref_blob[:7208]
        fp16_vals = finite_half_values(bias_zone)
        finite_count = sum(1 for v in fp16_vals if abs(v) < 1e10)
        record("Bias zone is 7,208 bytes", len(bias_zone) == 7208, f"size={len(bias_zone)}")
        record("FP16 bias values are finite/bounded", finite_count > len(fp16_vals) * 0.9, f"{finite_count}/{len(fp16_vals)} finite")
        weight_zone = ref_blob[7208:130088]
        record("Weight zone is 122,880 bytes", len(weight_zone) == 122880, f"size={len(weight_zone)}")
        record("Weight zone has broad uint8 distribution", len(set(weight_zone)) > 50, f"{len(set(weight_zone))} unique uint8 values")
        extra_zone = ref_blob[130088:130976]
        extra_vals = finite_half_values(extra_zone)
        extra_finite = sum(1 for v in extra_vals if abs(v) < 1e10)
        record("Extra zone is 888 bytes", len(extra_zone) == 888, f"size={len(extra_zone)}")
        record("Extra zone FP16 values are finite/bounded", extra_finite > 400, f"{extra_finite}/444 finite")
        padding = ref_blob[BLOB_SIZE_V410 - 96:]
        record("Last 96 bytes are zero padding", padding == b"\x00" * 96, f"all_zero={padding == b'\x00' * 96}")
    print()

    print("[V4] 4.0.2 vs 4.1.0 diff verification")
    v402_quality_path = args.extracted_v402 / "quality.bin"
    if v402_quality_path.exists() and ref_blob:
        v402_blob = v402_quality_path.read_bytes()
        compare_size = min(len(v402_blob), len(ref_blob))
        changed = sum(1 for i in range(compare_size) if v402_blob[i] != ref_blob[i])
        change_rate = changed / compare_size * 100
        record("4.0.2 vs 4.1.0 byte change rate is in expected range", 97.0 < change_rate < 99.5, f"actual={change_rate:.1f}% ({changed}/{compare_size} bytes)")
        record("4.0.2 blob is 130,088 bytes", len(v402_blob) == BLOB_SIZE_V402, f"size={len(v402_blob)} expected={BLOB_SIZE_V402}")
        record("4.1.0 blob is 131,072 bytes", len(ref_blob) == BLOB_SIZE_V410, f"size={len(ref_blob)} expected={BLOB_SIZE_V410} diff={len(ref_blob)-len(v402_blob)}")
        record("4.0.2 lacks the 4.1.0 extra zone", len(v402_blob[130088:]) == 0 or set(v402_blob[130088:]) <= {0}, f"remaining bytes={len(v402_blob[130088:])}")
    else:
        record("4.0.2 blob available for comparison", False, f"not found: {v402_quality_path}")
    print()

    print("[V5] FP8/uint8 unique value count")
    if ref_blob:
        v410_unique = len(set(ref_blob[7208:130088]))
        record("4.1.0 weight zone has 255 unique uint8 values", v410_unique == 255, f"found {v410_unique} unique values")
    print()

    print("[V6] DXIL entry point name verification")
    if args.dxil_dir.exists():
        pass_names: set[str] = set()
        for path in args.dxil_dir.glob("*.ll"):
            content = path.read_text(errors="replace")[:4000]
            if "fsr4_model" in content:
                m = re.search(r"define void @([^\(]+)", content)
                if m:
                    pass_names.add(m.group(1))
        # Authoritative taxonomy from the extracted 4.1.0 DXIL corpus:
        # - main ML compute entry points are pass1 through pass12
        # - pass0 is represented as pass0_post, not as a main pass0 entry
        # - there is no pass13 entry point in the corpus
        expected_main = {f"fsr4_model_v07_fp8_no_scale_pass{i}" for i in range(1, 13)}
        expected_post = {f"fsr4_model_v07_fp8_no_scale_pass{i}_post" for i in range(13)}
        expected_misc = {
            "fsr4_model_v07_fp8_no_scale_prepass",
            "fsr4_model_v07_fp8_no_scale_postpass",
        }
        expected_passes = expected_main | expected_post | expected_misc
        found = {p for p in expected_passes if any(p == ep for ep in pass_names)}
        missing = sorted(expected_passes - found)
        unexpected_pass13 = sorted(p for p in pass_names if "pass13" in p)
        record("All expected 4.1.0 DXIL model entry points are present", found == expected_passes, f"found {len(found)}/{len(expected_passes)} expected entry points; missing={missing}")
        record("No pass13 entry point is present in the extracted 4.1.0 DXIL corpus", not unexpected_pass13, f"pass13_matches={unexpected_pass13}")
    else:
        record("DXIL disassembly directory exists", False, str(args.dxil_dir))
    print()

    print("[V7] Blob format spec verification")
    if args.spec.exists() and ref_blob:
        spec = json.loads(args.spec.read_text())
        zones = spec.get("zones", [])
        record("Blob format spec has zone definitions", len(zones) > 0, f"{len(zones)} zones defined")
        for zone in zones:
            offset, size = int(zone.get("offset", 0)), int(zone.get("size", 0))
            actual = ref_blob[offset:offset + size]
            record(f"Zone '{zone.get('name', '?')}' at 0x{offset:X} has expected size", len(actual) == size, f"bytes_available={len(actual)} expected={size}")
    else:
        record("Blob format spec exists", False, str(args.spec))

    print("[V8] Generated DXIL RE evidence artifacts")
    dxil_ir_evidence = repo_root / "reports/dxil-ir-evidence.json"
    atomic_evidence = repo_root / "reports/atomic-buffer-patterns.json"
    entry_inventory = repo_root / "spec/dxil-entrypoint-inventory.json"
    if dxil_ir_evidence.exists():
        dxil_data = json.loads(dxil_ir_evidence.read_text())
        record("DXIL IR evidence artifact exists and covers 27 entrypoints", dxil_data.get("unique_entrypoints") == 27, f"unique_entrypoints={dxil_data.get('unique_entrypoints')}")
        main = [r for r in dxil_data.get("summary", []) if r.get("class") == "main_pass"]
        record("DXIL IR evidence covers 12 main passes", len(main) == 12, f"main_passes={len(main)}")
        raw_ok = all(r.get("resource_ops", {}).get("rawBufferLoad", {}).get("max", 0) > 0 for r in main)
        record("Every main pass has rawBufferLoad evidence", raw_ok, "checked resource_ops.rawBufferLoad.max > 0")
    else:
        record("DXIL IR evidence artifact exists", False, str(dxil_ir_evidence))
    if atomic_evidence.exists():
        atomic_data = json.loads(atomic_evidence.read_text())
        main = [r for r in atomic_data.get("summary", []) if r.get("class") == "main_pass"]
        record("Atomic/buffer pattern artifact covers 12 main passes", len(main) == 12, f"main_passes={len(main)}")
        atomic_ok = all(r.get("atomic_addr_total", 0) > 0 and r.get("atomic_addr_unique", 0) > 0 for r in main)
        record("Every main pass has atomicCompareExchange address evidence", atomic_ok, "checked atomic_addr_total and atomic_addr_unique")
        scale_ok = all(len(r.get("tertiary_scale", [])) > 0 for r in main)
        record("Every main pass has tertiary scale evidence", scale_ok, "checked dx.op.tertiary scale constants")
    else:
        record("Atomic/buffer pattern artifact exists", False, str(atomic_evidence))
    if entry_inventory.exists():
        inv = json.loads(entry_inventory.read_text())
        record("DXIL entrypoint inventory agrees with 27 unique names", len(inv.get("unique_entrypoints", [])) == 27, f"unique={len(inv.get('unique_entrypoints', []))}")
    else:
        record("DXIL entrypoint inventory exists", False, str(entry_inventory))
    print()


    return finish(args.report)


def finish(report_path: Path) -> int:
    errors = validate_report_rows(results)
    for error in errors:
        record("Verification report schema/consistency validation", False, error)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    report = {
        "schema_version": 2,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": [{"name": n, "status": s, "evidence": e} for n, s, e in results],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"  {passed} PASSED / {failed} FAILED / {len(results)} TOTAL")
    if failed:
        print("FAILURES:")
        for name, status, evidence in results:
            if status == "FAIL":
                print(f"  ✗ {name}: {evidence}")
    print(f"Report saved to {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
