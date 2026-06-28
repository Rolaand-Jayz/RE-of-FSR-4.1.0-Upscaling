#!/usr/bin/env python3
"""
Extract weight blobs from the FSR 4.1.0 DLL using pefile.

Locates the InitializerBuffer data via LEA instruction analysis in the
CreateContext function, resolves RVAs to file offsets, and writes each
quality preset's weight blob to disk.

Usage:
    python extract_blobs.py [--dll FILE] [--output-dir DIR]

Requires: pefile (pip install pefile)
"""

import os, struct, hashlib, argparse, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Extract weight blobs from FSR DLL")
    parser.add_argument("--dll", default=str(Path(__file__).resolve().parents[1] / "build/dll_v410.dll"),
        help="Path to the FSR DLL")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1] / "extracted/v410_initializers"),
        help="Output directory for extracted blobs")
    args = parser.parse_args()


import struct
import os
import json
import hashlib

DLL_V410 = os.path.expanduser("${FSR410_DLL:-/path/to/amd_fidelityfx_upscaler_dx12.dll}")
DLL_V402 = os.path.expanduser("${FSR402_DLL:-/path/to/amd_fidelityfx_upscaler_dx12.dll}")
BUILD_DIR = "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))/build"

DXBC_MAGIC = b'DXBC'

def extract_dxbc_blobs(dll_path, label):
    """Extract all DXBC blobs and their DXIL chunks."""
    with open(dll_path, 'rb') as f:
        data = f.read()
    
    blobs = []
    pos = 0
    idx = 0
    while True:
        pos = data.find(DXBC_MAGIC, pos)
        if pos == -1:
            break
        
        if pos + 32 > len(data):
            pos += 4
            continue
        
        total_size = struct.unpack_from('<I', data, pos + 24)[0]
        chunk_count = struct.unpack_from('<I', data, pos + 28)[0]
        
        # Sanity check
        if total_size > 5_000_000 or total_size < 64 or chunk_count > 100:
            pos += 4
            continue
        
        # Extract full blob
        blob_data = data[pos:pos+total_size]
        
        # Compute a hash for deduplication
        blob_hash = hashlib.sha256(blob_data).hexdigest()[:16]
        
        # Parse chunks to find DXIL
        dxil_data = None
        dxil_offset = None
        chunks_info = []
        chunk_offsets_start = 32
        for i in range(chunk_count):
            co = struct.unpack_from('<I', data, pos + chunk_offsets_start + i*4)[0]
            abs_off = pos + co
            if abs_off + 8 > len(data):
                continue
            chunk_magic = data[abs_off:abs_off+4]
            chunk_size = struct.unpack_from('<I', data, abs_off+4)[0]
            chunks_info.append({
                'magic': chunk_magic.decode('ascii', errors='replace'),
                'offset': abs_off,
                'size': chunk_size,
            })
            if chunk_magic == b'DXIL':
                dxil_data = data[abs_off:abs_off+chunk_size+8]
                dxil_offset = abs_off
        
        blobs.append({
            'index': idx,
            'offset': pos,
            'size': total_size,
            'hash': blob_hash,
            'chunk_count': chunk_count,
            'chunks': chunks_info,
            'dxil_size': len(dxil_data) if dxil_data else 0,
        })
        
        idx += 1
        pos += total_size  # jump past blob
    
    return blobs, data


def classify_blob(blob):
    """Try to classify a blob by its size and structure."""
    size = blob['size']
    chunk_types = set(c['magic'] for c in blob['chunks'])
    has_ildn = 'ILDN' in chunk_types
    has_rts0 = 'RTS0' in chunk_types
    
    # Classification based on size ranges from the analysis
    if size > 250_000:
        label = "LARGE_PASS"
    elif size > 100_000:
        label = "MEDIUM_PASS"
    elif size > 40_000:
        label = "MAIN_PASS"
    elif size > 15_000:
        label = "SMALL_PASS"
    elif size > 5_000:
        label = "TINY_PASS"
    else:
        label = "UTILITY"
    
    flags = []
    if has_ildn:
        flags.append("ILDN")
    if has_rts0:
        flags.append("RTS0")
    
    return f"{label}{'_'.join([''] + flags) if flags else ''}"


def main():
    os.makedirs(BUILD_DIR, exist_ok=True)
    
    results = {}
    
    for dll_path, label in [(DLL_V410, "4.1.0"), (DLL_V402, "4.0.2")]:
        if not os.path.exists(dll_path):
            print(f"WARNING: {label} not found at {dll_path}")
            continue
        
        print(f"\nExtracting {label}...")
        blobs, raw_data = extract_dxbc_blobs(dll_path, label)
        
        # Create output directory
        out_dir = os.path.join(BUILD_DIR, label.replace('.', '_'))
        dxil_dir = os.path.join(out_dir, "dxil")
        os.makedirs(dxil_dir, exist_ok=True)
        
        # Classify and save
        size_groups = {}
        for blob in blobs:
            cls = classify_blob(blob)
            if cls not in size_groups:
                size_groups[cls] = 0
            size_groups[cls] += 1
            
            # Save full DXBC blob
            blob_path = os.path.join(out_dir, f"blob_{blob['index']:04d}_{blob['size']}b.dxbc")
            with open(blob_path, 'wb') as f:
                f.write(raw_data[blob['offset']:blob['offset']+blob['size']])
            
            # Save DXIL chunk separately
            if blob['dxil_size'] > 0:
                dxil_chunk = None
                for c in blob['chunks']:
                    if c['magic'] == 'DXIL':
                        dxil_chunk = c
                        break
                if dxil_chunk:
                    dxil_path = os.path.join(dxil_dir, f"dxil_{blob['index']:04d}_{dxil_chunk['size']}b.dxil")
                    with open(dxil_path, 'wb') as f:
                        f.write(raw_data[dxil_chunk['offset']:dxil_chunk['offset']+dxil_chunk['size']+8])
        
        results[label] = {
            'total_blobs': len(blobs),
            'size_groups': size_groups,
            'blobs': blobs,
        }
        
        print(f"  Total blobs: {len(blobs)}")
        print(f"  Classification:")
        for cls, count in sorted(size_groups.items()):
            print(f"    {cls}: {count}")
    
    # Compare blob sizes between versions
    if '4.0.2' in results and '4.1.0' in results:
        print(f"\n{'='*60}")
        print("BLOB SIZE COMPARISON")
        print(f"{'='*60}")
        
        sizes_402 = sorted([(b['size'], b['index'], b['hash']) for b in results['4.0.2']['blobs']])
        sizes_410 = sorted([(b['size'], b['index'], b['hash']) for b in results['4.1.0']['blobs']])
        
        print(f"\n4.0.2 blob sizes (sorted): {', '.join(f'{s[0]}' for s in sizes_402[:20])}...")
        print(f"4.1.0 blob sizes (sorted): {', '.join(f'{s[0]}' for s in sizes_410[:20])}...")
        
        # Find size matches (same blob size likely = same shader)
        sizes_402_set = set(s[0] for s in sizes_402)
        sizes_410_set = set(s[0] for s in sizes_410)
        
        common = sizes_402_set & sizes_410_set
        only_402 = sizes_402_set - sizes_410_set
        only_410 = sizes_410_set - sizes_402_set
        
        print(f"\nCommon blob sizes: {len(common)}")
        print(f"Only in 4.0.2: {len(only_402)} — {sorted(only_402)}")
        print(f"Only in 4.1.0: {len(only_410)} — {sorted(only_410)}")
    
    # Save index
    index_path = os.path.join(BUILD_DIR, "blob_index.json")
    # Trim blobs for JSON (remove chunk details)
    for label in results:
        for b in results[label]['blobs']:
            b['chunks'] = [{'magic': c['magic'], 'size': c['size']} for c in b['chunks']]
    
    with open(index_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nBlob index saved to {index_path}")


if __name__ == '__main__':
    main()
