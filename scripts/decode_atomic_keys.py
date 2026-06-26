#!/usr/bin/env python3
"""Decode packed atomic key constants and load-index formula families."""
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
DEF_RE = re.compile(r"^\s*(%\d+)\s*=\s*(.*)$")
ATOMIC_RE = re.compile(r"(%\d+)\s*=\s*call i32 @dx\.op\.atomicCompareExchange\.i32\(i32\s+79,\s*%dx\.types\.Handle\s+(%\d+),\s*i32\s+(-?\d+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i32\s+([^,]+),\s*i32\s+([^\)]+)\)")
RAW_RE = re.compile(r"(%\d+)\s*=\s*call %dx\.types\.ResRet\.i32 @dx\.op\.rawBufferLoad\.i32\(i32\s+139,\s*%dx\.types\.Handle\s+(%\d+),\s*i32\s+([^,]+),")

def cls(name):
    if re.search(r'_pass\d+$', name): return 'main_pass'
    if re.search(r'_pass\d+_post$', name): return 'post_stage'
    if name.endswith('_prepass'): return 'prepass'
    if name.endswith('_postpass'): return 'final_postpass'
    return 'other'

def decode(v):
    hi=(v>>24)&0xff; plane=(v>>16)&0xff; y=(v>>12)&0xf; x=(v>>8)&0xf; slot=v&0xff
    # Hypothesis names are based on observed grid regularity, not runtime binding captures.
    if hi==0x50: space='operand_or_accumulator'
    elif hi==0x51: space='control_or_dimension_metadata'
    elif hi==0x52: space='lane_vector_or_output_slots'
    else: space='unknown'
    return {'value':v,'hex':hex(v%(1<<32)),'space_hi8':hi,'space':space,'plane_mid8':plane,'tile_y_hi4':y,'tile_x_low4':x,'slot_low8':slot,'slot_hex':hex(slot),'mid16':(v>>8)&0xffff,'low12':v&0xfff}

def expr_signature(var, defs, depth=0, seen=None):
    if seen is None: seen=set()
    if depth>6 or var in seen: return var
    seen.add(var)
    expr=defs.get(var, var)
    # Normalize SSA numbers but keep constants/opcodes.
    norm=re.sub(r'%\d+', '%v', expr)
    uses=re.findall(r'%\d+', expr)
    if not uses: return norm
    child=[expr_signature(u, defs, depth+1, seen.copy()) for u in uses[:3]]
    return norm + ' <- [' + '; '.join(child) + ']'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0'))
    ap.add_argument('--out', type=Path, default=Path('reports/decoded-buffer-addressing.json'))
    args=ap.parse_args()
    pass_rows=[]; global_keys=Counter(); formula_families=Counter()
    for path in sorted(args.dxil_dir.glob('*.ll')):
        text=path.read_text(errors='replace')
        for em in ENTRY_RE.finditer(text):
            name=em.group(1)
            if not name.startswith('fsr4_model_v07'): continue
            body=em.group('body'); lines=body.splitlines()
            defs={}
            atomic_out_to_key={}
            key_counts=Counter(); spaces=Counter(); raw_formulas=Counter(); first_chains=[]
            for line in lines:
                m=DEF_RE.match(line)
                if m: defs[m.group(1)]=m.group(2)
                am=ATOMIC_RE.search(line)
                if am:
                    out, handle, key_s, c1, c2, cmpv, newv=am.groups(); key=int(key_s); dec=decode(key)
                    atomic_out_to_key[out]=dec
                    key_counts[key]+=1; spaces[dec['space']]+=1; global_keys[key]+=1
                rm=RAW_RE.search(line)
                if rm:
                    out, handle, idx=rm.groups(); idx=idx.strip()
                    sig=expr_signature(idx, defs)
                    raw_formulas[sig]+=1; formula_families[sig]+=1
                    if len(first_chains)<12:
                        first_chains.append({'raw_out':out,'raw_handle':handle,'index_var':idx,'index_formula_signature':sig,'index_source_key':atomic_out_to_key.get(idx)})
            if key_counts or raw_formulas:
                pass_rows.append({'file':str(path),'entrypoint':name,'class':cls(name),'key_space_counts':dict(spaces),'unique_keys':len(key_counts),'top_keys':[dict(decode(k), count=v) for k,v in key_counts.most_common(40)],'raw_load_formula_families':[{'signature':k,'count':v} for k,v in raw_formulas.most_common(20)],'first_raw_load_chains':first_chains})
    out={'schema_version':1,'source':str(args.dxil_dir),'interpretation_status':'field names are structural hypotheses from static IR regularity; runtime descriptor capture still required for final semantic naming','decoded_fields':'key = (space_hi8 << 24) | (plane_mid8 << 16) | (tile_y_hi4 << 12) | (tile_x_low4 << 8) | slot_low8','global_top_keys':[dict(decode(k), count=v) for k,v in global_keys.most_common(120)],'global_raw_formula_families':[{'signature':k,'count':v} for k,v in formula_families.most_common(80)],'entries':pass_rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f'wrote {args.out} entries={len(pass_rows)} unique_global_keys={len(global_keys)}')
if __name__=='__main__': main()
