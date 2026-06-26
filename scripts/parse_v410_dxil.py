#!/usr/bin/env python3
"""
Parse 4.1.0 DXIL LLVM IR to find InitializerBuffer offsets.
Confirm tensor structure matches 4.0.2 or identify differences.

Usage:
    python parse_v410_dxil.py [--dxil-dir DIR] [--output FILE]
"""

import os, re, json, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Parse 4.1.0 DXIL for InitializerBuffer structure")
    parser.add_argument("--dxil-dir", default=str(Path(__file__).resolve().parents[1] / "build/llvm_ir/4_1_0"),
        help="Directory containing DXIL LLVM IR files")
    parser.add_argument("-o", "--output", default=None,
        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()



import re, os, json, glob

V410_LLVM_DIR = str(Path(__file__).resolve().parents[1] / "build/llvm_ir/4_1_0")
V402_SCHEMA = "/mnt/workdrive/fsr-re/reports/v402_initializer_offsets.json"

# Load 4.0.2 schema for comparison
with open(V402_SCHEMA) as f:
    v402_schema = json.load(f)

# Parse all .ll files for InitializerBuffer references
results = []
seen_offsets = set()

ll_files = sorted(glob.glob(f"{V410_LLVM_DIR}/blob_*.ll"))
print(f"Scanning {len(ll_files)} LLVM IR files for InitializerBuffer references...")

for ll_path in ll_files:
    with open(ll_path) as f:
        content = f.read()
    
    if "InitializerBuffer" not in content:
        continue
    
    blob_name = os.path.basename(ll_path)
    
    # Find all getelementptr or constant expressions with InitializerBuffer
    # DXIL pattern: @InitializerBuffer = external constant [...]
    # Then loads with byte offsets
    
    # Pattern 1: Direct offset constants used with InitializerBuffer
    # In LLVM IR: getelementptr i8, i8* %InitializerBuffer.load, i32 <OFFSET>
    geps = re.findall(
        r'getelementptr\s+\w+,\s+\w+\*\s+%?\w*[Ii]nitializer\w*,\s+i32\s+(\d+)',
        content
    )
    
    # Pattern 2: Constant offsets in store/load patterns
    # In DXIL: call %dx.types.Handle @dx.op.createHandle(i32 57, ...) with InitializerBuffer
    # Then: call @dx.op.bufferLoad with row/col offsets
    
    # Pattern 3: Look for the buffer binding - t1 means InitializerBuffer
    # !{i32 0, %"class.ID3D11Resource"* %InitializerBuffer, ..."t1", i32 1, ...}
    
    # Extract the HLSL function name (entry point) if present
    entry_match = re.search(r'define\s+void\s+@(\w+)', content)
    entry = entry_match.group(1) if entry_match else blob_name
    
    # Find all integer constants that could be byte offsets into InitializerBuffer
    # In ML2Code-generated shaders, offsets appear as constant i32 values in getelementptr
    
    # More aggressive: find all i32 constants near InitializerBuffer mentions
    offsets_found = set()
    
    # Method: find all contexts where InitializerBuffer is loaded, then track offset math
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'InitializerBuffer' in line:
            # Look at surrounding lines for offset values
            context = '\n'.join(lines[max(0,i-2):i+5])
            
            # Direct gep offset
            m = re.search(r'getelementptr.*InitializerBuffer.*?i32\s+(\d+)', context)
            if m:
                offsets_found.add(int(m.group(1)))
            
            # Constant in add/mul that looks like a byte offset (>100)
            m = re.findall(r'i32\s+(\d{3,})', context)
            for val in m:
                v = int(val)
                if v > 100 and v < 200000:
                    offsets_found.add(v)
    
    if offsets_found:
        for off in sorted(offsets_found):
            if off not in seen_offsets:
                seen_offsets.add(off)
                results.append({
                    'file': blob_name,
                    'entry': entry,
                    'offset': off,
                })

print(f"\nFound {len(results)} unique offset references across {len(ll_files)} files")

# Sort by offset
results.sort(key=lambda x: x['offset'])

# Compare against 4.0.2 schema
v402_offsets = set(t['offset'] for t in v402_schema if t['offset'] is not None)

print(f"\n4.0.2 schema has {len(v402_offsets)} unique offsets")
print(f"4.1.0 DXIL has {len(seen_offsets)} unique offsets")

# Find new offsets in 4.1.0
new_offsets = seen_offsets - v402_offsets
missing_offsets = v402_offsets - seen_offsets

if new_offsets:
    print(f"\n### NEW offsets in 4.1.0 (not in 4.0.2): ###")
    for off in sorted(new_offsets):
        print(f"  {off}")
else:
    print(f"\n  No new offsets — schema is identical!")

if missing_offsets:
    print(f"\n### Missing offsets (in 4.0.2 but not found in 4.1.0 DXIL): ###")
    for off in sorted(missing_offsets):
        # Find the 4.0.2 tensor name
        names = [t['name'] for t in v402_schema if t['offset'] == off]
        name = names[0] if names else "?"
        print(f"  {off}: {name}")
    print(f"  (These may use indirect addressing in the compiled DXIL)")

# Check if the extra 888 bytes (offset 130088) is referenced
if 130088 in seen_offsets:
    print(f"\n  *** Offset 130088 (extra 888 bytes) IS referenced in 4.1.0! ***")
elif any(o >= 130088 for o in seen_offsets):
    print(f"\n  Offsets >= 130088 found: {[o for o in sorted(seen_offsets) if o >= 130088]}")
else:
    print(f"\n  No offsets >= 130088 found in DXIL scan")
    print(f"  Highest offset found: {max(seen_offsets)}")
    print(f"  The extra 888 bytes may be accessed via runtime-computed offsets")

# Print full offset table
print(f"\n### Full 4.1.0 Offset Map (sorted) ###")
print(f"  {'Offset':>8}  {'File':<18}  Entry")
print(f"  {'-'*8}  {'-'*18}  {'-'*50}")
for r in results:
    print(f"  {r['offset']:>8}  {r['file']:<18}  {r['entry'][:50]}")


if __name__ == "__main__":
    main()
