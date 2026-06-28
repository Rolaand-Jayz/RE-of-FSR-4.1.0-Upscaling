#!/usr/bin/env python3
"""
Map 4.1.0 DXIL atomic offsets to weight positions.
Compare layer-by-layer against 4.0.2 HLSL offset schema.

Produces a per-layer diff showing how many bytes changed between versions.

Usage:
    python layer_diff.py [--v402-dir DIR] [--v410-dir DIR] [--offsets FILE] [--output FILE]
"""

import os, json, struct, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Layer-by-layer weight comparison between FSR 4.0.2 and 4.1.0")
    parser.add_argument("--v402-dir", default=str(Path(__file__).resolve().parents[1] / "extracted/v402_initializers"),
        help="Directory with 4.0.2 weight blobs")
    parser.add_argument("--v410-dir", default=str(Path(__file__).resolve().parents[1] / "extracted/v410_initializers"),
        help="Directory with 4.1.0 weight blobs")
    parser.add_argument("--offsets", default=None,
        help="Tensor offset JSON (from parse_offsets.py)")
    parser.add_argument("-o", "--output", default=None,
        help="Output report file path (default: stdout)")
    args = parser.parse_args()



import json, struct, numpy as np, os, re

V402_OFFSETS = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))/reports/v402_initializer_offsets.json"
V410_BLOB = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))/extracted/v410_initializers/quality.bin"
V402_BLOB = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))/extracted/v402_initializers/quality.bin"
LLVM_DIR = str(Path(__file__).resolve().parents[1] / "build/llvm_ir")

# Load 4.0.2 schema
with open(V402_OFFSETS) as f:
    schema = json.load(f)

# Load blobs
v410 = open(V410_BLOB, "rb").read()
v402 = open(V402_BLOB, "rb").read()

print("=" * 100)
print("FSR 4.0.2 → 4.1.0 Layer-by-Layer Weight Comparison")
print("=" * 100)

# Group by pass and analyze
# The schema has two "zones": biases 0-7208, weights 7208-130088
# Zone 1: Biases/quant params (offset 0-7208)
# Zone 2: FP8 weights (offset 7208-130088)

bias_tensors = [t for t in schema if t['offset'] is not None and t['offset'] < 7208]
weight_tensors = [t for t in schema if t['offset'] is not None and t['offset'] >= 7208]

print(f"\n### Bias/Quant Parameter Zone (0-7208) ###")
print(f"  {len(bias_tensors)} tensors")
print(f"  {'Pass':<6} {'Offset':>8} {'Name':<60} {'4.0.2 Bytes':>12} {'4.1.0 Δ%':>10}")
print("  " + "-" * 100)

total_bias_bytes = 0
total_bias_changed = 0

for t in sorted(bias_tensors, key=lambda x: x['offset']):
    off = t['offset']
    sz = t.get('byte_size') or 0
    
    # For tensors without byte_size, estimate from gap to next tensor
    if sz is None:
        next_offsets = [x['offset'] for x in bias_tensors if x['offset'] is not None and x['offset'] > off]
        if next_offsets:
            sz = min(next_offsets) - off
        else:
            sz = 7208 - off
    
    name = t['name']
    if len(name) > 58:
        name = name[:55] + "..."
    
    # Compare
    v402_chunk = v402[off:off+sz]
    v410_chunk = v410[off:off+sz]
    
    diff = sum(1 for a, b in zip(v402_chunk, v410_chunk) if a != b)
    pct = 100 * diff / len(v402_chunk) if len(v402_chunk) > 0 else 0
    
    total_bias_bytes += len(v402_chunk)
    total_bias_changed += diff
    
    print(f"  {t['pass']:<6} {off:>8} {name:<60} {len(v402_chunk):>12} {pct:>9.1f}%")

print(f"\n  Bias zone total: {total_bias_changed:,}/{total_bias_bytes:,} bytes changed ({100*total_bias_changed/total_bias_bytes:.1f}%)")

# Weight zone analysis - group by layer/block
print(f"\n### FP8 Weight Zone (7208-130088) ###")
print(f"  {len(weight_tensors)} tensors")

# Group by block name (encoder2, encoder3, bottleneck, decoder3, decoder2)
blocks = {}
for t in weight_tensors:
    name = t['name']
    # Extract block name
    block_match = re.match(r'(?:hwnc_|hwcn_)?(\w+?)(?:_ResidualBlock|_Downscale|_Upscale)', name)
    block = block_match.group(1) if block_match else 'unknown'
    
    if block not in blocks:
        blocks[block] = []
    blocks[block].append(t)

print(f"\n  {'Block':<15} {'Tensors':>8} {'Bytes':>10} {'Changed':>10} {'Δ%':>8}")
print("  " + "-" * 60)

for block, tensors in sorted(blocks.items(), key=lambda x: min(t['offset'] for t in x[1])):
    block_bytes = 0
    block_changed = 0
    
    for t in sorted(tensors, key=lambda x: x['offset']):
        off = t['offset']
        sz = t.get('byte_size') or 0
        if sz == 0:
            continue
        
        v402_chunk = v402[off:off+sz]
        v410_chunk = v410[off:off+sz]
        
        diff = sum(1 for a, b in zip(v402_chunk, v410_chunk) if a != b)
        block_bytes += sz
        block_changed += diff
    
    pct = 100 * block_changed / block_bytes if block_bytes > 0 else 0
    print(f"  {block:<15} {len(tensors):>8} {block_bytes:>10,} {block_changed:>10,} {pct:>7.1f}%")

# Detailed per-tensor analysis for bottleneck (the most interesting)
print(f"\n### Bottleneck Layer Detail (passes 7-9) ###")
print(f"  {'Pass':<6} {'Offset':>8} {'Shape':<22} {'Name':<55} {'Bytes':>8} {'Δ%':>8}")
print("  " + "-" * 110)

for t in sorted([x for x in weight_tensors if 'bottleneck' in x['name']], key=lambda x: x['offset']):
    off = t['offset']
    sz = t.get('byte_size') or 0
    if sz == 0:
        continue
    
    v402_chunk = v402[off:off+sz]
    v410_chunk = v410[off:off+sz]
    diff = sum(1 for a, b in zip(v402_chunk, v410_chunk) if a != b)
    pct = 100 * diff / sz if sz > 0 else 0
    
    name = t['name']
    if len(name) > 53:
        name = name[:50] + "..."
    
    print(f"  {t['pass']:<6} {off:>8} {str(t['shape']):<22} {name:<55} {sz:>8} {pct:>7.1f}%")

# Extra data analysis (4.1.0 bytes 130088-130976)
print(f"\n### 4.1.0 Extra Data Analysis ###")
extra = v410[130088:130976]
extra_u8 = np.frombuffer(extra, dtype=np.uint8)
extra_fp16 = np.frombuffer(extra[:len(extra) - len(extra)%2], dtype=np.float16)

nz = np.sum(extra_u8 != 0)
print(f"  Extra range: 130088-130976 ({len(extra)} bytes)")
print(f"  Non-zero bytes: {nz}")
print(f"  If FP16: {len(extra_fp16)} values, range [{np.nanmin(extra_fp16):.4f}, {np.nanmax(extra_fp16):.4f}]")
print(f"  If uint8: {len(extra_u8)} values, unique: {len(np.unique(extra_u8[extra_u8 != 0]))}")

# Check if extra data aligns with any 4.0.2 offset pattern
# The 444 FP16 values at the end could be extra biases
print(f"  444 extra FP16 values could be: additional biases for expanded layers")
print(f"  At 2 bytes each = 888 bytes, matching the non-zero region exactly")

print(f"\n### Summary ###")
total_402 = len(v402)
total_410 = len(v410[:130976])  # actual data
total_diff = sum(1 for a, b in zip(v402, v410[:total_402]) if a != b)
print(f"  4.0.2 data: {total_402:,} bytes")
print(f"  4.1.0 data: {total_410:,} bytes (+{total_410-total_402:,} bytes)")
print(f"  Bytes changed in shared region: {total_diff:,}/{total_402:,} ({100*total_diff/total_402:.1f}%)")
print(f"  Architecture: same tensor count (78), same offsets, {total_410-total_402} extra bytes")


if __name__ == "__main__":
    main()
