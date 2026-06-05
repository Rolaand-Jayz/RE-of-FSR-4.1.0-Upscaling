#!/usr/bin/env python3
"""
Phase 3: PE Analysis of FSR 4.1.0 DLL.
Walk sections, exports, resources. Search for DXIL/DXBC blobs.

Usage:
    python dll_analysis.py [--dll FILE] [--output FILE]
"""

import os, json, argparse, sys

def main():
    parser = argparse.ArgumentParser(description="Analyze FSR DLL PE structure")
    parser.add_argument("--dll", default="/mnt/workdrive/fsr-re/build/dll_v410.dll",
        help="Path to the FSR DLL")
    parser.add_argument("-o", "--output", default=None,
        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()


import pefile
import struct
import os
import json
import sys

DLL_V410 = os.path.expanduser("~/Desktop/temporal forge/vendor/fidelityfx-sdk-v220/Kits/FidelityFX/signedbin/amd_fidelityfx_upscaler_dx12.dll")
DLL_V402 = os.path.expanduser("~/Desktop/temporal forge/vendor/fidelityfx-sdk-mit-original/Kits/FidelityFX/signedbin/amd_fidelityfx_upscaler_dx12.dll")
OUTPUT = "/mnt/workdrive/fsr-re/reports/dll_analysis.json"

# DXBC magic bytes (DirectX Bytecode header)
DXBC_MAGIC = b'DXBC'
# DXIL magic (appears after DXBC header in some cases)
DXIL_MAGIC = b'DXIL'

def find_all_dxbc(data):
    """Find all DXBC blob offsets in raw data."""
    offsets = []
    pos = 0
    while True:
        pos = data.find(DXBC_MAGIC, pos)
        if pos == -1:
            break
        offsets.append(pos)
        pos += 4
    return offsets

def parse_dxbc_header(data, offset):
    """Parse a DXBC blob header at the given offset."""
    if offset + 32 > len(data):
        return None
    
    magic = data[offset:offset+4]
    if magic != DXBC_MAGIC:
        return None
    
    # DXBC header structure
    checksum = data[offset+4:offset+20].hex()
    version = struct.unpack_from('<I', data, offset+20)[0]
    total_size = struct.unpack_from('<I', data, offset+24)[0]
    chunk_count = struct.unpack_from('<I', data, offset+28)[0]
    
    # Read chunk offsets
    chunks = []
    chunk_offsets_start = offset + 32
    for i in range(min(chunk_count, 64)):  # safety limit
        co = struct.unpack_from('<I', data, chunk_offsets_start + i*4)[0]
        abs_offset = offset + co
        
        # Read chunk header
        if abs_offset + 8 <= len(data):
            chunk_magic = data[abs_offset:abs_offset+4]
            chunk_size = struct.unpack_from('<I', data, abs_offset+4)[0]
            chunks.append({
                'offset_from_blob': co,
                'absolute_offset': abs_offset,
                'magic': chunk_magic.decode('ascii', errors='replace'),
                'size': chunk_size,
            })
    
    return {
        'offset': offset,
        'checksum': checksum,
        'version': version,
        'total_size': total_size,
        'chunk_count': chunk_count,
        'chunks': chunks,
    }

def analyze_dll(dll_path, label):
    """Full PE analysis of a DLL."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {label}")
    print(f"Path: {dll_path}")
    print(f"Size: {os.path.getsize(dll_path):,} bytes")
    print(f"{'='*60}")
    
    pe = pefile.PE(dll_path)
    result = {
        'label': label,
        'path': dll_path,
        'file_size': os.path.getsize(dll_path),
        'sections': [],
        'exports': [],
        'resources': {},
        'dxbc_blobs': [],
    }
    
    # Sections
    print(f"\n--- Sections ---")
    for section in pe.sections:
        name = section.Name.decode().rstrip('\x00')
        entry = {
            'name': name,
            'virtual_address': hex(section.VirtualAddress),
            'virtual_size': section.Misc_VirtualSize,
            'raw_offset': hex(section.PointerToRawData),
            'raw_size': section.SizeOfRawData,
            'entropy': section.get_entropy(),
        }
        result['sections'].append(entry)
        print(f"  {name:8s} VA={hex(section.VirtualAddress)} "
              f"RawOff={hex(section.PointerToRawData)} "
              f"Size={section.SizeOfRawData:,} "
              f"Entropy={section.get_entropy():.2f}")
    
    # Exports
    print(f"\n--- Exports ---")
    if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if exp.name:
                name = exp.name.decode()
                result['exports'].append({
                    'name': name,
                    'ordinal': exp.ordinal,
                    'address': hex(exp.address),
                })
                print(f"  {name}: {hex(exp.address)}")
    else:
        print("  No exports found")
    
    # Resources (simplified walk — just enumerate types and sizes)
    print(f"\n--- Resources ---")
    if hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE'):
        for res_type in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            type_name = pefile.RESOURCE_TYPE.get(res_type.id, f"Unknown({res_type.id})")
            entries = []
            def collect_leaf(node, depth=0):
                if hasattr(node, 'directory') and node.directory:
                    for e in node.directory.entries:
                        collect_leaf(e, depth+1)
                elif hasattr(node, 'data') and node.data:
                    d = node.data
                    entries.append({
                        'lang': getattr(d, 'lang', None),
                        'sublang': getattr(d, 'sublang', None),
                        'rva': hex(d.struct.OffsetToData) if hasattr(d, 'struct') else None,
                        'size': d.struct.Size if hasattr(d, 'struct') else None,
                    })
            collect_leaf(res_type)
            total_size = sum(e.get('size', 0) or 0 for e in entries)
            print(f"  Type: {type_name} (ID={res_type.id}): {len(entries)} entries, {total_size:,} bytes total")
            result['resources'][type_name] = entries
    else:
        print("  No resource directory")
    
    # Find DXBC blobs by scanning full file
    print(f"\n--- DXBC Blob Scan ---")
    with open(dll_path, 'rb') as f:
        data = f.read()
    
    dxbc_offsets = find_all_dxbc(data)
    print(f"  Found {len(dxbc_offsets)} DXBC blobs")
    
    for off in dxbc_offsets:
        blob = parse_dxbc_header(data, off)
        if blob:
            # Summarize chunks
            chunk_types = {}
            for c in blob['chunks']:
                m = c['magic']
                if m not in chunk_types:
                    chunk_types[m] = 0
                chunk_types[m] += 1
            
            blob['chunk_types'] = chunk_types
            result['dxbc_blobs'].append(blob)
            
            print(f"  Blob at 0x{off:x}: size={blob['total_size']:,}, "
                  f"chunks={blob['chunk_count']}, types={chunk_types}")
            
            # Show detail for first few
            if len(result['dxbc_blobs']) <= 5:
                for c in blob['chunks'][:10]:
                    print(f"    Chunk: magic='{c['magic']}' size={c['size']} at 0x{c['absolute_offset']:x}")
                if len(blob['chunks']) > 10:
                    print(f"    ... and {len(blob['chunks'])-10} more chunks")
    
    # Section-specific DXBC search (high entropy sections likely contain shaders)
    print(f"\n--- High-Entropy Section Scan ---")
    for section in pe.sections:
        if section.get_entropy() > 7.0:
            name = section.Name.decode().rstrip('\x00')
            section_data = section.get_data()
            section_dxbc = find_all_dxbc(section_data)
            if section_dxbc:
                print(f"  {name}: {len(section_dxbc)} DXBC blobs (offsets within section: {[hex(o) for o in section_dxbc[:5]]})")
    
    # Summary stats
    total_dxbc_bytes = sum(b['total_size'] for b in result['dxbc_blobs'])
    print(f"\n--- Summary ---")
    print(f"  Total DXBC blob count: {len(result['dxbc_blobs'])}")
    print(f"  Total DXBC data: {total_dxbc_bytes:,} bytes ({total_dxbc_bytes/1024/1024:.1f} MB)")
    print(f"  Non-DXBC DLL size: {result['file_size'] - total_dxbc_bytes:,} bytes")
    
    pe.close()
    return result


def main():
    results = {}
    
    # Analyze both DLLs
    for dll_path, label in [(DLL_V410, "4.1.0"), (DLL_V402, "4.0.2")]:
        if os.path.exists(dll_path):
            results[label] = analyze_dll(dll_path, label)
        else:
            print(f"WARNING: {label} DLL not found at {dll_path}")
    
    # Compare
    if '4.0.2' in results and '4.1.0' in results:
        print(f"\n{'='*60}")
        print("COMPARISON: 4.0.2 vs 4.1.0")
        print(f"{'='*60}")
        v402 = results['4.0.2']
        v410 = results['4.1.0']
        
        print(f"  File size: {v402['file_size']:,} → {v410['file_size']:,} (Δ={v410['file_size']-v402['file_size']:,})")
        print(f"  DXBC blobs: {len(v402['dxbc_blobs'])} → {len(v410['dxbc_blobs'])}")
        print(f"  Sections: {len(v402['sections'])} → {len(v410['sections'])}")
        print(f"  Exports: {len(v402['exports'])} → {len(v410['exports'])}")
        
        # Compare export names
        v402_exports = set(e['name'] for e in v402['exports'])
        v410_exports = set(e['name'] for e in v410['exports'])
        new_exports = v410_exports - v402_exports
        removed_exports = v402_exports - v410_exports
        if new_exports:
            print(f"  New exports: {new_exports}")
        if removed_exports:
            print(f"  Removed exports: {removed_exports}")
        if not new_exports and not removed_exports:
            print(f"  Export names: IDENTICAL")
    
    # Save
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull analysis saved to {OUTPUT}")


if __name__ == '__main__':
    main()
