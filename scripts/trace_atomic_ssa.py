#!/usr/bin/env python3
"""Trace SSA provenance for atomicCompareExchange/rawBufferLoad chains in FSR4 LLVM IR."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

DEF_RE = re.compile(r"^\s*(%\d+)\s*=\s*(.*)$")
ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
ATOMIC_LINE_RE = re.compile(r"(%\d+)\s*=\s*call i32 @dx\.op\.atomicCompareExchange\.i32\(i32\s+79,\s*%dx\.types\.Handle\s+(%\d+),\s*i32\s+(-?\d+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i32\s+([^\)]+)\)")
RAW_LINE_RE = re.compile(r"(%\d+)\s*=\s*call %dx\.types\.ResRet\.i32 @dx\.op\.rawBufferLoad\.i32\(i32\s+139,\s*%dx\.types\.Handle\s+(%\d+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i8\s+(\d+),\s*i32\s+(\d+)\)")
VAR_RE = re.compile(r"%\d+")

def decode_key(v:int):
    return {
        'value': v,
        'hex': hex(v % (1<<32)),
        'space_hi8': (v >> 24) & 0xff,
        'plane_mid8': (v >> 16) & 0xff,
        'tile_y_or_row_hi4': (v >> 12) & 0xf,
        'tile_x_or_col_low4': (v >> 8) & 0xf,
        'slot_low8': v & 0xff,
        'mid16': (v >> 8) & 0xffff,
        'low12': v & 0xfff,
    }

def classify_key(v:int):
    hi=(v>>24)&0xff; low=v&0xff
    if hi==0x50 and low in (0x29,0x2a,0x2f,0x30,0x32): return 'weight_or_constant_index'
    if hi==0x51: return 'control_or_shape_metadata'
    if hi==0x52: return 'vector_lane_or_output_slot'
    if hi==0x50 and low in (0x28,0x35): return 'tile_accumulator_or_operand_slot'
    return 'unknown'

def expr_tree(var, defs, depth=0, seen=None):
    if seen is None: seen=set()
    if depth>5 or var in seen: return {'var':var, 'truncated':True}
    seen.add(var)
    expr=defs.get(var)
    if expr is None: return {'var':var, 'source':'external_or_arg'}
    uses=VAR_RE.findall(expr)
    return {'var':var,'expr':expr[:240],'uses':[expr_tree(u, defs, depth+1, seen.copy()) for u in uses[:6]]}

def cls(name):
    if re.search(r'_pass\d+$', name): return 'main_pass'
    if re.search(r'_pass\d+_post$', name): return 'post_stage'
    if name.endswith('_prepass'): return 'prepass'
    if name.endswith('_postpass'): return 'final_postpass'
    return 'other'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0'))
    ap.add_argument('--out', type=Path, default=Path('reports/atomic-ssa-trace.json'))
    ap.add_argument('--max-events-per-entry', type=int, default=80)
    args=ap.parse_args()
    entries=[]
    for path in sorted(args.dxil_dir.glob('*.ll')):
        text=path.read_text(errors='replace')
        for em in ENTRY_RE.finditer(text):
            name=em.group(1)
            if not name.startswith('fsr4_model_v07'): continue
            lines=em.group('body').splitlines()
            defs={}
            for line in lines:
                m=DEF_RE.match(line)
                if m: defs[m.group(1)]=m.group(2)
            events=[]
            for i,line in enumerate(lines,1):
                am=ATOMIC_LINE_RE.search(line)
                if am:
                    out, handle, key_s, c1,c2,cmpv,newv=am.groups()
                    key=int(key_s)
                    evt={'line':i,'kind':'atomicCompareExchange','out':out,'handle':handle,'key':decode_key(key),'key_class':classify_key(key),'compare':cmpv.strip(),'new':newv.strip(),'line_text':line.strip()[:500]}
                    if cmpv.strip().startswith('%'):
                        evt['compare_provenance']=expr_tree(cmpv.strip(), defs)
                    if newv.strip().startswith('%'):
                        evt['new_provenance']=expr_tree(newv.strip(), defs)
                    events.append(evt)
                rm=RAW_LINE_RE.search(line)
                if rm:
                    out, handle, idx, elem, mask, align=rm.groups()
                    evt={'line':i,'kind':'rawBufferLoad','out':out,'handle':handle,'index':idx.strip(),'element':elem.strip(),'mask':int(mask),'align':int(align),'line_text':line.strip()[:500]}
                    if idx.strip().startswith('%'):
                        evt['index_provenance']=expr_tree(idx.strip(), defs)
                    events.append(evt)
                if len(events)>=args.max_events_per_entry:
                    break
            if events:
                entries.append({'file':str(path),'entrypoint':name,'class':cls(name),'events':events})
    out={'schema_version':1,'source':str(args.dxil_dir),'entries':entries}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f'wrote {args.out} entries={len(entries)}')
if __name__=='__main__': main()
