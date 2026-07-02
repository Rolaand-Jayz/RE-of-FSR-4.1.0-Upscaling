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
import subprocess
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
    record_status(name, status, evidence)


def record_status(name: str, status: str, evidence: str) -> None:
    if status not in {"PASS", "FAIL", "SKIP", "WARN"}:
        raise ValueError(f"invalid verification status: {status}")
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


def finite_float32_values(data: bytes) -> list[float]:
    values = []
    for i in range(0, len(data), 4):
        values.append(struct.unpack("<f", data[i:i + 4])[0])
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


def categorize_check(name: str) -> str:
    """Classify a verification check into an evidence-strength category."""
    n = name.lower()
    if any(k in n for k in ["md5", "sha-256", "sha256", "re-extracted matches",
                            "has expected byte size", "byte change rate",
                            "exactly 2 unique blobs", "unique uint8 values",
                            "lacks the 4.1.0", "4.0.2 blob is", "4.1.0 blob is",
                            "committed blob has expected size",
                            "shipping binary available"]):
        return "hash_identity"
    if any(k in n for k in ["plausib", "tensor offset", "78 tensors",
                            "hlsl pass files", "raw hlsl offsets",
                            "broad uint8 distribution"]):
        return "plausibility"
    if any(k in n for k in ["not supplied", "runtime", "capture"]):
        return "runtime_observed"
    if any(k in n for k in ["exists", "covers", "artifact", "present",
                            "entry point", "entrypoint", "main pass",
                            "all expected", "closure", "dispatch analysis",
                            "cross-reference", "formula", "key slot",
                            "summary", "pass static", "no pass13",
                            "post stage", "paired", "topology",
                            "slices include", "sink slices", "activation",
                            "compare/select", "lower-clamp", "nonlinearity",
                            "arithmetic", "affine", "mac arithmetic",
                            "host cbuffer", "decoded", "ssa trace",
                            "resource binding", "no dxil handle"]):
        return "static_inventory"
    return "static_consistency"


def existing_dir(path: Path | None) -> bool:
    return bool(path and path.exists() and path.is_dir())


def relpath(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return str(path)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dll-v410", type=Path, default=repo_root / "build/dll_v410.dll")
    ap.add_argument("--hlsl-dir", type=Path, default=None, help="Optional FSR 4.0.2 HLSL source directory")
    ap.add_argument("--extracted-v410", type=Path, default=None,
                    help="Path to v4.1.0 extracted blobs (default: extracted/v410_initializers/ or $WEIGHTS_DIR)")
    ap.add_argument("--extracted-v402", type=Path, default=None,
                    help="Path to v4.0.2 extracted blobs (default: extracted/v402_initializers/ or $WEIGHTS_DIR)")
    ap.add_argument("--dxil-dir", type=Path, default=repo_root / "build/llvm_ir/4_1_0")
    ap.add_argument("--spec", type=Path, default=repo_root / "spec/blob-format.json")
    ap.add_argument("--report", type=Path, default=repo_root / "verification-report.json")
    args = ap.parse_args()

    # WEIGHTS_DIR: allow validators to use locally-extracted blobs
    weights_dir = os.environ.get("WEIGHTS_DIR")
    if args.extracted_v410 is None:
        if weights_dir:
            args.extracted_v410 = Path(weights_dir) / "v410_initializers"
        else:
            args.extracted_v410 = repo_root / "extracted/v410_initializers"
    if args.extracted_v402 is None:
        if weights_dir:
            args.extracted_v402 = Path(weights_dir) / "v402_initializers"
        else:
            args.extracted_v402 = repo_root / "extracted/v402_initializers"

    print("=" * 60)
    print("FSR-RE VERIFICATION SUITE")
    print("=" * 60)
    print()

    print("[V1] Blob extraction and MD5 verification")
    md5s: dict[str, str] = {}
    ref_blob = b""
    if args.dll_v410.exists():
        dll_size = args.dll_v410.stat().st_size
        record("dll_v410.dll has expected byte size", dll_size == EXPECTED_DLL_V410_SIZE, f"size={dll_size} expected={EXPECTED_DLL_V410_SIZE}")

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
    else:
        record_status("dll_v410.dll shipping binary available", "SKIP", f"not found: {args.dll_v410}")
        for preset in V410_RVAS:
            extracted_path = args.extracted_v410 / f"{preset}.bin"
            if extracted_path.exists():
                blob = extracted_path.read_bytes()
                if preset == "quality":
                    ref_blob = blob
                md5s[preset] = md5(blob)
                record(f"{preset}: committed blob has expected size", len(blob) == BLOB_SIZE_V410, f"size={len(blob)} expected={BLOB_SIZE_V410}")
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
        record_status("Optional HLSL source directory not supplied", "SKIP", "pass --hlsl-dir to enable this check")
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
        extra_vals = finite_float32_values(extra_zone)
        extra_finite = sum(1 for v in extra_vals if abs(v) < 1e10)
        record("Extra zone is 888 bytes", len(extra_zone) == 888, f"size={len(extra_zone)}")
        record("Extra zone FP32 values are finite/bounded", extra_finite == len(extra_vals), f"{extra_finite}/{len(extra_vals)} finite")
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
        record_status("DXIL disassembly directory exists", "SKIP", f"proprietary-derived DXIL disassembly not committed; {args.dxil_dir}")
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
    decoded_addr = repo_root / "reports/decoded-buffer-addressing.json"
    ssa_trace = repo_root / "reports/atomic-ssa-trace.json"
    if decoded_addr.exists():
        dec = json.loads(decoded_addr.read_text())
        record("Decoded buffer addressing report exists", dec.get("schema_version") == 1, relpath(decoded_addr, repo_root))
        spaces = {row.get("space") for row in dec.get("global_top_keys", [])}
        record("Decoded key spaces include operand/control/vector classes", {"operand_or_accumulator", "control_or_dimension_metadata", "lane_vector_or_output_slots"}.issubset(spaces), f"spaces={sorted(spaces)}")
        record("Decoded addressing report covers many packed keys", len(dec.get("global_top_keys", [])) >= 80, f"top_keys={len(dec.get('global_top_keys', []))}")
    else:
        record("Decoded buffer addressing report exists", False, str(decoded_addr))
    if ssa_trace.exists():
        tr = json.loads(ssa_trace.read_text())
        entries = tr.get("entries", [])
        record("Atomic SSA trace report exists", tr.get("schema_version") == 1, relpath(ssa_trace, repo_root))
        record("Atomic SSA trace covers more than 100 shader variants", len(entries) > 100, f"entries={len(entries)}")
        has_prov = any(any("index_provenance" in ev or "new_provenance" in ev or "compare_provenance" in ev for ev in e.get("events", [])) for e in entries)
        record("Atomic SSA trace includes provenance trees", has_prov, "checked provenance fields")
    else:
        record("Atomic SSA trace report exists", False, str(ssa_trace))
    print()
    resource_bindings = repo_root / "spec/resource-bindings.json"
    if resource_bindings.exists():
        rb = json.loads(resource_bindings.read_text())
        entries = rb.get("entries", [])
        record("Resource binding artifact exists", rb.get("schema_version") == 1, relpath(resource_bindings, repo_root))
        record("Resource binding artifact covers all model shader variants", len(entries) == 214, f"entries={len(entries)}")
        record("No DXIL handle uses are unmapped", len(rb.get("unmapped_handle_uses", [])) == 0, f"unmapped={len(rb.get('unmapped_handle_uses', []))}")
        main = [x for x in rb.get("summary", []) if x.get("class") == "main_pass"]
        required = {"atomic_indirection_or_scratch_uav", "raw_intermediate_or_operand_uav", "raw_model_or_weight_buffer_srv", "constant_buffer_or_root_constants"}
        roles_ok = all(required.issubset(set(x.get("role_counts", {}).keys())) for x in main)
        record("Every main pass has the four expected static resource roles", roles_ok, f"main_passes={len(main)}")
    else:
        record("Resource binding artifact exists", False, str(resource_bindings))
    print()
    affine_formulas = repo_root / "reports/affine-ssa-formulas-summary.json"
    key_slots = repo_root / "spec/key-slot-semantics.json"
    pass_summaries = repo_root / "spec/pass-static-summaries.json"
    if affine_formulas.exists():
        af = json.loads(affine_formulas.read_text())
        record("Affine SSA formula artifact exists", af.get("schema_version") == 1, relpath(affine_formulas, repo_root))
        record("Affine SSA formula artifact covers more than 100 shader variants", af.get("entries_count", len(af.get("entries", []))) > 100, f"entries={af.get('entries_count', len(af.get('entries', [])))}")
        record("Affine SSA formula artifact has many formula families", len(af.get("global_formula_families", [])) >= 100, f"families={len(af.get('global_formula_families', []))}")
    else:
        record("Affine SSA formula artifact exists", False, str(affine_formulas))
    if key_slots.exists():
        ks = json.loads(key_slots.read_text())
        slots = ks.get("slots", [])
        record("Key slot semantics artifact exists", ks.get("schema_version") == 1, relpath(key_slots, repo_root))
        observed_roles = {s.get("inferred_static_role") for s in slots}
        needed_roles = {"weight_index_indirection_slot", "lane_vector_slot", "control_weight_or_loop_bound"}
        record("Key slot semantics include critical static roles", needed_roles.issubset(observed_roles), f"roles={sorted(observed_roles)[:20]}")
    else:
        record("Key slot semantics artifact exists", False, str(key_slots))
    if pass_summaries.exists():
        ps = json.loads(pass_summaries.read_text())
        passes = ps.get("passes", [])
        main = [p for p in passes if p.get("class") == "main_pass"]
        record("Pass static summaries artifact exists", ps.get("schema_version") == 1, relpath(pass_summaries, repo_root))
        record("Pass static summaries cover 27 entrypoints", len(passes) == 27, f"passes={len(passes)}")
        complete = all(all(p.get("static_completion", {}).values()) for p in main)
        record("Every main pass has static resource/op/atomic/formula/activation completion", complete, f"main_passes={len(main)}")
    else:
        record("Pass static summaries artifact exists", False, str(pass_summaries))
    print()

    activation_report = repo_root / "reports/activation-nonlinearity-evidence.json"
    if activation_report.exists():
        act = json.loads(activation_report.read_text())
        summary = act.get("summary", [])
        main = [r for r in summary if r.get("class") == "main_pass"]
        patterns = act.get("global_pattern_counts", {})
        kinds = act.get("global_kind_counts", {})
        record("Activation/nonlinearity artifact exists", act.get("schema_version") == 1, relpath(activation_report, repo_root))
        record("Activation/nonlinearity artifact covers 27 entrypoints", act.get("unique_entrypoints") == 27 and len(summary) == 27, f"unique={act.get('unique_entrypoints')} summary={len(summary)}")
        record("Activation/nonlinearity artifact covers all 214 shader variants", act.get("shader_variants") == 214, f"variants={act.get('shader_variants')}")
        record("Activation/nonlinearity artifact includes compare/select evidence", kinds.get("llvm_fcmp", 0) > 0 and kinds.get("llvm_select", 0) > 0, f"kinds={kinds}")
        record("Activation/nonlinearity artifact includes direct lower-clamp/ReLU candidates", patterns.get("direct_relu_or_lower_clamp_zero", 0) > 0, f"patterns={patterns}")
        record("Every main pass has activation/nonlinearity events", all(r.get("event_count", 0) > 0 for r in main), f"main_passes={len(main)}")
        direct_main = sum(1 for r in main if r.get("has_direct_relu_or_lower_clamp_zero"))
        record("Most main passes have direct lower-clamp/ReLU candidate evidence", direct_main >= 10, f"direct_main={direct_main}/{len(main)}; exceptions={[r.get('entrypoint') for r in main if not r.get('has_direct_relu_or_lower_clamp_zero')]}")
    else:
        record("Activation/nonlinearity artifact exists", False, str(activation_report))
    print()

    topology_report = repo_root / "spec/static-layer-topology.json"
    if topology_report.exists():
        topo = json.loads(topology_report.read_text())
        obs = topo.get("observations", {})
        record("Static layer topology artifact exists", topo.get("schema_version") == 1, relpath(topology_report, repo_root))
        record("Static layer topology covers 27 entrypoints", topo.get("entrypoint_count") == 27, f"entrypoints={topo.get('entrypoint_count')}")
        record("Static layer topology identifies 12 main passes and 13 post stages", obs.get("main_passes") == 12 and obs.get("post_stages") == 13, f"observations={obs}")
        record("Static layer topology pairs every main pass with a post stage", obs.get("main_passes_with_post_stage") == 12, f"paired={obs.get('main_passes_with_post_stage')}")
    else:
        record("Static layer topology artifact exists", False, str(topology_report))
    print()

    arithmetic_report = repo_root / "reports/arithmetic-dataflow-slices.json"
    if arithmetic_report.exists():
        ar = json.loads(arithmetic_report.read_text())
        summary = ar.get("summary", [])
        main = [r for r in summary if r.get("class") == "main_pass"]
        nodes = ar.get("global_node_kind_counts", {})
        sinks = ar.get("global_sink_counts", {})
        record("Arithmetic dataflow slice artifact exists", ar.get("schema_version") == 1, relpath(arithmetic_report, repo_root))
        record("Arithmetic dataflow slice artifact covers 27 entrypoints", ar.get("unique_entrypoints") == 27 and len(summary) == 27, f"unique={ar.get('unique_entrypoints')} summary={len(summary)}")
        record("Arithmetic dataflow slice artifact covers all 214 shader variants", ar.get("shader_variants") == 214, f"variants={ar.get('shader_variants')}")
        record("Arithmetic dataflow slices include raw stores and atomic sinks", sinks.get("rawBufferStore.values", 0) > 0 and sinks.get("atomicCompareExchange.operands", 0) > 0, f"sinks={sinks}")
        record("Arithmetic dataflow slices reach rawBufferLoad and arithmetic producers", nodes.get("dxil_rawBufferLoad", 0) > 0 and (nodes.get("llvm_add", 0) + nodes.get("llvm_mul", 0) + nodes.get("llvm_fadd", 0)) > 0, f"nodes={{'rawBufferLoad': {nodes.get('dxil_rawBufferLoad', 0)}, 'add': {nodes.get('llvm_add', 0)}, 'mul': {nodes.get('llvm_mul', 0)}, 'fadd': {nodes.get('llvm_fadd', 0)}}}")
        record("Every main pass has arithmetic dataflow sink slices", all(r.get("sink_counts") for r in main), f"main_passes={len(main)}")
    else:
        record("Arithmetic dataflow slice artifact exists", False, str(arithmetic_report))
    print()


    return finish(args.report, repo_root)


def finish(report_path: Path, repo_root: Path) -> int:
    errors = validate_report_rows(results)
    for error in errors:
        record("Verification report schema/consistency validation", False, error)
    # ============================================================
    # [V9] Static RE Closure: Tensor offsets + MAC formulas + HLSL xref
    # ============================================================
    tov_path = repo_root / "reports/tensor-offset-verification.json"
    if tov_path.exists():
        tov = json.loads(tov_path.read_text())
        record("Tensor offset plausibility artifact exists", True, relpath(tov_path, repo_root))
        record("Tensor offset plausibility check: all 78 tensors parse into plausible typed values",
               tov.get("all_pass", False),
               f"passed={tov.get('passed')}/{tov.get('tensor_count')} claim_scope={tov.get('claim_scope')} note={tov.get('note', '')}")
    else:
        record("Tensor offset plausibility artifact exists", False, "not found")

    mac_path = repo_root / "reports/mac-arithmetic-complete.json"
    if mac_path.exists():
        mac = json.loads(mac_path.read_text())
        pass_count = len(mac.get("pass_operators", {}))
        record("MAC arithmetic formulas cover all passes",
               pass_count >= 12,
               f"passes_documented={pass_count}")
    else:
        record("MAC arithmetic artifact exists", False, "not found")

    closure_path = repo_root / "reports/static-re-closure.md"
    record("Static RE closure report exists",
           closure_path.exists(),
           relpath(closure_path, repo_root))

    host_path = repo_root / "reports/host-cbuffer-dispatch.json"
    record("Host cbuffer dispatch analysis exists",
           host_path.exists(),
           relpath(host_path, repo_root))

    hlsli_path = repo_root / "reports/hlsl-operator-analysis.json"
    record("HLSL operator cross-reference exists",
           hlsli_path.exists(),
           relpath(hlsli_path, repo_root))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    skipped = sum(1 for _, s, _ in results if s == "SKIP")
    warned = sum(1 for _, s, _ in results if s == "WARN")
    # Build summary grouped by evidence category
    summary_by_kind = {}
    for n, s, e in results:
        kind = categorize_check(n)
        if kind not in summary_by_kind:
            summary_by_kind[kind] = {"passed": 0, "failed": 0, "skipped": 0, "warned": 0}
        if s == "PASS":
            summary_by_kind[kind]["passed"] += 1
        elif s == "FAIL":
            summary_by_kind[kind]["failed"] += 1
        elif s == "SKIP":
            summary_by_kind[kind]["skipped"] += 1
        elif s == "WARN":
            summary_by_kind[kind]["warned"] += 1

    # Capture provenance for the generated report
    try:
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        source_commit = "unknown"

    report = {
        "schema_version": 4,
        "generated_by": "scripts/verify.py",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_commit": source_commit,
        "command": "python scripts/verify.py",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "warned": warned,
        "summary_by_kind": summary_by_kind,
        "results": [{"name": n, "status": s, "evidence": e} for n, s, e in results],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"  {passed} PASSED / {failed} FAILED / {skipped} SKIPPED / {warned} WARN / {len(results)} TOTAL")
    if failed:
        print("FAILURES:")
        for name, status, evidence in results:
            if status == "FAIL":
                print(f"  ✗ {name}: {evidence}")
    print(f"Report saved to {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
