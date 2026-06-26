#!/usr/bin/env python3
"""Extract atomicCompareExchange address/key patterns from FSR4 DXIL IR.

FSR4 main passes use many atomicCompareExchange.i32 calls. This script extracts
constant arguments and clusters them by entrypoint so the buffer-addressing
mechanism is represented as data instead of prose.
"""
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
ATOMIC_RE = re.compile(r"@dx\.op\.atomicCompareExchange\.i32\(i32\s+79,\s*%dx\.types\.Handle\s+%[^,]+,\s*i32\s+(-?\d+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i32\s+([^\)]+)\)")
RAW_RE = re.compile(r"@dx\.op\.rawBufferLoad\.i32\(i32\s+139,\s*%dx\.types\.Handle\s+%[^,]+,\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i8\s+(\d+),\s*i32\s+(\d+)\)")
TER_RE = re.compile(r"@dx\.op\.tertiary\.i32\(i32\s+49,\s*i32\s+(-?\d+),\s*i32\s+([^,]+),\s*i32\s+([^\)]+)\)")

def cls(name):
    if re.search(r'_pass\d+$', name): return 'main_pass'
    if re.search(r'_pass\d+_post$', name): return 'post_stage'
    if name.endswith('_prepass'): return 'prepass'
    if name.endswith('_postpass'): return 'final_postpass'
    return 'other'

def idx(name):
    m=re.search(r'_pass(\d+)', name)
    return int(m.group(1)) if m else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0'))
    ap.add_argument('--out', type=Path, default=Path('reports/atomic-buffer-patterns.json'))
    args=ap.parse_args()
    per=defaultdict(lambda: {'variants':0,'files':[], 'atomic_addr':Counter(), 'atomic_compare':Counter(), 'atomic_new':Counter(), 'raw_mask_align':Counter(), 'tertiary_scale':Counter()})
    for path in sorted(args.dxil_dir.glob('*.ll')):
        text=path.read_text(errors='replace')
        for m in ENTRY_RE.finditer(text):
            name=m.group(1)
            if not name.startswith('fsr4_model_v07'): continue
            body=m.group('body')
            rec=per[name]; rec['variants']+=1; rec['files'].append(str(path))
            for am in ATOMIC_RE.finditer(body):
                addr, coord1, coord2, cmpv, newv = [x.strip() for x in am.groups()]
                rec['atomic_addr'][int(addr)] += 1
                rec['atomic_compare'][cmpv] += 1
                rec['atomic_new'][newv] += 1
            for rm in RAW_RE.finditer(body):
                idxv, elem, mask, align = [x.strip() for x in rm.groups()]
                rec['raw_mask_align'][(int(mask), int(align))] += 1
            for tm in TER_RE.finditer(body):
                scale, a, b = [x.strip() for x in tm.groups()]
                rec['tertiary_scale'][int(scale)] += 1
    summary=[]
    for name, r in sorted(per.items()):
        summary.append({
            'entrypoint': name, 'class': cls(name), 'pass_index': idx(name), 'variants': r['variants'], 'files': r['files'],
            'atomic_addr_unique': len(r['atomic_addr']), 'atomic_addr_total': sum(r['atomic_addr'].values()),
            'atomic_addr_top80': [{'value':k,'hex':hex(k % (1<<32)),'count':v} for k,v in r['atomic_addr'].most_common(80)],
            'atomic_compare_top20': [{'value':k,'count':v} for k,v in r['atomic_compare'].most_common(20)],
            'atomic_new_top20': [{'value':k,'count':v} for k,v in r['atomic_new'].most_common(20)],
            'raw_mask_align': [{'mask':k[0],'align':k[1],'count':v} for k,v in r['raw_mask_align'].most_common()],
            'tertiary_scale': [{'scale':k,'count':v} for k,v in r['tertiary_scale'].most_common()],
        })
    out={'schema_version':1,'source':str(args.dxil_dir),'summary':summary}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f'wrote {args.out} with {len(summary)} entrypoints')
if __name__=='__main__': main()
