#!/usr/bin/env python3
"""
Parse FP8 initializer format from 4.0.2 source schema and apply to 4.1.0 blobs.

Reads the tensor offset map and extracts individual weight tensors from
the raw blob data, decoding FP8 values and reporting statistics.

Usage:
    python parse_weights.py [--blob FILE] [--offsets FILE] [--output FILE]
"""

import re, struct, os, json, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Parse individual weight tensors from blob")
    parser.add_argument("--blob", default=None,
        help="Path to weight blob file")
    parser.add_argument("--offsets", default=None,
        help="Path to tensor offset JSON (from parse_offsets.py)")
    parser.add_argument("-o", "--output", default=None,
        help="Output file path (default: stdout)")
    args = parser.parse_args()


import re
import struct
import os
import json
import sys

SRC = '/path/to/sdk/source'
DLL_402 = str(Path(__file__).resolve().parents[1] / "build/dll_v402.dll")
DLL_410 = str(Path(__file__).resolve().parents[1] / "build/dll_v410.dll")
REPORT = str(Path(__file__).resolve().parents[1] / "reports")
EXTRACT = str(Path(__file__).resolve().parents[1] / "extracted/fp8_weights")
LOG = str(Path(__file__).resolve().parents[1] / "reports/progress.log")

os.makedirs(EXTRACT, exist_ok=True)
os.makedirs(os.path.join(EXTRACT, 'v402'), exist_ok=True)
os.makedirs(os.path.join(EXTRACT, 'v410'), exist_ok=True)

def log(msg):
    with open(LOG, 'a') as f:
        f.write(msg + '\n')
    print(msg)

def parse_hlsl_weights(filepath):
    """Parse weight tensor declarations from an HLSL file."""
    with open(filepath) as f:
        content = f.read()
    
    weights = []
    
    # Pattern: const TensorXX< BufferStorage > variable_name = {
    #   ... various uint/int params ...
    #   OFFSET, // threadGroupStorageByteOffset
    #   storage_variable_name };
    
    # Find all tensor declarations
    # Look for threadGroupStorageByteOffset as the key indicator
    tensor_pattern = re.compile(
        r'const\s+(\w+<\s*\w+\s*>)\s+(\w+)\s*=\s*\{([^}]+)\}',
        re.MULTILINE
    )
    
    for match in tensor_pattern.finditer(content):
        tensor_type = match.group(1).strip()
        var_name = match.group(2).strip()
        body = match.group(3)
        
        # Only process InitializerBuffer references
        if 'InitializerBuffer' not in body:
            continue
        
        # Extract the offset (threadGroupStorageByteOffset)
        # It's the second-to-last value before the storage reference
        lines = [l.strip().rstrip(',').strip() for l in body.split('\n') if l.strip()]
        
        # Parse values - each line has a value and possibly a comment
        values = []
        for line in lines:
            line = line.split('//')[0].strip().rstrip(',')
            if line:
                try:
                    if '(' in line:
                        # e.g. uint4(2, 2, 7, 16)
                        values.append(line)
                    elif '.' in line:
                        values.append(float(line))
                    else:
                        values.append(int(line, 0))
                except:
                    values.append(line)
        
        if len(values) >= 2:
            # For Tensor types, the offset is the value before the storage reference
            # Pattern: ... offset, storage_name }
            # Find the offset (numeric value before last non-numeric)
            offset = None
            for i in range(len(values) - 2, -1, -1):
                if isinstance(values[i], (int, float)):
                    offset = values[i]
                    break
            
            if offset is not None:
                weights.append({
                    'name': var_name,
                    'type': tensor_type,
                    'offset': offset,
                    'raw_values': values,
                })
    
    return weights

def parse_hlsl_file_detailed(filepath):
    """More detailed parsing of HLSL tensor declarations."""
    with open(filepath) as f:
        content = f.read()
    
    weights = []
    
    # Find blocks that reference InitializerBuffer
    # Pattern: const TensorType<...> varname = { ... OFFSET ... storage_varname };
    # where storage_varname references InitializerBuffer
    
    # Split on tensor declarations
    parts = re.split(r'const\s+\w', content)
    
    # Better approach: find all "threadGroupStorageByteOffset" lines
    # and work backwards to find the tensor name
    
    lines = content.split('\n')
    current_tensor = None
    current_body = []
    in_tensor = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Start of tensor declaration
        tensor_start = re.match(r'\s*const\s+(Tensor\d\w*\s*<\s*\w+\s*>)\s+(\w+)\s*=\s*\{', line)
        if tensor_start:
            current_tensor = {
                'type': tensor_start.group(1).strip(),
                'name': tensor_start.group(2).strip(),
            }
            current_body = []
            in_tensor = True
            continue
        
        if in_tensor:
            if stripped.startswith('};') or stripped == '}':
                in_tensor = False
                
                # Check if this tensor uses InitializerBuffer
                body_str = '\n'.join(current_body)
                if 'InitializerBuffer' in body_str:
                    # Parse the body values
                    offset = None
                    for body_line in current_body:
                        if 'threadGroupStorageByteOffset' in body_line:
                            # Extract the offset value
                            val_match = re.search(r'(\d+)', body_line.split('//')[0])
                            if val_match:
                                offset = int(val_match.group(1))
                    
                    if offset is None:
                        # Try parsing from raw values
                        nums = []
                        for body_line in current_body:
                            cleaned = body_line.split('//')[0].strip().rstrip(',')
                            try:
                                nums.append(int(cleaned, 0))
                            except:
                                try:
                                    nums.append(float(cleaned))
                                except:
                                    pass
                        # offset is usually the second-to-last number
                        if len(nums) >= 2:
                            offset = nums[-2]
                    
                    if offset is not None:
                        current_tensor['offset'] = offset
                        weights.append(current_tensor)
                
                current_tensor = None
                current_body = []
            else:
                current_body.append(stripped)
    
    return weights

# Parse all FP8 HLSL passes files
log("=== Parsing 4.0.2 FP8 HLSL for weight offsets ===")

variant = 'fp8_no_scale_quality'
variant_dir = f'{SRC}/fsr4_model_v07_{variant}'

# Parse pre, passes, and post HLSL files
all_weights = {}
for hlsl_file in ['pre.hlsl', 'passes_1080.hlsl', 'passes_2160.hlsl', 'passes_4320.hlsl', 'post.hlsl']:
    filepath = f'{variant_dir}/{hlsl_file}'
    if not os.path.exists(filepath):
        continue
    
    weights = parse_hlsl_file_detailed(filepath)
    log(f"  {hlsl_file}: {len(weights)} weight tensors")
    
    for w in weights:
        name = w['name']
        if name not in all_weights:
            all_weights[name] = w
            all_weights[name]['source_file'] = hlsl_file

log(f"\nTotal unique weight tensors: {len(all_weights)}")

# Sort by offset
sorted_weights = sorted(all_weights.values(), key=lambda x: x['offset'])

log("\nWeight tensor layout (sorted by offset):")
for w in sorted_weights:
    log(f"  0x{w['offset']:06x} ({w['offset']:>8d}): {w['name']} ({w['type']})")

# Calculate sizes (distance to next offset)
total_size = 130088  # Known initializer size
log(f"\nInitializer size: {total_size:,} bytes")

for i, w in enumerate(sorted_weights):
    if i + 1 < len(sorted_weights):
        w['size'] = sorted_weights[i + 1]['offset'] - w['offset']
    else:
        w['size'] = total_size - w['offset']
    log(f"  {w['name']}: offset={w['offset']}, size={w['size']}")

# Save the weight schema
schema = {
    'variant': variant,
    'total_size': total_size,
    'num_weights': len(sorted_weights),
    'weights': sorted_weights,
}

with open(f'{REPORT}/fp8_weight_schema.json', 'w') as f:
    json.dump(schema, f, indent=2)

# Now extract individual weights from 4.0.2 and 4.1.0 blobs
log("\n=== Extracting individual weights ===")

# Load 4.0.2 FP8 quality initializer
with open(f'{variant_dir}/initializers.bin', 'rb') as f:
    init_402 = f.read()

# Load 4.1.0 FP8 blobs (candidates from earlier analysis)
# Blob 1 at 0x8d6354 seems like quality variant (second blob, similar position to 4.0.2)
# We need to figure out which 4.1.0 blob corresponds to which variant

# First, let's check if the 4.1.0 blobs have the same internal structure
# by looking at the descriptor table (first ~1.2KB)

# Extract FP8 data from 4.1.0 blobs (skipping descriptor tables)
blob_410_info = [
    ('blob0', 0x8b3f1c, 131124, 0x46c),   # name, offset, total_size, fp8_data_offset
    ('blob1', 0x8d6354, 131116, 0x488),
    ('blob2', 0x8fa4f8, 131160, 0x474),
    ('blob3', 0x91c930, 131104, 0x48c),
]

with open(DLL_410, 'rb') as f:
    dll_410 = f.read()

# For each 4.1.0 blob, extract the FP8 data and check size
log("\n4.1.0 FP8 data sizes:")
for name, offset, total, fp8_offset in blob_410_info:
    fp8_size = total - fp8_offset
    log(f"  {name}: {fp8_size:,} bytes (4.0.2: {total_size:,} bytes, diff: {fp8_size - total_size:+d})")

# The sizes are VERY close to 4.0.2 (within ~100 bytes)
# This strongly suggests the same architecture with slightly different weight values

# Extract weights from 4.0.2
log("\nExtracting 4.0.2 weights...")
for w in sorted_weights:
    data = init_402[w['offset']:w['offset'] + w['size']]
    out_path = f'{EXTRACT}/v402/{w["name"]}.bin'
    with open(out_path, 'wb') as f:
        f.write(data)

log(f"Extracted {len(sorted_weights)} weight tensors to {EXTRACT}/v402/")

# Now extract from 4.1.0 blob1 (likely quality variant)
# Use the same offsets, adjusted for the FP8 data start
log("\nExtracting 4.1.0 weights from blob1 (quality candidate)...")
blob1_data = dll_410[0x8d6354 + 0x488 : 0x8d6354 + 131116]
fp8_410_size = len(blob1_data)
log(f"  4.1.0 FP8 data: {fp8_410_size:,} bytes")

# Check if the weight schema still applies
for w in sorted_weights:
    if w['offset'] + w['size'] <= fp8_410_size:
        data = blob1_data[w['offset']:w['offset'] + w['size']]
        out_path = f'{EXTRACT}/v410/{w["name"]}.bin'
        with open(out_path, 'wb') as f:
            f.write(data)

log(f"Extracted weights from 4.1.0 blob1")

# Verify: compare first and last weight tensors
log("\n=== Verification ===")
for w in sorted_weights[:3]:
    w402 = init_402[w['offset']:w['offset'] + min(32, w['size'])]
    w410 = blob1_data[w['offset']:w['offset'] + min(32, w['size'])]
    match = w402 == w410
    log(f"  {w['name']}: match={match}")
    log(f"    4.0.2: {w402.hex()}")
    log(f"    4.1.0: {w410.hex()}")

log("\n=== Done ===")


if __name__ == "__main__":
    main()
