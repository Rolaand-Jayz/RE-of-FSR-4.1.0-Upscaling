#!/usr/bin/env python3
"""Static RE closure: plausibility-check tensor offsets against the 4.1.0 blob and extract HLSL-side operator/layout artifacts."""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
from pathlib import Path


def repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def fp16_to_float(raw: int) -> float:
    sign = (raw >> 15) & 1
    exp = (raw >> 10) & 0x1F
    mant = raw & 0x3FF
    if exp == 0:
        return (-1) ** sign * mant * (2 ** -24) if mant else 0.0
    if exp == 31:
        return float('inf') if not mant else float('nan')
    return (-1) ** sign * (1 + mant / 1024.0) * (2 ** (exp - 15))


def parse_args() -> argparse.Namespace:
    repo_root_default = Path(__file__).resolve().parents[1]
    sdk_root_default = repo_root_default.parent / 'fsr4-sdk-402-source'
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root', type=Path, default=repo_root_default)
    ap.add_argument('--sdk-root', type=Path, default=sdk_root_default)
    ap.add_argument('--out', type=Path, default=None, help='Output directory, default: <repo-root>/reports')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    out_dir = args.out.resolve() if args.out else (repo_root / 'reports')
    out_dir.mkdir(parents=True, exist_ok=True)
    sdk_root = args.sdk_root.resolve()
    shader_root = sdk_root / 'Kits/FidelityFX/upscalers/fsr4/internal/shaders'

    print('=' * 70)
    print('PART 1: Tensor Offset Plausibility Check against 4.1.0 Blob')
    print('=' * 70)

    tm = json.loads((repo_root / 'spec/tensor-map.json').read_text())
    tensors = tm['tensors']
    blob_path = repo_root / 'extracted/v410_initializers/quality.bin'
    blob = blob_path.read_bytes()
    print(f'Blob size: {len(blob)} bytes')

    verification_results = []
    all_pass = True
    for i, t in enumerate(tensors):
        name = t['name']
        offset = t['offset']
        size = t['byte_size']
        ttype = t['tensor_type']
        pass_num = t['pass']
        region = blob[offset:offset + size]
        result = {
            'index': i,
            'name': name,
            'pass': pass_num,
            'offset': offset,
            'size': size,
            'type': ttype,
        }

        if 'Tensor1f' in ttype or 'bias' in name.lower():
            n_floats = size // 4
            floats = struct.unpack(f'<{n_floats}f', region[:n_floats * 4])
            finite = sum(1 for v in floats if math.isfinite(v))
            nonzero = sum(1 for v in floats if v != 0.0)
            max_abs = max(abs(v) for v in floats if math.isfinite(v))
            result.update({
                'n_values': n_floats,
                'finite': finite,
                'nonzero': nonzero,
                'max_abs': round(max_abs, 6),
                'sample': [round(v, 4) for v in floats[:5]],
                'status': 'PASS' if finite == n_floats and max_abs < 1e6 else 'FAIL',
            })
        elif 'Tensor4h_HNWC' in ttype:
            n_halves = size // 2
            halves = struct.unpack(f'<{n_halves}h', region[:n_halves * 2])
            floats = [fp16_to_float(h) for h in halves]
            finite = sum(1 for v in floats if math.isfinite(v))
            nonzero = sum(1 for v in floats if v != 0.0)
            max_abs = max(abs(v) for v in floats if math.isfinite(v))
            result.update({
                'n_values': n_halves,
                'finite': finite,
                'nonzero': nonzero,
                'max_abs': round(max_abs, 6),
                'sample': [round(v, 4) for v in floats[:5]],
                'status': 'PASS' if finite == n_halves and max_abs < 1e6 else 'FAIL',
            })
        elif 'QuantizedTensor4f8' in ttype:
            uint8_vals = list(region)
            unique = len(set(uint8_vals))
            result.update({
                'n_values': len(uint8_vals),
                'unique_values': unique,
                'sample': sorted(set(uint8_vals))[:10],
                'status': 'PASS' if unique >= 2 else 'FAIL',
            })
        else:
            result['status'] = 'UNKNOWN_TYPE'

        if result['status'] != 'PASS':
            all_pass = False
        verification_results.append(result)

    passed = sum(1 for r in verification_results if r['status'] == 'PASS')
    failed = sum(1 for r in verification_results if r['status'] == 'FAIL')
    unknown = sum(1 for r in verification_results if r['status'] == 'UNKNOWN_TYPE')
    print(f'\nPlausibility: {passed} PASS / {failed} FAIL / {unknown} UNKNOWN out of {len(tensors)}')
    print(f"Overall: {'ALL PASS' if all_pass else 'FAILURES PRESENT'}")
    print('\nSample of checked tensors:')
    for r in verification_results[:5] + verification_results[40:45]:
        if 'sample' in r:
            print(f"  [{r['index']:2d}] pass={r['pass']:2s} off={r['offset']:6d} sz={r['size']:5d} {r['status']} {r['name'][:45]:45s} sample={r['sample'][:5]}")

    tensor_report = {
        'schema_version': '1.1',
        'source': 'static_re_closure',
        'claim_scope': 'plausibility_check',
        'note': 'This validates that the 4.0.2-derived tensor map parses 4.1.0 blob regions into plausible typed values. It does not prove runtime offset use.',
        'blob_file': repo_rel(blob_path, repo_root),
        'blob_size': len(blob),
        'tensor_count': len(tensors),
        'passed': passed,
        'failed': failed,
        'unknown': unknown,
        'all_pass': all_pass,
        'method': 'Parsed the 4.1.0 quality blob using 4.0.2 HLSL-derived tensor offsets. Each region was checked only for type-appropriate plausible values, not for live runtime binding proof.',
        'results': verification_results,
    }
    vr_path = out_dir / 'tensor-offset-verification.json'
    vr_path.write_text(json.dumps(tensor_report, indent=2) + '\n')
    print(f'\nSaved: {repo_rel(vr_path, repo_root)}')

    print('\n' + '=' * 70)
    print('PART 2: MAC Arithmetic from HLSL Operator Includes')
    print('=' * 70)

    runtime_dir = shader_root / 'ml2code_runtime'
    if not runtime_dir.exists():
        alt = sdk_root / 'Kits/FidelityFX/upscalers/fsr4/ml2code_runtime'
        if alt.exists():
            runtime_dir = alt
    print(f'Runtime dir: {runtime_dir} (exists: {runtime_dir.exists()})')

    operator_files = [p for p in runtime_dir.rglob('*.hlsli')] if runtime_dir.exists() else []
    print(f'Operator include files: {len(operator_files)}')
    for f in operator_files:
        print(f'  {repo_rel(f, runtime_dir)}')

    mac_formulas = {}
    operators_to_read = [
        'Conv2D_k2s2b.hlsli',
        'ConvNextBlock.hlsli',
        'Conv2D_k3s1b.hlsli',
        'Conv2D_k4s1b.hlsli',
        'Conv2D_k5s4b.hlsli',
        'ConvTranspose2D_k2s2b.hlsli',
    ]

    for op_name in operators_to_read:
        found = False
        for fpath in operator_files:
            if fpath.name == op_name:
                content = fpath.read_text()
                muls = re.findall(r'(\w+)\s*\*=\s*(\w+)', content)
                adds = re.findall(r'(\w+)\s*\+=\s*(\w+)', content)
                fmas = re.findall(r'(\w+)\s*=\s*(\w+)\s*\*\s*(\w+)\s*\+\s*(\w+)', content)
                weight_loads = re.findall(r'(\w+\.Load|rawBufferLoad|InitializerBuffer\.\w+)[^;]+;', content)
                bias_adds = re.findall(r'bias\[|\.bias|bias\s*\+', content)
                mac_formulas[op_name] = {
                    'file': repo_rel(fpath, repo_root),
                    'lines': content.count('\n'),
                    'multiply_assign_count': len(muls),
                    'add_assign_count': len(adds),
                    'fma_count': len(fmas),
                    'weight_load_patterns': weight_loads[:5],
                    'has_bias_add': len(bias_adds) > 0,
                    'first_30_lines': content.split('\n')[:30],
                }
                print(f'\n  {op_name}: {len(content)} chars, {content.count(chr(10))} lines')
                print(f'    FMA patterns: {len(fmas)}, *= patterns: {len(muls)}, += patterns: {len(adds)}')
                found = True
                break
        if not found:
            print(f'\n  {op_name}: NOT FOUND')

    hlsl_path = shader_root / 'fsr4_model_v07_fp8_no_scale_passes_1080.hlsl'
    if not hlsl_path.exists():
        print(f'\nSKIP: HLSL source not found at {hlsl_path}')
        print('Parts 2 and 3 require the FSR 4.0.2 SDK. Skipping SDK-dependent analysis.')
        mac_path = out_dir / 'mac-arithmetic-formulas.json'
        layout_path = out_dir / 'hlsl-per-pass-layout.json'
        for p in (mac_path, layout_path):
            p.write_text(json.dumps({
                'status': 'SKIP',
                'reason': 'SDK HLSL source not available. Re-run with --sdk-root pointing to a local FSR 4.0.2 SDK checkout.',
            }, indent=2) + '\n')
            print(f'Saved (SKIP): {repo_rel(p, repo_root)}')
        print('\n' + '=' * 70)
        print('STATIC RE CLOSURE COMPLETE (partial — SDK-dependent steps skipped)')
        print('=' * 70)
        print(f"Tensor offset plausibility check: {'ALL 78 PASS' if all_pass else 'FAILURES'}")
        print('MAC formulas: SKIP (no SDK)')
        print('Pass layouts: SKIP (no SDK)')
        return 0 if all_pass else 1

    hlsl = hlsl_path.read_text()
    pass_operators = {}
    for m in re.finditer(r'#include\s+"([^"]+)"', hlsl):
        include = m.group(1)
        context = hlsl[max(0, m.start() - 500):m.start()]
        pass_match = re.search(r'PASS_(\d+)', context)
        pass_num = int(pass_match.group(1)) if pass_match else -1
        if 'operators/' in include:
            pass_operators.setdefault(pass_num, []).append(include)

    print('\n\nPass → Operator mapping:')
    for p in sorted(pass_operators):
        print(f'  pass{p}: {pass_operators[p]}')

    mac_path = out_dir / 'mac-arithmetic-formulas.json'
    mac_path.write_text(json.dumps({
        'schema_version': '1.0',
        'source': '4.0.2 MIT-licensed HLSL (ml2code_runtime operators)',
        'method': 'Extracted multiply-accumulate patterns from HLSL operator include files. These operators are #included by each pass function in fsr4_model_v07_fp8_no_scale_passes_1080.hlsl.',
        'pass_operator_mapping': {str(k): v for k, v in pass_operators.items()},
        'operator_analysis': {k: {**v, 'first_30_lines': None} for k, v in mac_formulas.items()},
    }, indent=2) + '\n')
    print(f'\nSaved: {repo_rel(mac_path, repo_root)}')

    print('\n' + '=' * 70)
    print('PART 3: Per-pass tensor layout extraction from HLSL')
    print('=' * 70)
    pass_tensor_layout = {}
    pass_blocks = re.split(r'#ifdef\s+MLSR_PASS_(\d+)(?:_POST)?', hlsl)
    for i in range(1, len(pass_blocks) - 1, 2):
        pass_num = int(pass_blocks[i])
        block = pass_blocks[i + 1] if i + 1 < len(pass_blocks) else ''
        if '_POST' in block[:20]:
            continue
        tensors_in_pass = []
        for m in re.finditer(r'threadGroupStorageByteOffset\s*\n\s*(\d+)', block):
            offset = int(m.group(1))
            shape_match = re.search(r'logicalSize.*?=\s*(.+?),', block[max(0, m.start()-300):m.start()+100])
            tensors_in_pass.append({
                'offset': offset,
                'shape': shape_match.group(1) if shape_match else None,
            })
        pass_tensor_layout[pass_num] = tensors_in_pass
        print(f"  pass{pass_num}: {len(tensors_in_pass)} tensors, offsets: {[t['offset'] for t in tensors_in_pass]}")

    layout_path = out_dir / 'hlsl-per-pass-layout.json'
    layout_path.write_text(json.dumps({
        'schema_version': '1.0',
        'source': repo_rel(hlsl_path, repo_root),
        'pass_count': max(pass_tensor_layout.keys()) + 1,
        'layout': {str(k): v for k, v in sorted(pass_tensor_layout.items())},
    }, indent=2) + '\n')
    print(f'\nSaved: {repo_rel(layout_path, repo_root)}')

    print('\n' + '=' * 70)
    print('STATIC RE CLOSURE COMPLETE')
    print('=' * 70)
    print(f"Tensor offset plausibility check: {'ALL 78 PASS' if all_pass else 'FAILURES'}")
    print(f'MAC formulas extracted: {len(mac_formulas)} operators')
    print(f'Pass layouts extracted: {len(pass_tensor_layout)} passes')
    return 0 if all_pass else 1


if __name__ == '__main__':
    raise SystemExit(main())
