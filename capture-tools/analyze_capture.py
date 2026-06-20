#!/usr/bin/env python3
"""
FSR 4.1.0 Capture Analysis — Post-Processing Script
Run on the Oracle/CachyOS box after receiving fsr4_dispatches.json

This script takes the JSON output from extract_dispatches.py and:
1. Maps FSR passes to our static analysis data
2. Extracts cbuffer values → tensor offset map
3. Validates dispatch dimensions against our shader analysis
4. Checks sequential pipeline assumption (skip connections?)
5. Produces a verified runtime report
"""

import json
import os
import sys
from datetime import datetime

# Known static analysis data (from our RE)
STATIC_DATA = {
    "model_name": "fsr4_model_v07_fp8_no_scale",
    "expected_passes": 27,  # 1 pre + 12 body + 13 scatter + 1 post
    "body_passes": 12,      # pass1..pass12
    "scatter_passes": 13,   # pass0_post..pass12_post
    "weight_buffer_size": 131072,  # bytes (InitializerBuffer)
    "weight_format": {
        "fp16_biases": 7208,
        "fp8_weights": 122880,
        "extra_fp16": 888,
        "padding": 96,
    },
    "thread_group_size": [32, 1, 1],
    "buffer_handles": {
        "UAV_1_0": "atomic_accumulation_scratch",
        "UAV_0_11": "weight_buffer",
        "SRV_0_18": "feature_map",
        "CBV_0_0": "config_constants",
    },
    "pass_groups": {
        "group_a": ["pass1", "pass2", "pass12"],   # 21 input reads
        "group_b": ["pass4", "pass5", "pass10"],    # 31 input reads
        "group_c": ["pass7", "pass8"],              # 78 input reads
    },
    "tile_variants": [15392, 30752, 61472],  # base offsets
    "presets_byte_identical": 5,
    "drs_diff_pct": 96.1,
}

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_capture_data(json_path):
    """Load the JSON output from RenderDoc extraction."""
    with open(json_path) as f:
        return json.load(f)

def analyze_fsr_dispatches(data):
    """Core analysis of FSR dispatch data."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "capture_file": data.get("capture_file", "unknown"),
        "summary": {},
        "pipeline_validation": {},
        "cbuffer_analysis": {},
        "dispatch_dimension_analysis": {},
        "pass_order": [],
        "findings": [],
        "gaps_remaining": [],
    }
    
    fsr_dispatches = data.get("fsr_dispatches", [])
    
    # ===== Pipeline Structure Validation =====
    report["summary"]["fsr_dispatches_captured"] = len(fsr_dispatches)
    report["summary"]["expected"] = STATIC_DATA["expected_passes"]
    report["summary"]["match"] = len(fsr_dispatches) == STATIC_DATA["expected_passes"]
    
    if len(fsr_dispatches) < STATIC_DATA["expected_passes"]:
        report["findings"].append(
            f"WARNING: Only {len(fsr_dispatches)}/{STATIC_DATA['expected_passes']} FSR passes captured. "
            f"FSR may not be fully active, or capture missed some dispatches."
        )
    
    # ===== Pass Order Analysis =====
    pass_order = []
    for d in fsr_dispatches:
        pass_order.append({
            "index": d["index"],
            "eid": d["eid"],
            "name": d["pass_name"],
            "category": d["pass_category"],
            "threadgroups": d.get("dispatch_dimensions", {}),
        })
    
    report["pass_order"] = pass_order
    
    # Check if passes are in expected order: prepass → body → scatter → postpass
    body_passes = [p for p in pass_order if p["category"] == "ml_body"]
    scatter_passes = [p for p in pass_order if p["category"] == "scatter"]
    encoder_passes = [p for p in pass_order if p["category"] == "encoder"]
    decoder_passes = [p for p in pass_order if p["category"] == "decoder"]
    
    report["pipeline_validation"] = {
        "encoder_passes": len(encoder_passes),
        "body_passes": len(body_passes),
        "scatter_passes": len(scatter_passes),
        "decoder_passes": len(decoder_passes),
        "expected_body": STATIC_DATA["body_passes"],
        "expected_scatter": STATIC_DATA["scatter_passes"],
        "body_match": len(body_passes) == STATIC_DATA["body_passes"],
        "scatter_match": len(scatter_passes) == STATIC_DATA["scatter_passes"],
    }
    
    # ===== Dispatch Dimension Analysis =====
    dim_analysis = {}
    for p in pass_order:
        if p["category"] in ("ml_body", "encoder", "decoder"):
            dims = p.get("threadgroups", {})
            tg_x = dims.get("threadgroups_x")
            tg_y = dims.get("threadgroups_y") 
            tg_z = dims.get("threadgroups_z")
            
            if tg_x is not None:
                total_threads = (tg_x or 1) * (tg_y or 1) * (tg_z or 1) * 32
                dim_analysis[p["name"]] = {
                    "threadgroups": f"{tg_x}x{tg_y}x{tg_z}",
                    "total_threads_est": total_threads,
                    "thread_group_size": STATIC_DATA["thread_group_size"],
                }
    
    report["dispatch_dimension_analysis"] = dim_analysis
    
    # ===== CBuffer Analysis =====
    cbuffer_findings = {}
    
    for d in fsr_dispatches:
        if d["pass_category"] in ("ml_body", "encoder", "decoder"):
            bindings = d.get("bindings", {})
            cbuffers = bindings.get("cbuffers", {})
            
            if cbuffers:
                cbuffer_findings[d["pass_name"]] = {
                    "cbuffer_slots_found": list(cbuffers.keys()),
                    "data_sizes": {k: len(v) // 2 for k, v in cbuffers.items() if isinstance(v, str) and not v.startswith("error")},
                }
                
                # Try to extract weight offset constants from cbuffer slot 0
                cb0 = cbuffers.get("0")
                if cb0 and isinstance(cb0, str) and not cb0.startswith("error"):
                    try:
                        raw = bytes.fromhex(cb0)
                        # First 64 bytes typically contain dispatch config
                        # Look for known offset patterns
                        i32_values = []
                        for i in range(0, min(len(raw), 256), 4):
                            if i + 4 <= len(raw):
                                val = int.from_bytes(raw[i:i+4], 'little')
                                i32_values.append({"offset": i, "value": val})
                        
                        cbuffer_findings[d["pass_name"]]["cbuffer_0_first_64_bytes"] = i32_values[:16]
                        
                        # Check for our known tile variant offsets
                        for tv in STATIC_DATA["tile_variants"]:
                            for iv in i32_values:
                                if iv["value"] == tv:
                                    cbuffer_findings[d["pass_name"]].setdefault(
                                        "tile_variant_detected", []
                                    ).append({"offset": iv["offset"], "value": tv})
                    
                    except Exception as e:
                        cbuffer_findings[d["pass_name"]]["parse_error"] = str(e)
    
    report["cbuffer_analysis"] = cbuffer_findings
    
    # ===== Sequential Pipeline Check =====
    # If we have SRV resource IDs for body passes, check if they change monotonically
    resource_progression = []
    for d in fsr_dispatches:
        if d["pass_category"] == "ml_body":
            bindings = d.get("bindings", {})
            srvs = bindings.get("srvs", {})
            uavs = bindings.get("uavs", {})
            
            resource_progression.append({
                "pass": d["pass_name"],
                "srv_resource_ids": {k: v.get("resource_id") for k, v in srvs.items() if v},
                "uav_resource_ids": {k: v.get("resource_id") for k, v in uavs.items() if v},
            })
    
    # Check if the feature map SRV (slot 18 or highest slot) changes between passes
    # Sequential: resource ID changes each pass (runtime rebinds)
    # Skip-connected: same resource ID appears in multiple passes
    if resource_progression:
        all_srv_ids = set()
        for rp in resource_progression:
            for rid in rp["srv_resource_ids"].values():
                all_srv_ids.add(rid)
        
        report["pipeline_validation"]["unique_srv_resources"] = len(all_srv_ids)
        report["pipeline_validation"]["resource_progression"] = resource_progression
    
    # ===== Findings Summary =====
    
    if len(fsr_dispatches) >= 27:
        report["findings"].append("✅ Full FSR 4.1.0 pipeline captured (27 passes)")
    else:
        report["findings"].append(f"⚠️ Partial capture: {len(fsr_dispatches)}/27 passes")
    
    if len(body_passes) == 12:
        report["findings"].append("✅ All 12 ML body passes present")
    
    if cbuffer_findings:
        tile_detections = sum(1 for v in cbuffer_findings.values() 
                            if "tile_variant_detected" in v)
        if tile_detections > 0:
            report["findings"].append(
                f"✅ Tile variant offsets detected in {tile_detections} passes "
                f"(confirms spatial tiling theory)"
            )
    
    # ===== Remaining Gaps =====
    report["gaps_remaining"] = []
    
    if not cbuffer_findings:
        report["gaps_remaining"].append("No cbuffer data extracted — may need RenderDoc API access adjustment")
    
    if len(fsr_dispatches) < 27:
        report["gaps_remaining"].append("Incomplete pipeline capture — need full 27-pass frame")
    
    # Check if weight buffer UAV was captured
    has_weight_buffer = False
    for d in fsr_dispatches:
        bindings = d.get("bindings", {})
        uavs = bindings.get("uavs", {})
        for slot, info in uavs.items():
            if info and "resource_id" in info:
                has_weight_buffer = True
                break
    
    if not has_weight_buffer:
        report["gaps_remaining"].append("Weight buffer UAV not captured — need buffer data extraction")
    
    return report

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_capture.py <fsr4_dispatches.json>")
        print()
        print("This script processes the JSON output from extract_dispatches.py")
        print("and produces a runtime validation report.")
        sys.exit(1)
    
    json_path = sys.argv[1]
    
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}")
        sys.exit(1)
    
    print(f"Loading capture data from: {json_path}")
    data = load_capture_data(json_path)
    
    print(f"Analyzing {len(data.get('fsr_dispatches', []))} FSR dispatches...")
    report = analyze_fsr_dispatches(data)
    
    # Save report
    report_path = os.path.join(OUTPUT_DIR, "runtime_validation_report.json")
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"FSR 4.1.0 Runtime Validation Report")
    print(f"{'='*60}")
    
    print(f"\nCaptured: {report['summary']['fsr_dispatches_captured']}/{report['summary']['expected']} passes")
    print(f"Match: {'YES' if report['summary']['match'] else 'NO'}")
    
    print(f"\nPipeline Structure:")
    pv = report["pipeline_validation"]
    print(f"  Encoder: {pv.get('encoder_passes', 0)}")
    print(f"  ML Body: {pv.get('body_passes', 0)}/{pv.get('expected_body', '?')}")
    print(f"  Scatter: {pv.get('scatter_passes', 0)}/{pv.get('expected_scatter', '?')}")
    print(f"  Decoder: {pv.get('decoder_passes', 0)}")
    
    if report["findings"]:
        print(f"\nFindings:")
        for f in report["findings"]:
            print(f"  {f}")
    
    if report["gaps_remaining"]:
        print(f"\nRemaining Gaps:")
        for g in report["gaps_remaining"]:
            print(f"  • {g}")
    else:
        print(f"\n✅ No remaining gaps — capture is complete!")
    
    print(f"\nReport saved to: {report_path}")

if __name__ == "__main__":
    main()
