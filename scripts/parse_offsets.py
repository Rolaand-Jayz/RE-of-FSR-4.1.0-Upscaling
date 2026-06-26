#!/usr/bin/env python3
from pathlib import Path
"""
Extract the InitializerBuffer offset map from 4.0.2 FP8 HLSL source.

Parses threadGroupStorageByteOffset attributes from the FSR4 model shader files
to build a complete tensor offset table (78 tensors with byte offsets, shapes,
and layer assignments).

Usage:
    python parse_offsets.py [--hlsl-dir DIR] [--output FILE]

Requires the FidelityFX SDK 4.0.2 HLSL source (MIT licensed).
"""

import re, os, json, argparse, sys

def main():
    parser = argparse.ArgumentParser(description="Extract FSR4 tensor offsets from HLSL source")
    parser.add_argument("--hlsl-dir",
        default=str(Path(__file__).resolve().parents[1] / "build/llvm_ir/4_0_2"),
        help="Directory containing HLSL shader source files")
    parser.add_argument("-o", "--output",
        default=None,
        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()



import re, os, json

SRC="/path/to/sdk/source"

def parse_hlsl_file(filepath):
    """Parse HLSL file for InitializerBuffer tensor references with offsets and shapes."""
    with open(filepath) as f:
        content = f.read()
    
    results = []
    
    # Split into pass sections
    pass_sections = re.split(r'#ifdef MLSR_PASS_(\w+)', content)
    
    idx = 1
    while idx < len(pass_sections):
        pass_name = pass_sections[idx]
        pass_code = pass_sections[idx + 1]
        
        # Find all storage_* = { InitializerBuffer } blocks
        # Then find the tensor definition that uses that storage, extracting offset and shape
        storage_blocks = re.finditer(
            r'const\s+(\w+)\s+storage_(\w+)\s*=\s*\{\s*InitializerBuffer\s*\}',
            pass_code
        )
        
        for m in storage_blocks:
            storage_type = m.group(1)
            var_name = m.group(2)
            storage_pos = m.end()
            
            # The tensor definition follows shortly after
            # Look for the next block that uses storage_<var_name>
            # Pattern: const <TensorType> <name> = { ... <offset>, // threadGroupStorageByteOffset ... storage_<name> };
            next_chunk = pass_code[storage_pos:storage_pos + 2000]
            
            # Extract offset
            offset_match = re.search(
                r'(\d+),\s*//\s*threadGroupStorageByteOffset',
                next_chunk
            )
            offset = int(offset_match.group(1)) if offset_match else None
            
            # Extract logicalSize (uint3 or uint4)
            size_match = re.search(
                r'uint([34])\(([^)]+)\),\s*//\s*logicalSize',
                next_chunk
            )
            shape = size_match.group(2) if size_match else None
            
            # Extract storageSize
            stsize_match = re.search(
                r'uint[34]\(([^)]+)\),\s*//\s*storageSize',
                next_chunk
            )
            storage_size = stsize_match.group(1) if stsize_match else None
            
            # Extract tensor type (Conv2D weight, bias, etc.)
            type_match = re.search(r'const\s+(\w+[<\w\s>]*?)\s+' + re.escape(var_name) + r'\s*=', next_chunk)
            tensor_type = type_match.group(1).strip() if type_match else None
            
            # Calculate byte size from shape
            byte_size = None
            if shape:
                dims = [int(x.strip()) for x in shape.split(',')]
                # FP8 = 1 byte per element, FP16 = 2 bytes
                if 'f8' in (tensor_type or '').lower() or 'f8' in storage_type.lower() or 'Quantized' in (tensor_type or ''):
                    elem_bytes = 1
                elif 'float16' in (tensor_type or '').lower() or 'half' in (tensor_type or '').lower() or '1f<' in (tensor_type or ''):
                    elem_bytes = 2
                else:
                    elem_bytes = 1  # default FP8
                byte_size = 1
                for d in dims:
                    byte_size *= d
                byte_size *= elem_bytes
            
            results.append({
                'pass': pass_name,
                'name': var_name,
                'offset': offset,
                'shape': shape,
                'storage_size': storage_size,
                'tensor_type': tensor_type,
                'byte_size': byte_size,
            })
        
        idx += 2
    
    return results

# Parse all HLSL files
all_results = []

# Pre (encoder)
pre_path = f"{SRC}/fsr4_model_v07_fp8_no_scale_quality/pre.hlsl"
if os.path.exists(pre_path):
    all_results.extend(parse_hlsl_file(pre_path))

# Passes (main body) — use 1080p version
passes_path = f"{SRC}/fsr4_model_v07_fp8_no_scale_passes_1080.hlsl"
if os.path.exists(passes_path):
    all_results.extend(parse_hlsl_file(passes_path))

# Post (decoder)
post_path = f"{SRC}/fsr4_model_v07_fp8_no_scale_quality/post.hlsl"
if os.path.exists(post_path):
    all_results.extend(parse_hlsl_file(post_path))

# Sort by offset
all_results.sort(key=lambda x: (x.get('offset') or 0))

# Print results
print("=" * 90)
print(f"FSR 4.0.2 FP8 InitializerBuffer Offset Map")
print(f"Total tensors: {len(all_results)}")
print("=" * 90)
print(f"{'Pass':<10} {'Offset':>8} {'Size':>8} {'Shape':<20} {'Name'}")
print("-" * 90)

prev_end = 0
for r in all_results:
    off = r['offset']
    sz = r['byte_size']
    gap = off - prev_end if off is not None and prev_end else 0
    gap_str = f" (gap:{gap})" if gap > 0 and prev_end > 0 else ""
    
    # Truncate name for display
    name = r['name']
    if len(name) > 40:
        name = name[:37] + "..."
    
    print(f"  {r['pass']:<10} {off:>8} {str(sz):>8} {str(r['shape']):<20} {name}{gap_str}")
    
    if off is not None and sz is not None:
        prev_end = off + sz

print(f"\n  Total data range: 0 - {prev_end}")

# Save as JSON
out_path = "/mnt/workdrive/fsr-re/reports/v402_initializer_offsets.json"
with open(out_path, 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
