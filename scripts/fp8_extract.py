#!/usr/bin/env python3
"""
FSR 4.1.0 FP8 Initializer Extraction.

Extracts FP8 quantized weight data from InitializerBuffer blobs and
analyzes the quantization scheme (codebook distribution, unique values).

Usage:
    python fp8_extract.py [--blob FILE] [--preset NAME] [--output FILE]
"""

import os, struct, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Extract and analyze FP8 weights from blob")
    parser.add_argument("--blob", default=None,
        help="Path to weight blob file")
    parser.add_argument("--preset", default="quality",
        help="Quality preset name (for auto-path resolution)")
    parser.add_argument("-o", "--output", default=None,
        help="Output file path (default: stdout)")
    args = parser.parse_args()


import struct
import os
import sys
import json

DLL_402 = '/mnt/workdrive/fsr-re/build/dll_v402.dll'
DLL_410 = '/mnt/workdrive/fsr-re/build/dll_v410.dll'
SRC_BASE = '/path/to/sdk/source'
REPORT_DIR = '/mnt/workdrive/fsr-re/reports'
EXTRACT_DIR = '/mnt/workdrive/fsr-re/extracted/fp8_initializers'
LOG = '/mnt/workdrive/fsr-re/reports/progress.log'

os.makedirs(EXTRACT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def log(msg):
    with open(LOG, 'a') as f:
        f.write(msg + '\n')
    print(msg)

# Step 1: Verify 4.0.2 baseline
log("=== Step 1: Verify 4.0.2 baseline ===")

variants_402 = {
    'fp8_no_scale_native': 0x9d5640,
    'fp8_no_scale_quality': 0x9f5280,
    'fp8_no_scale_balanced': 0xa14ec0,
    'fp8_no_scale_drs': 0xa54740,
    'fp8_no_scale_performance': 0xa34b00,
    'fp8_no_scale_ultraperf': 0xa74380,
}

BLOB_SIZE_402 = 130088

with open(DLL_402, 'rb') as f:
    dll_402 = f.read()

for name, offset in variants_402.items():
    blob = dll_402[offset:offset + BLOB_SIZE_402]
    src_path = f'{SRC_BASE}/fsr4_model_v07_{name}/initializers.bin'
    with open(src_path, 'rb') as f:
        src = f.read()
    match = blob == src
    log(f"  4.0.2 {name}: {'MATCH' if match else 'MISMATCH'} at 0x{offset:06x}")

# Step 2: Analyze FP8 byte distribution signature
log("\n=== Step 2: FP8 byte distribution analysis ===")

with open(f'{SRC_BASE}/fsr4_model_v07_fp8_no_scale_quality/initializers.bin', 'rb') as f:
    fp8_sample = f.read()

from collections import Counter
fp8_freq = Counter(fp8_sample)
fp8_total = len(fp8_sample)

# FP8 E4M3: values are 0x00-0xFF but with specific distribution
# Top bytes, high byte frequency, low byte frequency
high_bytes = sum(1 for b in fp8_sample if b >= 0x80)
low_bytes = sum(1 for b in fp8_sample if b < 0x80)
zero_bytes = sum(1 for b in fp8_sample if b == 0)

log(f"  FP8 sample: {fp8_total:,} bytes")
log(f"  High bytes (>=0x80): {high_bytes:,} ({high_bytes/fp8_total*100:.1f}%)")
log(f"  Low bytes (<0x80): {low_bytes:,} ({low_bytes/fp8_total*100:.1f}%)")
log(f"  Zero bytes: {zero_bytes:,} ({zero_bytes/fp8_total*100:.1f}%)")

# Step 3: Find FP8 blobs in 4.1.0 by scanning for matching distribution
log("\n=== Step 3: Scanning 4.1.0 DLL for FP8 initializer blobs ===")

with open(DLL_410, 'rb') as f:
    dll_410 = f.read()

# Strategy: slide a 130KB window across the DLL, compute FP8-likeness score
# FP8 data should have: ~50/50 high/low byte split, very few zeros (<3%)
# DXBC blobs have a different distribution (lots of small values, structured headers)

CHUNK_SIZE = 130088  # Start with 4.0.2 size
STEP = 4096  # Slide in 4KB steps for speed
dll_len = len(dll_410)

candidates = []

# We'll scan the .rdata section primarily
# But for thoroughness, scan the whole DLL
log(f"  DLL size: {dll_len:,} bytes")
log(f"  Scanning with {CHUNK_SIZE}-byte windows, step {STEP}...")

i = 0
count = 0
while i + CHUNK_SIZE <= dll_len:
    chunk = dll_410[i:i + CHUNK_SIZE]
    
    # Quick filter: check zero ratio
    zeros = chunk.count(0)
    zero_pct = zeros / CHUNK_SIZE
    
    # FP8 data has <2% zeros
    if zero_pct < 0.02:
        # Check high/low byte balance
        highs = sum(1 for b in chunk if b >= 0x80)
        high_pct = highs / CHUNK_SIZE
        
        # FP8 should be roughly 40-60% high bytes
        if 0.35 < high_pct < 0.65:
            # This is a strong FP8 candidate
            # Compute a similarity score against the known FP8 distribution
            chunk_freq = Counter(chunk)
            
            # Check entropy (FP8 has moderate entropy, not max)
            import math
            entropy = -sum((c/CHUNK_SIZE) * math.log2(c/CHUNK_SIZE) for c in chunk_freq.values() if c > 0)
            
            candidates.append({
                'offset': i,
                'zero_pct': zero_pct,
                'high_pct': high_pct,
                'entropy': entropy,
                'unique_bytes': len(chunk_freq),
            })
    
    i += STEP
    count += 1
    if count % 5000 == 0:
        pass  # Silent progress

log(f"  Scanned {count:,} windows, found {len(candidates)} FP8 candidates")

# Sort by similarity to expected FP8 profile
# Expected: zero_pct ~1%, high_pct ~50%, entropy ~7.5, unique_bytes ~256
for c in candidates:
    c['score'] = abs(c['zero_pct'] - 0.01) + abs(c['high_pct'] - 0.50)

candidates.sort(key=lambda x: x['score'])

# Report top candidates
log(f"\nTop 20 FP8 candidates:")
for c in candidates[:20]:
    log(f"  0x{c['offset']:06x}: zeros={c['zero_pct']*100:.2f}%, highs={c['high_pct']*100:.2f}%, "
        f"entropy={c['entropy']:.2f}, unique={c['unique_bytes']}, score={c['score']:.4f}")

# Step 4: Group nearby candidates into blobs
log("\n=== Step 4: Grouping candidates into blobs ===")

# Candidates within 4KB of each other are likely the same blob
if candidates:
    groups = []
    current_group = [candidates[0]]
    
    for c in sorted(candidates, key=lambda x: x['offset']):
        if c['offset'] - current_group[-1]['offset'] < STEP * 2:
            current_group.append(c)
        else:
            groups.append(current_group)
            current_group = [c]
    groups.append(current_group)
    
    log(f"  Found {len(groups)} candidate groups")
    
    blobs = []
    for g in groups:
        start = g[0]['offset']
        end = max(c['offset'] for c in g) + CHUNK_SIZE
        best_score = min(c['score'] for c in g)
        blobs.append({
            'start': start,
            'end': end,
            'size': end - start,
            'best_score': best_score,
            'candidates': len(g),
        })
    
    blobs.sort(key=lambda x: x['best_score'])
    
    log(f"\nTop blob groups (sorted by FP8 similarity):")
    for b in blobs[:20]:
        log(f"  0x{b['start']:06x}-0x{b['end']:06x}: {b['size']:,} bytes, "
            f"score={b['best_score']:.4f}, candidates={b['candidates']}")
    
    # Step 5: Extract top candidates
    log("\n=== Step 5: Extracting FP8 initializer candidates ===")
    
    # Look for blobs that are close to 130KB
    fp8_blobs = []
    for b in blobs:
        if b['best_score'] < 0.1 and 120000 < b['size'] < 150000:
            fp8_blobs.append(b)
    
    log(f"  Found {len(fp8_blobs)} FP8-like blobs (120-150KB, score<0.1)")
    
    for i, b in enumerate(fp8_blobs):
        blob_data = dll_410[b['start']:b['end']]
        s = b['start']
        sz = b['size']
        out_path = f'{EXTRACT_DIR}/v410_candidate_{i:02d}_0x{s:06x}_{sz}b.bin'
        with open(out_path, 'wb') as f:
            f.write(blob_data)
        log(f"  Extracted candidate {i}: 0x{b['start']:06x}, {b['size']:,} bytes -> {out_path}")
    
    # Save metadata
    with open(f'{REPORT_DIR}/fp8_candidates_v410.json', 'w') as f:
        json.dump({
            'blobs': fp8_blobs,
            'all_groups': [{'start': b['start'], 'end': b['end'], 'size': b['size'], 
                           'score': b['best_score']} for b in blobs[:50]],
        }, f, indent=2)

# Step 6: Also try exact-size search
log("\n=== Step 6: Exact 130,088-byte scan ===")

# Try every possible 130,088-byte window
# That's too many - use 256-byte steps
best_exact = None
best_exact_score = 999

for offset in range(0, dll_len - BLOB_SIZE_402, 256):
    chunk = dll_410[offset:offset + BLOB_SIZE_402]
    zeros = chunk.count(0)
    zero_pct = zeros / BLOB_SIZE_402
    if zero_pct < 0.02:
        highs = sum(1 for b in chunk if b >= 0x80)
        high_pct = highs / BLOB_SIZE_402
        if 0.35 < high_pct < 0.65:
            score = abs(zero_pct - 0.01) + abs(high_pct - 0.50)
            if score < best_exact_score:
                best_exact_score = score
                best_exact = offset

if best_exact:
    log(f"  Best 130KB match at 0x{best_exact:06x} (score={best_exact_score:.4f})")
    # Check nearby for more blobs
    log(f"  Checking for additional blobs near 0x{best_exact:06x}...")
    for delta in range(BLOB_SIZE_402, BLOB_SIZE_402 + 10000, 256):
        offset = best_exact + delta
        if offset + BLOB_SIZE_402 <= dll_len:
            chunk = dll_410[offset:offset + BLOB_SIZE_402]
            zeros = chunk.count(0)
            zero_pct = zeros / BLOB_SIZE_402
            if zero_pct < 0.02:
                highs = sum(1 for b in chunk if b >= 0x80)
                high_pct = highs / BLOB_SIZE_402
                if 0.35 < high_pct < 0.65:
                    log(f"    Found at 0x{offset:06x} (delta=+{delta}, zeros={zero_pct*100:.2f}%, highs={high_pct*100:.2f}%)")

log("\n=== Done ===")


if __name__ == "__main__":
    main()
