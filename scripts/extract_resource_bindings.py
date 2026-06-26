#!/usr/bin/env python3
"""Extract static DXIL resource bindings and handle use roles for FSR4 model entrypoints."""
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
CREATE_RE = re.compile(r"(%\d+)\s*=\s*call %dx\.types\.Handle @dx\.op\.createHandle\(i32\s+57,\s*i8\s+(\d+),\s*i32\s+(\d+),\s*i32\s+(\d+),\s*i1\s+(true|false)\)")
DXOP_HANDLE_RE = re.compile(r"@dx\.op\.([\w\.]+)\([^\n]*?%dx\.types\.Handle\s+(%\d+)")
META_RES_LINE_RE = re.compile(r"!(\d+)\s*=\s*!\{i32\s+(\d+),\s*ptr undef,\s*!\"([^\"]*)\",\s*i32\s+(-?\d+),\s*i32\s+(-?\d+),\s*i32\s+(-?\d+),\s*i32\s+(-?\d+)(.*)\}")

RANGE_KIND = {
    0: 'SRV_or_tbuffer',
    1: 'UAV',
    2: 'CBV_or_root_constants',
    3: 'sampler',
}
HANDLE_CLASS = {
    0: 'SRV',
    1: 'UAV',
    2: 'CBV',
    3: 'sampler',
}

def cls(name):
    if re.search(r'_pass\d+$', name): return 'main_pass'
    if re.search(r'_pass\d+_post$', name): return 'post_stage'
    if name.endswith('_prepass'): return 'prepass'
    if name.endswith('_postpass'): return 'final_postpass'
    return 'other'

def semantic_role(handle_class, reg, uses):
    ops=set(uses)
    if 'atomicCompareExchange.i32' in ops:
        return 'atomic_indirection_or_scratch_uav'
    if 'rawBufferLoad.i32' in ops and handle_class == 'SRV':
        return 'raw_model_or_weight_buffer_srv'
    if 'rawBufferLoad.i32' in ops and handle_class == 'UAV':
        return 'raw_intermediate_or_operand_uav'
    if 'cbufferLoadLegacy.i32' in ops or handle_class == 'CBV':
        return 'constant_buffer_or_root_constants'
    if any('Store' in op for op in ops):
        return 'write_target'
    return 'unknown_static_role'

def parse_metadata_resources(text):
    resources=[]
    for m in META_RES_LINE_RE.finditer(text):
        mid, rid, name, kind, reg, space, count, rest = m.groups()
        kind=int(kind); reg=int(reg); space=int(space); count=int(count)
        resources.append({'metadata_id': int(mid), 'resource_id': int(rid), 'name': name, 'range_kind_raw': kind, 'range_kind': RANGE_KIND.get(kind, 'unknown'), 'register': reg, 'space': space, 'count_or_size': count, 'raw_tail': rest.strip()})
    return resources

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0'))
    ap.add_argument('--out', type=Path, default=Path('spec/resource-bindings.json'))
    args=ap.parse_args()
    entries=[]
    all_unmapped=[]
    for path in sorted(args.dxil_dir.glob('*.ll')):
        text=path.read_text(errors='replace')
        resources=parse_metadata_resources(text)
        for em in ENTRY_RE.finditer(text):
            ep=em.group(1)
            if not ep.startswith('fsr4_model_v07'): continue
            body=em.group('body')
            handles={}
            for cm in CREATE_RE.finditer(body):
                var, hclass, range_id, index, non_uniform = cm.groups()
                hclass=int(hclass); range_id=int(range_id); lower=0; index=int(index)
                handles[var]={'handle':var,'handle_class_raw':hclass,'handle_class':HANDLE_CLASS.get(hclass,'unknown'),'range_id':range_id,'lower_bound':lower,'index':index,'non_uniform':non_uniform=='true','ops':Counter()}
            for op,var in DXOP_HANDLE_RE.findall(body):
                if var in handles:
                    handles[var]['ops'][op]+=1
                else:
                    all_unmapped.append({'file':str(path),'entrypoint':ep,'handle':var,'op':op})
            hrows=[]
            for h,row in sorted(handles.items(), key=lambda kv:int(kv[0][1:])):
                uses=dict(row.pop('ops'))
                row['uses']=uses
                row['static_role']=semantic_role(row['handle_class'], row['index'], uses)
                hrows.append(row)
            entries.append({'file':str(path),'entrypoint':ep,'class':cls(ep),'metadata_resources':resources,'handles':hrows})
    # aggregate by entrypoint name
    by_ep=defaultdict(lambda:{'variants':0,'handle_roles':Counter(),'handle_signatures':Counter()})
    for e in entries:
        b=by_ep[e['entrypoint']]; b['variants']+=1
        for h in e['handles']:
            b['handle_roles'][h['static_role']]+=1
            sig=(h['handle_class'], h['range_id'], h['lower_bound'], h['index'], h['static_role'], tuple(sorted(h['uses'].items())))
            b['handle_signatures'][repr(sig)]+=1
    summary=[]
    for ep,b in sorted(by_ep.items()):
        summary.append({'entrypoint':ep,'class':cls(ep),'variants':b['variants'],'role_counts':dict(b['handle_roles']),'signature_count':len(b['handle_signatures']),'top_signatures':[{'signature':k,'count':v} for k,v in b['handle_signatures'].most_common(20)]})
    out={'schema_version':1,'source':str(args.dxil_dir),'entries':entries,'summary':summary,'unmapped_handle_uses':all_unmapped,'static_role_note':'Roles are static inferences from DXIL createHandle metadata and use-sites; runtime descriptor capture can refine names.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out,indent=2))
    print(f'wrote {args.out}: entries={len(entries)} unmapped={len(all_unmapped)}')
if __name__=='__main__': main()
