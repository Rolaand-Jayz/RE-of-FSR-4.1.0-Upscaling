#!/usr/bin/env python3
"""
Parse FP8 initializer schema and compare 4.0.2 vs 4.1.0 weights.

Produces statistical comparison: unique value counts, distribution histograms,
and byte-level change analysis between versions.

Usage:
    python weight_compare.py [--v402 DIR] [--v410 DIR] [--offsets FILE] [--output FILE]
"""

import re, struct, os, json, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Compare weight distributions between FSR versions")
    parser.add_argument("--v402-dir", default="/mnt/workdrive/fsr-re/extracted/v402_initializers",
        help="Directory with 4.0.2 weight blobs")
    parser.add_argument("--v410-dir", default="/mnt/workdrive/fsr-re/extracted/v410_initializers",
        help="Directory with 4.1.0 weight blobs")
    parser.add_argument("--offsets", default=None,
        help="Tensor offset JSON (from parse_offsets.py)")
    parser.add_argument("-o", "--output", default=None,
        help="Output report file path (default: stdout)")
    args = parser.parse_args()


import re, struct, os, json

HLSL = "/path/to/sdk/source"
SRC = "/path/to/sdk/source"
DLL_410 = "/mnt/workdrive/fsr-re/build/dll_v410.dll"
REPORT = "/mnt/workdrive/fsr-re/reports"
EXTRACT = "/mnt/workdrive/fsr-re/extracted/fp8_weights"

with open(HLSL) as f:
    content = f.read()

blocks = re.split(r"(const\s+Tensor)", content)
offsets = []
for i in range(1, len(blocks), 2):
    if i + 1 >= len(blocks):
        break
    full = blocks[i] + blocks[i + 1]
    if "InitializerBuffer" not in full:
        continue
    name_match = re.search(r"Tensor[^=]+\s+(\w+)\s*=", full)
    if not name_match:
        continue
    name = name_match.group(1)
    offset_match = re.search(r"(\d+),\s*//\s*threadGroupStorageByteOffset", full)
    if not offset_match:
        continue
    offset = int(offset_match.group(1))
    if offset >= 130088:
        continue
    offsets.append((name, offset))

seen = set()
unique = []
for name, offset in offsets:
    if name not in seen:
        seen.add(name)
        unique.append((name, offset))

unique.sort(key=lambda x: x[1])

total = 130088
schema = []
for i, (name, offset) in enumerate(unique):
    size = unique[i + 1][1] - offset if i + 1 < len(unique) else total - offset
    schema.append({"name": name, "offset": offset, "size": size})

print(f"FP8 Schema: {len(schema)} tensors")
for s in schema:
    kind = "BIAS" if "bias" in s["name"].lower() else "WEIGHT"
    print(f"  0x{s['offset']:06x}  {s['size']:>6d}B  {kind:6s}  {s['name']}")

bias_bytes = sum(s["size"] for s in schema if "bias" in s["name"].lower())
weight_bytes = sum(s["size"] for s in schema if "bias" not in s["name"].lower())
print(f"\nBias: {bias_bytes}B ({bias_bytes//4} floats), Weight: {weight_bytes}B (FP8)")

os.makedirs(REPORT, exist_ok=True)
with open(os.path.join(REPORT, "fp8_initializer_schema.json"), "w") as f:
    json.dump({"total_size": total, "tensors": schema}, f, indent=2)

# Load data
with open(os.path.join(SRC, "fsr4_model_v07_fp8_no_scale_quality", "initializers.bin"), "rb") as f:
    init_402 = f.read()

with open(DLL_410, "rb") as f:
    dll_410 = f.read()

# 4.1.0 blobs (skip descriptor tables)
blobs_410 = [
    ("blob0", 0x8b3f1c + 0x46c, 0x8b3f1c + 131124),
    ("blob1", 0x8d6354 + 0x488, 0x8d6354 + 131116),
    ("blob2", 0x8fa4f8 + 0x474, 0x8fa4f8 + 131160),
    ("blob3", 0x91c930 + 0x48c, 0x91c930 + 131104),
]

print("\n=== Blob sizes ===")
for name, start, end in blobs_410:
    size = end - start
    diff = size - len(init_402)
    print(f"  {name}: {size:,}B (diff from 4.0.2: {diff:+d})")

# Use blob1 for comparison
b1_start = blobs_410[1][1]
b1_end = blobs_410[1][2]
b1 = dll_410[b1_start:b1_end]

max_off = max(s["offset"] + s["size"] for s in schema)
print(f"\nMax schema offset: {max_off}, 4.0.2 size: {len(init_402)}, 4.1.0 blob1: {len(b1)}")

print("\n=== Bias Comparison (4.0.2 vs 4.1.0 blob1) ===")
for s in schema:
    if "bias" not in s["name"].lower():
        continue
    off, sz = s["offset"], s["size"]
    if off + sz > min(len(b1), len(init_402)):
        print(f"  {s['name']}: OUT OF RANGE")
        continue
    f402 = struct.unpack(f"<{sz//4}f", init_402[off:off+sz])
    f410 = struct.unpack(f"<{sz//4}f", b1[off:off+sz])
    changed = sum(1 for a, b in zip(f402, f410) if a != b)
    print(f"  {s['name']}: {changed}/{sz//4} changed")

print("\n=== FP8 Weight Comparison (4.0.2 vs 4.1.0 blob1) ===")
for s in schema:
    if "bias" in s["name"].lower():
        continue
    off, sz = s["offset"], s["size"]
    if off + sz > min(len(b1), len(init_402)):
        print(f"  {s['name']}: OUT OF RANGE")
        continue
    d402 = init_402[off:off+sz]
    d410 = b1[off:off+sz]
    changed = sum(1 for a, b in zip(d402, d410) if a != b)
    pct = changed / sz * 100 if sz > 0 else 0
    print(f"  {s['name']}: {changed:,}/{sz:,} bytes changed ({pct:.1f}%)")

# Extract all individual weights
os.makedirs(os.path.join(EXTRACT, "v402"), exist_ok=True)
os.makedirs(os.path.join(EXTRACT, "v410"), exist_ok=True)

print("\n=== Extracting individual weights ===")
for s in schema:
    off, sz = s["offset"], s["size"]
    if off + sz <= len(init_402):
        with open(os.path.join(EXTRACT, "v402", s["name"] + ".bin"), "wb") as f:
            f.write(init_402[off:off+sz])
    if off + sz <= len(b1):
        with open(os.path.join(EXTRACT, "v410", s["name"] + ".bin"), "wb") as f:
            f.write(b1[off:off+sz])

print(f"Extracted {len(schema)} weight tensors to {EXTRACT}/")
print("\nDone.")


if __name__ == "__main__":
    main()
