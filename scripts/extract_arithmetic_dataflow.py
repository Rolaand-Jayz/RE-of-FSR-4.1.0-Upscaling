#!/usr/bin/env python3
"""Extract static arithmetic dataflow slices from FSR 4.1.0 DXIL LLVM IR.

Slices start at rawBufferStore value operands and atomic compare-exchange new/compare
operands, then walk SSA producers backward with bounded depth. Output is compact:
per-entrypoint op histograms, provenance-root histograms, and representative slices.
"""
from __future__ import annotations
import argparse,json,re,hashlib
from pathlib import Path
from collections import Counter,defaultdict
ENTRY_RE=re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)",re.S|re.M)
ASSIGN_RE=re.compile(r"^\s*(%[\w.]+)\s*=\s*(.*)$")
VAR_RE=re.compile(r"%[A-Za-z0-9_.]+")
CALL_FAMILY_RE=re.compile(r"@dx\.op\.([^(]+)\(")

def classify(entry):
 if entry.endswith('_prepass'): return 'prepass'
 if entry.endswith('_postpass'): return 'final_postpass'
 if re.search(r'_pass\d+_post$',entry): return 'post_stage'
 if re.search(r'_pass\d+$',entry): return 'main_pass'
 return 'other'
def pass_index(entry):
 m=re.search(r'_pass(\d+)',entry); return int(m.group(1)) if m else None
def sha(s): return hashlib.sha256(s.encode('utf-8',errors='replace')).hexdigest()
def instr_kind(rhs):
 if '@dx.op.rawBufferLoad' in rhs: return 'dxil_rawBufferLoad'
 if '@dx.op.rawBufferStore' in rhs: return 'dxil_rawBufferStore'
 if '@dx.op.atomicCompareExchange' in rhs: return 'dxil_atomicCompareExchange'
 if '@dx.op.atomicBinOp' in rhs: return 'dxil_atomicBinOp'
 if '@dx.op.tertiary' in rhs: return 'dxil_tertiary'
 if '@dx.op.binary' in rhs: return 'dxil_binary'
 if '@dx.op.unary' in rhs: return 'dxil_unary'
 if '@dx.op.' in rhs:
  m=CALL_FAMILY_RE.search(rhs); return 'dxil_'+(m.group(1) if m else 'other')
 for k in ['fadd','fmul','fsub','fdiv','add','mul','sub','shl','lshr','ashr','and','or','xor','icmp','fcmp','select','phi','extractvalue','bitcast','zext','sext','trunc','uitofp','sitofp','fptoui','fptosi']:
  if re.search(r'\b'+k+r'\b',rhs): return 'llvm_'+k
 return 'other'
def split_args(call_line):
 inside=call_line[call_line.find('(')+1:call_line.rfind(')')]
 args=[]; cur=''; depth=0
 for ch in inside:
  if ch=='(' : depth+=1
  elif ch==')': depth-=1
  if ch==',' and depth==0:
   args.append(cur.strip()); cur=''
  else: cur+=ch
 if cur.strip(): args.append(cur.strip())
 return args
def vars_in(s): return VAR_RE.findall(s)
def trace(var,defs,depth=0,max_depth=14,seen=None,nodes=None):
 if seen is None: seen=set()
 if nodes is None: nodes=[]
 if depth>max_depth or var in seen: return nodes
 seen.add(var)
 d=defs.get(var)
 if not d:
  nodes.append({'var':var,'kind':'root_argument_or_undef','line_no':None,'text':var}); return nodes
 kind=instr_kind(d['rhs'])
 nodes.append({'var':var,'kind':kind,'line_no':d['line_no'],'text':d['text'][:240]})
 for v in vars_in(d['rhs']):
  if v!=var: trace(v,defs,depth+1,max_depth,seen,nodes)
 return nodes
def analyze(entry,file,body):
 lines=body.splitlines(); defs={}
 for i,l in enumerate(lines,1):
  m=ASSIGN_RE.match(l)
  if m: defs[m.group(1)]={'line_no':i,'rhs':m.group(2),'text':l.strip()}
 slices=[]; hist=Counter(); root=Counter(); sink_count=Counter()
 for i,l in enumerate(lines,1):
  if '@dx.op.rawBufferStore' in l:
   args=split_args(l); vals=args[4:8] if len(args)>=8 else args
   seed=[]
   for a in vals: seed.extend(vars_in(a))
   sink='rawBufferStore.values'; sink_count[sink]+=1
  elif '@dx.op.atomicCompareExchange' in l:
   args=split_args(l); vals=args[4:7] if len(args)>=7 else args
   seed=[]
   for a in vals: seed.extend(vars_in(a))
   sink='atomicCompareExchange.operands'; sink_count[sink]+=1
  else:
   continue
  nodes=[]; seen=set()
  for v in seed: trace(v,defs,seen=seen,nodes=nodes)
  c=Counter(n['kind'] for n in nodes); hist.update(c)
  for n in nodes:
   if n['kind'] in {'dxil_rawBufferLoad','root_argument_or_undef'} or n['kind'].startswith('dxil_'):
    root[n['kind']]+=1
  if len(slices)<12:
   slices.append({'sink':sink,'line_no':i,'line':l.strip()[:260],'seed_vars':seed,'node_kind_counts':dict(c),'nodes':nodes[:80]})
 return {'file':str(file),'body_sha256':sha(body),'sink_counts':dict(sink_count),'node_kind_counts':dict(hist),'root_counts':dict(root),'sample_slices':slices}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--dxil-dir',type=Path,default=Path('build/llvm_ir/4_1_0')); ap.add_argument('--out',type=Path,default=Path('reports/arithmetic-dataflow-slices.json')); args=ap.parse_args()
 by=defaultdict(list); variants=0
 for p in sorted(args.dxil_dir.glob('*.ll')):
  txt=p.read_text(errors='replace')
  for m in ENTRY_RE.finditer(txt):
   name=m.group(1)
   if not name.startswith('fsr4_model_v07'): continue
   variants+=1; by[name].append(analyze(name,p,m.group('body')))
 summary=[]; g_nodes=Counter(); g_sinks=Counter(); g_roots=Counter()
 for ep,recs in sorted(by.items()):
  nodes=Counter(); sinks=Counter(); roots=Counter(); samples=[]
  for r in recs:
   nodes.update(r['node_kind_counts']); sinks.update(r['sink_counts']); roots.update(r['root_counts'])
   for s in r['sample_slices']:
    if len(samples)<20: samples.append(s)
  g_nodes.update(nodes); g_sinks.update(sinks); g_roots.update(roots)
  summary.append({'entrypoint':ep,'class':classify(ep),'pass_index':pass_index(ep),'variants':len(recs),'sink_counts':dict(sinks),'node_kind_counts':dict(nodes),'root_counts':dict(roots),'has_store_slice':sinks.get('rawBufferStore.values',0)>0,'has_atomic_slice':sinks.get('atomicCompareExchange.operands',0)>0,'sample_slices':samples})
 out={'schema_version':1,'basis':'bounded static SSA backward slices from rawBufferStore and atomicCompareExchange sinks; runtime values not validated','unique_entrypoints':len(summary),'shader_variants':variants,'global_sink_counts':dict(g_sinks),'global_node_kind_counts':dict(g_nodes),'global_root_counts':dict(g_roots),'summary':summary}
 args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(out,indent=2),encoding='utf-8')
 print(f'wrote {args.out}: entrypoints={len(summary)} variants={variants} sinks={dict(g_sinks)}')
 print('nodes', dict(g_nodes.most_common(20)))
if __name__=='__main__': main()
