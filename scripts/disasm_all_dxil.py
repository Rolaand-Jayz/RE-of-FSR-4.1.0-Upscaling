#!/usr/bin/env python3
"""
Extract LLVM bitcode from DXIL chunk files and disassemble using opt.
Works around LLVM 22's strict data layout validation by using opt --data-layout.

Usage:
    python3 scripts/disasm_all_dxil.py [--force] [--version 4_1_0|4_0_2]
"""
import struct, subprocess, os, sys, re, glob, argparse, tempfile

BC_MAGIC = b'\x42\x43\xc0\xde'
DXIL_LAYOUT = 'e-m:e-p:32:32-i1:32-i8:8-i16:16-i32:32-i64:64-f16:16-f32:32-f64:64-n8:16:32:64'

def extract_bitcode(dxil_path):
    """Extract LLVM bitcode from a DXIL chunk file."""
    with open(dxil_path, 'rb') as f:
        data = f.read()
    bc_pos = data.find(BC_MAGIC)
    if bc_pos < 0:
        return None
    return data[bc_pos:]

def disassemble_bitcode(bc_data, ll_path):
    """Disassemble LLVM bitcode using opt --data-layout to handle DXIL layouts."""
    with tempfile.NamedTemporaryFile(suffix='.bc', delete=False) as tf:
        tf.write(bc_data)
        bc_path = tf.name
    
    try:
        # Use opt -S with DXIL data layout override
        # This works around LLVM 22 rejecting i8:32 in DXIL bitcode
        r = subprocess.run(
            ['opt', f'--data-layout={DXIL_LAYOUT}', '-S', bc_path, '-o', ll_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return False, f'opt failed: {r.stderr.strip()[:200]}'
        
        if not os.path.exists(ll_path) or os.path.getsize(ll_path) == 0:
            return False, 'empty output'
        
        # Validate output looks like LLVM IR
        with open(ll_path) as f:
            content = f.read(200)
        if 'ModuleID' not in content and 'target' not in content:
            return False, 'invalid IR output'
        
        return True, None
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    finally:
        if os.path.exists(bc_path):
            os.unlink(bc_path)

def main():
    parser = argparse.ArgumentParser(description='Disassemble DXIL blobs to LLVM IR')
    parser.add_argument('--force', action='store_true', help='Re-extract even existing files')
    parser.add_argument('--version', choices=['4_1_0', '4_0_2', 'both'], default='both')
    args = parser.parse_args()
    
    base = '/mnt/workdrive/fsr-re/build'
    versions = ['4_1_0', '4_0_2'] if args.version == 'both' else [args.version]
    
    for version in versions:
        dxil_dir = os.path.join(base, version, 'dxil')
        llvm_dir = os.path.join(base, 'llvm_ir', version)
        
        if not os.path.isdir(dxil_dir):
            print(f'SKIP: {dxil_dir} not found')
            continue
        
        os.makedirs(llvm_dir, exist_ok=True)
        
        dxil_files = sorted(glob.glob(os.path.join(dxil_dir, 'dxil_*.dxil')))
        print(f'\n=== {version}: {len(dxil_files)} DXIL files ===')
        
        stats = {'success': 0, 'existing': 0, 'failed': 0, 'no_bc': 0}
        failures = []
        
        for i, dxil_path in enumerate(dxil_files):
            basename = os.path.basename(dxil_path)
            m = re.match(r'dxil_(\d+)_', basename)
            if not m:
                continue
            idx = int(m.group(1))
            ll_path = os.path.join(llvm_dir, f'blob_{idx:04d}.ll')
            
            # Skip if already exists and non-empty (unless --force)
            if not args.force and os.path.exists(ll_path) and os.path.getsize(ll_path) > 0:
                stats['existing'] += 1
                continue
            
            bc_data = extract_bitcode(dxil_path)
            if bc_data is None:
                stats['no_bc'] += 1
                failures.append((basename, 'no BC magic'))
                continue
            
            ok, err = disassemble_bitcode(bc_data, ll_path)
            if ok:
                stats['success'] += 1
                sz = os.path.getsize(ll_path)
                if stats['success'] <= 5 or stats['success'] % 50 == 0:
                    print(f'  OK: {basename} -> blob_{idx:04d}.ll ({sz:,} bytes)')
            else:
                stats['failed'] += 1
                failures.append((basename, err))
        
        total_ll = len(glob.glob(os.path.join(llvm_dir, 'blob_*.ll')))
        print(f'\n  Results: {stats["success"]} new, {stats["existing"]} existing, '
              f'{stats["failed"]} failed, {stats["no_bc"]} no BC, {total_ll} total LLVM IR files')
        
        if failures and stats['failed'] <= 10:
            print(f'  Failures:')
            for name, err in failures[:10]:
                print(f'    {name}: {err}')

if __name__ == '__main__':
    main()
