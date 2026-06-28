#!/usr/bin/env python3
from pathlib import Path
"""
Analyze FP8 encoding patterns across FSR shader passes.
Examines how weights are encoded in the DXIL LLVM IR.

Usage:
    python weight_encoding.py [--dxil-dir DIR] [--output FILE]
"""

import os, re

def find_blob(ver, func):
    irl = f"os.path.dirname(os.path.dirname(os.path.abspath(__file__)))/build/llvm_ir/{ver}"
    for f in sorted(os.listdir(irl)):
        if not f.endswith(".ll"): continue
        path = os.path.join(irl, f)
        with open(path) as fh:
            for line in fh:
                m = re.match(r"define void @([a-zA-Z0-9_.]+)\(\)", line)
                if m and m.group(1) == func:
                    return path
    return None

# Analyze weight encoding for key passes
passes = [
    "fsr4_model_v07_fp8_no_scale_pass7",
    "fsr4_model_v07_fp8_no_scale_pass9",
    "fsr4_model_v07_fp8_no_scale_pass1",
    "fsr4_model_v07_fp8_no_scale_prepass",
    "fsr4_model_v07_fp8_no_scale_postpass",
]

for func in passes:
    print(f"=== {func} ===")
    for ver in ["4_0_2", "4_1_0"]:
        path = find_blob(ver, func)
        if not path:
            print(f"  {ver}: not found")
            continue
        with open(path) as f:
            lines = f.readlines()
        
        # rawBufferLoad byte widths (the i8 N parameter = component mask byte count)
        load_widths = {}
        for line in lines:
            if "rawBufferLoad" not in line:
                continue
            m = re.search(r"rawBufferLoad\.\w+\(i32 (\d+)", line)
            if m:
                load_widths[m.group(1)] = load_widths.get(m.group(1), 0) + 1
        
        # rawBufferStore
        store_count = sum(1 for l in lines if "rawBufferStore" in l)
        
        # Handle types
        handles = set()
        for line in lines:
            m = re.match(r"  %\d+ = call %dx.types.Handle @dx.op.createHandle\(i32 57, i8 (\d+), i32 (\d+), i32 (\d+)", line)
            if m:
                kind = m.group(1)  # 0=SRV, 1=UAV
                space = m.group(2)
                idx = m.group(3)
                handles.add(f"{kind}:{space}:{idx}")
        
        # Type casts
        bitcasts = sum(1 for l in lines if "bitcast" in l)
        uitofp = sum(1 for l in lines if "uitofp" in l)
        sitofp = sum(1 for l in lines if "sitofp" in l)
        fptoui = sum(1 for l in lines if "fptoui" in l)
        
        # Data types loaded
        load_types = set()
        for line in lines:
            m = re.search(r"rawBufferLoad\.(\w+)", line)
            if m:
                load_types.add(m.group(1))
        
        print(f"  {ver}: {len(lines)} lines, handles={sorted(handles)}")
        print(f"    loads: {load_widths}, stores: {store_count}, load_types: {load_types}")
        print(f"    casts: bitcast={bitcasts}, uitofp={uitofp}, sitofp={sitofp}, fptoui={fptoui}")
    print()


if __name__ == "__main__":
    main()
