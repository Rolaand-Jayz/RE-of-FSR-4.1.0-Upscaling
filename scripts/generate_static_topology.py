#!/usr/bin/env python3
"""Build a conservative static topology map from pass-level RE artifacts."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

def pass_num(ep):
 m=re.search(r'_pass(\d+)',ep); return int(m.group(1)) if m else None
def stage_kind(p):
 ep=p['entrypoint']; cls=p['class']
 if cls=='prepass': return 'input_analysis_or_prepass'
 if cls=='final_postpass': return 'final_output_postprocess'
 if cls=='post_stage': return 'per_pass_post_stage'
 if cls=='main_pass':
  a=p.get('activation_nonlinearity',{}); ar=p.get('arithmetic_dataflow',{}); res=p.get('resource_role_counts',{})
  if ar.get('node_kind_counts',{}).get('llvm_fadd',0)>0: return 'accumulation_heavy_main_pass'
  if a.get('has_direct_relu_or_lower_clamp_zero'): return 'activation_gated_main_pass'
  if res.get('raw_model_or_weight_buffer_srv',0)>0: return 'weighted_transform_main_pass'
  return 'main_pass_static_transform'
 return 'other'
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,default=Path('spec/static-layer-topology.json')); args=ap.parse_args()
 ps=json.load(open('spec/pass-static-summaries.json'))['passes']
 inv=json.load(open('spec/dxil-entrypoint-inventory.json'))
 order=sorted(ps,key=lambda p:(-1 if p['class']=='prepass' else (99 if p['class']=='final_postpass' else pass_num(p['entrypoint']) or 98), 0 if p['class']=='main_pass' else 1, p['entrypoint']))
 rows=[]
 for idx,p in enumerate(order):
  rows.append({'order':idx,'entrypoint':p['entrypoint'],'class':p['class'],'pass_index':pass_num(p['entrypoint']),'stage_kind':stage_kind(p),'variants':p.get('variants',0),'resource_roles':p.get('resource_role_counts',{}),'static_signals':{'raw_load_formula_count':p.get('raw_load_formula_count',0),'atomic_addr_total':p.get('atomic_addr_total',0),'activation_events':p.get('activation_nonlinearity',{}).get('event_count',0),'direct_relu_or_lower_clamp_zero':p.get('activation_nonlinearity',{}).get('has_direct_relu_or_lower_clamp_zero',False),'arithmetic_sinks':p.get('arithmetic_dataflow',{}).get('sink_counts',{})}})
 main=[r for r in rows if r['class']=='main_pass']; post=[r for r in rows if r['class']=='post_stage']
 paired=[]
 for m in main:
  mate=next((p for p in post if p['pass_index']==m['pass_index']),None)
  paired.append({'pass_index':m['pass_index'],'main':m['entrypoint'],'post':mate['entrypoint'] if mate else None,'has_post':mate is not None})
 out={'schema_version':1,'basis':'static ordering/classification from entrypoint names plus generated static summaries; not runtime dispatch order proof','entrypoint_count':len(rows),'classes':inv.get('classes',{}),'topology':rows,'main_post_pairs':paired,'observations':{'main_passes':len(main),'post_stages':len(post),'main_passes_with_post_stage':sum(1 for p in paired if p['has_post']),'prepass_count':sum(1 for r in rows if r['class']=='prepass'),'final_postpass_count':sum(1 for r in rows if r['class']=='final_postpass')}}
 args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(out,indent=2),encoding='utf-8')
 print(f"wrote {args.out}: entries={len(rows)} main={len(main)} post={len(post)} paired={out['observations']['main_passes_with_post_stage']}")
if __name__=='__main__': main()
