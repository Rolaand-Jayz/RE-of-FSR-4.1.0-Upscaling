#!/usr/bin/env python3
"""
Parse the DXIL LLVM IR for NN passes to extract cbuffer-derived InitializerBuffer offsets.

The cbuffer (b0) contains tensor layout parameters including byte offsets
into InitializerBuffer (t1). This script traces all cbufferLoadLegacy calls
to determine how offsets are delivered at runtime.

Usage:
    python trace_cbuffer.py [--dxil-dir DIR] [--output FILE]
"""

import os, re, json, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Trace cbuffer offset loads in FSR 4.1.0 DXIL")
    parser.add_argument("--dxil-dir", default="/mnt/workdrive/fsr-re/build/llvm_ir/4_1_0",
        help="Directory containing DXIL LLVM IR files")
    parser.add_argument("-o", "--output", default=None,
        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()


import re, glob, struct

LLVM_DIR = "/mnt/workdrive/fsr-re/build/llvm_ir/4_1_0"

# Find all NN pass blobs (those with "pass" in their entry name)
pass_files = {}
for f in sorted(glob.glob(f"{LLVM_DIR}/blob_*.ll")):
    with open(f) as fh:
        content = fh.read()
    
    # Get entry point name
    m = re.search(r'ptr @(\w+)', content)
    if not m:
        continue
    entry = m.group(1)
    
    # Only NN passes
    if 'pass' not in entry.lower() and 'prepass' not in entry.lower():
        continue
    
    pass_files[f] = entry

print(f"Found {len(pass_files)} NN pass blobs")
print()

# For each pass, extract the cbuffer layout
# The pattern is:
#   %handle_b0 = call @dx.op.createHandle(i32 57, i8 2, ...)  -- CBV
#   %handle_t0 = call @dx.op.createHandle(i32 57, i8 1, ...)  -- SRV (input)
#   %handle_t1 = call @dx.op.createHandle(i32 57, i8 1, ...)  -- SRV (InitializerBuffer)
#   %val = call @dx.op.cbufferLoadLegacy(i32 59, %handle_b0, i32 INDEX)
#
# Then later: rawBufferLoad(%handle_t1, %computed_offset, ...)
# where %computed_offset involves cbuffer-loaded values

# Strategy: for each pass, find all cbuffer loads and their indices
# Then trace which loaded values are used as offsets for InitializerBuffer access

# Key insight: in the 4.0.2 HLSL, the InitializerBuffer handle (t1) is created,
# and the tensor's threadGroupStorageByteOffset is used as a base.
# In DXIL, this offset is loaded from the cbuffer.

# Let me parse a few key passes

key_passes = {
    'pass0': 'encoder1 downscale (first conv)',
    'pass1': 'encoder2 RB0 (first residual)',
    'pass6': 'encoder3 downscale',
    'pass7': 'bottleneck RB0',
    'pass9': 'bottleneck RB2 (last bottleneck)',
    'pass13': 'decoder2 RB2 (final upscale)',
}

for filepath, entry in sorted(pass_files.items(), key=lambda x: x[1]):
    # Extract pass number
    pm = re.search(r'pass(\d+)', entry)
    if not pm:
        continue
    pass_num = pm.group(1)
    
    if f'pass{pass_num}' not in key_passes:
        continue
    
    desc = key_passes[f'pass{pass_num}']
    
    with open(filepath) as fh:
        content = fh.read()
    
    lines = content.split('\n')
    
    # Find all cbufferLoadLegacy calls and their indices
    cbuffer_loads = []
    for i, line in enumerate(lines):
        m = re.search(r'cbufferLoadLegacy\.\w+\(i32 59, %[^,]+, i32 (\d+)\)', line)
        if m:
            idx = int(m.group(1))
            # Get the result register
            rm = re.search(r'%(\d+)\s*=', line)
            reg = rm.group(1) if rm else '?'
            cbuffer_loads.append((idx, reg, line.strip()[:120]))
    
    # Find rawBufferLoad calls for InitializerBuffer (t1)
    # We need to identify which handle is t1 (InitializerBuffer)
    # Pattern: createHandle(i32 57, i8 1, i32 0, i32 1, ...) for t1
    
    # Extract resource bindings from metadata
    res_match = re.search(r'!dx\.resources\s*=\s*!\{!([^}]+)\}', content)
    
    print(f"=== Pass {pass_num}: {entry} ({desc}) ===")
    print(f"  Cbuffer loads: {len(cbuffer_loads)}")
    
    # Print cbuffer index range
    if cbuffer_loads:
        indices = [x[0] for x in cbuffer_loads]
        print(f"  Cbuffer indices: {min(indices)}-{max(indices)} ({len(set(indices))} unique)")
        
        # Print all unique cbuffer indices
        print(f"  Unique indices: {sorted(set(indices))}")
    
    # Check for large constant values that might be offsets
    # Look for: add i32 %val, LARGE_CONSTANT
    # or: mul i32 %val, CONSTANT  
    large_consts = set()
    for line in lines:
        for m in re.finditer(r'i32\s+(\d{3,})', line):
            v = int(m.group(1))
            if 100 <= v <= 200000:
                large_consts.add(v)
    
    if large_consts:
        # Filter to values that look like InitializerBuffer offsets
        offset_like = sorted(v for v in large_consts if v > 1000)
        if offset_like:
            print(f"  Large constants (>1000): {offset_like[:20]}")
    
    print()


if __name__ == "__main__":
    main()
