#!/usr/bin/env python3
"""Generate static per-pass summaries from RE artifacts."""
from __future__ import annotations
import argparse, json, re
from collections import defaultdict, Counter
from pathlib import Path

def cls(name):
    if re.search(r'_pass\d+$', name): return 'main_pass'
    if re.search(r'_pass\d+_post$', name): return 'post_stage'
    if name.endswith('_prepass'): return 'prepass'
    if name.endswith('_postpass'): return 'final_postpass'
    return 'other'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out', type=Path, default=Path('spec/pass-static-summaries.json')); args=ap.parse_args()
    rb=json.load(open('spec/resource-bindings.json'))
    dx=json.load(open('reports/dxil-ir-evidence.json'))
    atomic=json.load(open('reports/atomic-buffer-patterns.json'))
    aff=json.load(open('reports/affine-ssa-formulas-summary.json'))
    slots=json.load(open('spec/key-slot-semantics.json'))
    slot_lookup={(s['space'],s['slot_low8']):s for s in slots['slots']}
    out_rows=[]
    eps=sorted({x['entrypoint'] for x in dx['summary']})
    rb_by=defaultdict(list); [rb_by[x['entrypoint']].append(x) for x in rb['entries']]
    dx_by={x['entrypoint']:x for x in dx['summary']}
    at_by={x['entrypoint']:x for x in atomic['summary']}
    aff_by=defaultdict(list); [aff_by[x['entrypoint']].append(x) for x in aff.get('entries', aff.get('entry_summaries', []))]
    for ep in eps:
        resources=Counter()
        handles=[]
        for v in rb_by.get(ep,[]):
            for h in v['handles']:
                resources[h['static_role']]+=1
                if len(handles)<8: handles.append(h)
        at=at_by.get(ep,{})
        top_slots=[]
        for k in at.get('atomic_addr_top80',[])[:20]:
            space='operand_or_accumulator' if k['hex'].startswith('0x50') else ('control_or_dimension_metadata' if k['hex'].startswith('0x51') else ('lane_vector_or_output_slots' if k['hex'].startswith('0x52') else 'unknown'))
            slot=k['value'] & 0xff
            sem=slot_lookup.get((space,slot),{})
            top_slots.append({'key':k,'slot_role':sem.get('inferred_static_role','unknown'), 'slot_confidence':sem.get('confidence','low')})
        formulas=Counter()
        formula_count=0
        for v in aff_by.get(ep,[]):
            # Supports either full local affine artifact or compact committed summary.
            if 'formulas' in v:
                source_iter = [{'signature': f['formula']['signature'], 'count': 1} for f in v['formulas'] if f['kind']=='rawBufferLoad.index']
            else:
                source_iter = v.get('top_signatures', [])
            for item in source_iter:
                formulas[item['signature']] += item.get('count', 1); formula_count += item.get('count', 1)
        row={'entrypoint':ep,'class':cls(ep),'variants':dx_by.get(ep,{}).get('variants',0),'line_count':dx_by.get(ep,{}).get('line_count',{}),'resource_role_counts':dict(resources),'representative_handles':handles,'dxop_hist':dx_by.get(ep,{}).get('dxop_hist',{}),'resource_ops':dx_by.get(ep,{}).get('resource_ops',{}),'atomic_addr_total':at.get('atomic_addr_total',0),'atomic_addr_unique':at.get('atomic_addr_unique',0),'top_decoded_key_slots':top_slots,'raw_load_formula_count':formula_count,'top_raw_load_formula_families':[{'signature':k,'count':v} for k,v in formulas.most_common(20)],'static_completion':{'resources_mapped':bool(resources),'dxil_ops_summarized':ep in dx_by,'atomic_patterns_extracted':bool(at),'raw_load_formulas_extracted':formula_count>0}}
        out_rows.append(row)
    out={'schema_version':1,'basis':'static DXIL/resource/key/formula artifacts; not runtime validated','passes':out_rows}
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(out,indent=2)); print(f'wrote {args.out}: passes={len(out_rows)}')
if __name__=='__main__': main()
