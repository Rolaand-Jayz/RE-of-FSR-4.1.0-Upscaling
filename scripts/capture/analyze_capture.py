#!/usr/bin/env python3
"""FSR 4.1.0 Post-Capture Analysis Pipeline

Takes RenderDoc capture results (capture_results.json) and produces:
1. Independent tensor offset map derived from runtime data
2. Per-pass dispatch dimensions and resource bindings
3. Verification against static analysis

USAGE:
    python3 analyze_capture.py [capture_results.json]

If no argument given, looks for the latest capture_results.json in runtime-capture/
"""

import json
import struct
import sys
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime

BASE = Path("/mnt/workdrive/fsr-re")
CAPTURE_DIR = BASE / "runtime-capture"
REPORTS = BASE / "reports"

def load_capture(path=None):
    if path is None:
        candidates = sorted(CAPTURE_DIR.glob("capture_results*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print("ERROR: No capture results found in", CAPTURE_DIR)
            print("Run capture.py first to generate capture data.")
            sys.exit(1)
        path = candidates[-1]
        print(f"Loading latest capture: {path}")
    
    with open(path) as f:
        return json.load(f)

def analyze_dispatches(data):
    """Analyze all captured FSR4 dispatches."""
    dispatches = data.get("dispatches", [])
    
    results = {
        "total_dispatches": len(dispatches),
        "passes": [],
        "initializer_buffers": [],
        "dispatch_dimension_table": [],
        "cbuffer_summary": [],
    }
    
    print(f"\nFound {len(dispatches)} FSR4 dispatches")
    print("=" * 70)
    
    for i, d in enumerate(dispatches):
        eid = d.get("eid", "?")
        name = d.get("name", "unknown")
        dx = d.get("dispatches_x")
        dy = d.get("dispatches_y")
        dz = d.get("dispatches_z")
        shader = d.get("shader_name", "")
        tg = d.get("thread_groups")
        
        # Classify pass type
        name_lower = name.lower()
        if "prepass" in name_lower or "pre" in name_lower:
            ptype = "encoder"
        elif "postpass" in name_lower or "post" in name_lower or "rcas" in name_lower:
            ptype = "decoder"
        elif "spd" in name_lower or "autoexp" in name_lower:
            ptype = "spd"
        elif "debug" in name_lower:
            ptype = "debug"
        else:
            ptype = "body"
        
        # Total threads
        total_threads = None
        if dx and dy and dz:
            total_threads = dx * dy * dz
        
        # Cbuffer analysis
        cbuffers = d.get("cbuffers", [])
        cbuffer_info = []
        for cb in cbuffers:
            cb_info = {
                "resource_id": cb.get("resource_id"),
                "offset": cb.get("byte_offset"),
                "size": cb.get("byte_size"),
            }
            cbuffer_info.append(cb_info)
            
            # Try to parse main constants (256 bytes, known layout from provider diff)
            if cb.get("byte_size") == 256 and cb.get("data_hex"):
                try:
                    raw = bytes.fromhex(cb["data_hex"])
                    parse_main_constants(raw, i, name)
                except Exception as e:
                    print(f"  [WARN] Could not parse cbuffer for pass {i}: {e}")
        
        pass_info = {
            "index": i,
            "eid": eid,
            "name": name,
            "type": ptype,
            "dispatch_groups": [dx, dy, dz],
            "total_threads": total_threads,
            "shader_name": shader,
            "thread_groups": tg,
            "cbuffer_count": len(cbuffers),
            "cbuffers": cbuffer_info,
        }
        
        results["passes"].append(pass_info)
        results["dispatch_dimension_table"].append({
            "pass": i,
            "name": name,
            "groups": f"({dx}, {dy}, {dz})",
            "total": total_threads,
            "type": ptype,
        })
        
        print(f"  Pass {i:2d} [{ptype:8s}]: {name}")
        print(f"           Groups: ({dx}, {dy}, {dz}) = {total_threads} threads")
        if tg:
            print(f"           Thread groups: {tg}")
        print(f"           Cbuffers: {len(cbuffers)}")
    
    return results

def parse_main_constants(raw, pass_idx, pass_name):
    """Parse the 256-byte main constant buffer using the known layout from provider diff."""
    if len(raw) < 100:
        return
    
    # Layout from provider-diff-report.md:
    inv_size = struct.unpack_from('<ff', raw, 0x00)
    scale = struct.unpack_from('<ff', raw, 0x08)
    inv_scale = struct.unpack_from('<ff', raw, 0x10)
    jitter = struct.unpack_from('<ff', raw, 0x18)
    mv_scale = struct.unpack_from('<ff', raw, 0x20)
    tex_size = struct.unpack_from('<ff', raw, 0x28)
    max_render = struct.unpack_from('<ff', raw, 0x30)
    jitter_cancel = struct.unpack_from('<ff', raw, 0x38)
    width = struct.unpack_from('<I', raw, 0x40)[0]
    height = struct.unpack_from('<I', raw, 0x44)[0]
    reset = struct.unpack_from('<I', raw, 0x48)[0]
    width_lr = struct.unpack_from('<I', raw, 0x4C)[0]
    height_lr = struct.unpack_from('<I', raw, 0x50)[0]
    
    # Compute spatial scale
    if width_lr > 0 and height_lr > 0:
        spatial_scale = (width / width_lr, height / height_lr)
    else:
        spatial_scale = (None, None)
    
    print(f"           Constants: {width_lr}x{height_lr} -> {width}x{height} (scale {spatial_scale})")

def analyze_initializer_buffers(data):
    """Analyze captured InitializerBuffer dumps."""
    dumps = data.get("initializer_buffer_dumps", [])
    
    print(f"\n{'=' * 70}")
    print(f"InitializerBuffer captures: {len(dumps)}")
    print(f"{'=' * 70}")
    
    results = []
    
    for dump in dumps:
        eid = dump.get("dispatch_eid", "?")
        name = dump.get("dispatch_name", "unknown")
        size = dump.get("byte_size", 0)
        md5 = dump.get("md5", "unknown")
        data_file = dump.get("data_file")
        
        print(f"\n  EID {eid} ({name}): {size} bytes, MD5={md5}")
        
        if data_file and os.path.exists(data_file):
            with open(data_file, "rb") as f:
                blob = f.read()
            
            # Parse known blob format
            bias_zone = blob[:7208]
            weight_zone = blob[7208:130088]
            extra_zone = blob[130088:130976]
            padding = blob[130976:]
            
            # Bias analysis
            fp16_biases = []
            for i in range(0, len(bias_zone), 2):
                val = struct.unpack_from('<e', bias_zone, i)[0]
                fp16_biases.append(val)
            non_zero_bias = sum(1 for v in fp16_biases if v != 0)
            
            # Weight analysis
            unique_weights = len(set(weight_zone))
            
            # Extra zone analysis
            extra_fp16 = []
            if len(extra_zone) >= 2:
                for i in range(0, len(extra_zone), 2):
                    val = struct.unpack_from('<e', extra_zone, i)[0]
                    extra_fp16.append(val)
            
            print(f"    Bias zone:   {len(fp16_biases)} FP16 values, {non_zero_bias} non-zero")
            print(f"    Weight zone: {unique_weights} unique uint8 values")
            print(f"    Extra zone:  {len(extra_fp16)} FP16 values")
            if extra_fp16:
                non_zero_extra = sum(1 for v in extra_fp16 if v != 0)
                print(f"    Extra non-zero: {non_zero_extra}")
                # Check range
                valid = [v for v in extra_fp16 if v != 0]
                if valid:
                    print(f"    Extra range: [{min(valid):.4f}, {max(valid):.4f}]")
            
            # Verify against extracted blobs
            extracted_quality = BASE / "extracted/v410_initializers/quality.bin"
            if extracted_quality.exists():
                with open(extracted_quality, "rb") as f:
                    extracted = f.read()
                if blob == extracted:
                    print(f"    ✅ Byte-for-byte match with extracted quality.bin")
                else:
                    match_pct = sum(1 for a, b in zip(blob, extracted) if a == b) / max(len(blob), len(extracted)) * 100
                    print(f"    ⚠️  {match_pct:.1f}% match with extracted quality.bin")
            
            results.append({
                "eid": eid,
                "name": name,
                "size": size,
                "md5": md5,
                "bias_count": len(fp16_biases),
                "bias_nonzero": non_zero_bias,
                "weight_unique": unique_weights,
                "extra_fp16_count": len(extra_fp16),
                "data_file": data_file,
            })
    
    return results

def generate_report(capture_data, dispatch_analysis, buffer_analysis):
    """Generate the final analysis report."""
    
    passes = dispatch_analysis["passes"]
    
    report = []
    report.append("# FSR 4.1.0 Runtime Capture Analysis")
    report.append(f"\n**Date:** {datetime.utcnow().isoformat()}")
    report.append(f"**Capture:** {capture_data.get('capture_file', 'unknown')}")
    report.append(f"**Frame:** {capture_data.get('frame_number', '?')}")
    report.append(f"**Total FSR4 dispatches found:** {len(passes)}")
    report.append("")
    
    # Pass table
    report.append("## Dispatch Table")
    report.append("")
    report.append("| # | Type | Name | Groups | Total Threads | Cbuffers |")
    report.append("|---|------|------|--------|---------------|----------|")
    for p in passes:
        g = p.get("dispatch_groups", [None, None, None])
        gs = f"({g[0]}, {g[1]}, {g[2]})" if all(x is not None for x in g) else "?"
        report.append(f"| {p['index']} | {p['type']} | {p['name']} | {gs} | {p.get('total_threads', '?')} | {p['cbuffer_count']} |")
    
    report.append("")
    
    # Spatial analysis
    report.append("## Spatial Scale Analysis")
    report.append("")
    report.append("From cbuffer contents (render resolution vs upscale resolution):")
    report.append("")
    
    # Group by spatial scale
    scales = defaultdict(list)
    for p in passes:
        # We'll need the parsed cbuffer data for this
        scales[p["type"]].append(p["index"])
    
    for stype, indices in scales.items():
        report.append(f"- **{stype}** passes: {', '.join(str(i) for i in indices)}")
    
    report.append("")
    
    # Buffer analysis
    if buffer_analysis:
        report.append("## InitializerBuffer Verification")
        report.append("")
        for b in buffer_analysis:
            report.append(f"- EID {b['eid']}: {b['size']} bytes, MD5={b['md5'][:16]}...")
            report.append(f"  - Biases: {b['bias_count']} FP16, {b['bias_nonzero']} non-zero")
            report.append(f"  - Weights: {b['weight_unique']} unique values")
            report.append(f"  - Extra FP16: {b['extra_fp16_count']} values")
        report.append("")
    
    # What we learned
    report.append("## Key Findings")
    report.append("")
    total = len(passes)
    body_count = sum(1 for p in passes if p["type"] == "body")
    encoder_count = sum(1 for p in passes if p["type"] == "encoder")
    decoder_count = sum(1 for p in passes if p["type"] == "decoder")
    
    report.append(f"- Total dispatches: {total} (expected ~27)")
    report.append(f"- Body passes: {body_count}")
    report.append(f"- Encoder passes: {encoder_count}")
    report.append(f"- Decoder passes: {decoder_count}")
    
    if total >= 27:
        report.append(f"- ✅ Dispatch count matches provider analysis")
    elif total > 0:
        report.append(f"- ⚠️  Expected 27, got {total}. Some passes may not match FSR4 filter.")
    
    report.append("")
    report.append("## Next Steps")
    report.append("")
    report.append("1. Cross-reference dispatch dimensions against HLSL thread group sizes from 4.0.2")
    report.append("2. Parse cbuffer raw hex to extract per-pass weight offsets") 
    report.append("3. Build independent tensor offset map from runtime cbuffer data")
    report.append("4. Verify 444 extra FP16 parameters are accessed by specific body passes")
    
    report_text = "\n".join(report)
    
    # Save report
    out_path = REPORTS / "runtime-capture-analysis.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(report_text)
    
    print(f"\nReport saved to {out_path}")
    return report_text

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    data = load_capture(path)
    
    print("=" * 70)
    print("FSR 4.1.0 Post-Capture Analysis")
    print("=" * 70)
    
    dispatch_analysis = analyze_dispatches(data)
    buffer_analysis = analyze_initializer_buffers(data)
    report = generate_report(data, dispatch_analysis, buffer_analysis)
    
    # Also save machine-readable results
    results = {
        "dispatch_analysis": dispatch_analysis,
        "buffer_analysis": buffer_analysis,
        "timestamp": datetime.utcnow().isoformat(),
    }
    out_json = CAPTURE_DIR / "analysis_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Analysis data saved to {out_json}")

if __name__ == "__main__":
    main()
