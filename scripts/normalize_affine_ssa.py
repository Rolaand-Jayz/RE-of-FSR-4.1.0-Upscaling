#!/usr/bin/env python3
"""Normalize selected FSR4 LLVM SSA expressions into affine-ish formula families.

This is intentionally conservative: it extracts linear constants and symbolic terms from
add/shl/lshr/tertiary patterns used around rawBufferLoad and atomic indirection.
Unknown constructs are preserved as symbolic atoms rather than guessed away.
"""
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
DEF_RE = re.compile(r"^\s*(%\d+)\s*=\s*(.*)$")
RAW_RE = re.compile(r"(%\d+)\s*=\s*call %dx\.types\.ResRet\.i32 @dx\.op\.rawBufferLoad\.i32\(i32\s+139,\s*%dx\.types\.Handle\s+(%\d+),\s*i32\s+([^,]+),")
ATOMIC_RE = re.compile(r"(%\d+)\s*=\s*call i32 @dx\.op\.atomicCompareExchange\.i32\(i32\s+79,\s*%dx\.types\.Handle\s+(%\d+),\s*i32\s+(-?\d+),\s*i32\s+[^,]+,\s*i32\s+[^,]+,\s*i32\s+([^,]+),\s*i32\s+([^\)]+)\)")
VAR_RE = re.compile(r"%\d+")

class Expr:
    def __init__(self, const=0, terms=None, unknown=None):
        self.const=const; self.terms=Counter(terms or {}); self.unknown=Counter(unknown or {})
    def add(self,o):
        return Expr(self.const+o.const, self.terms+o.terms, self.unknown+o.unknown)
    def scale(self,k):
        return Expr(self.const*k, {t:v*k for t,v in self.terms.items()}, {t:v*k for t,v in self.unknown.items()})
    def sig(self):
        parts=[]
        for k,v in sorted(self.terms.items()): parts.append(f"{v}*{k}" if v!=1 else k)
        for k,v in sorted(self.unknown.items()): parts.append(f"{v}*UNK({k})" if v!=1 else f"UNK({k})")
        if self.const or not parts: parts.append(str(self.const))
        return " + ".join(parts)
    def to_json(self): return {'const':self.const,'terms':dict(self.terms),'unknown':dict(self.unknown),'signature':self.sig()}

def atom(var, defs):
    expr=defs.get(var,'')
    if 'groupId.i32' in expr:
        m=re.search(r'i32 94, i32 (\d+)', expr); return Expr(terms={f'groupId{m.group(1) if m else "?"}':1})
    if 'threadIdInGroup.i32' in expr:
        m=re.search(r'i32 95, i32 (\d+)', expr); return Expr(terms={f'threadId{m.group(1) if m else "?"}':1})
    return Expr(unknown={var:1})

def norm(x, defs, depth=0, seen=None):
    x=x.strip()
    if re.fullmatch(r'-?\d+', x): return Expr(const=int(x))
    if not x.startswith('%'): return Expr(unknown={x:1})
    if seen is None: seen=set()
    if depth>12 or x in seen: return atom(x, defs)
    seen.add(x)
    e=defs.get(x)
    if not e: return atom(x, defs)
    if m:=re.match(r'add i32 (%\d+|-?\d+), (%\d+|-?\d+)', e): return norm(m.group(1),defs,depth+1,seen.copy()).add(norm(m.group(2),defs,depth+1,seen.copy()))
    if m:=re.match(r'sub i32 (%\d+|-?\d+), (%\d+|-?\d+)', e): return norm(m.group(1),defs,depth+1,seen.copy()).add(norm(m.group(2),defs,depth+1,seen.copy()).scale(-1))
    if m:=re.match(r'shl i32 (%\d+|-?\d+), (\d+)', e): return norm(m.group(1),defs,depth+1,seen.copy()).scale(1<<int(m.group(2)))
    if m:=re.match(r'lshr(?: exact)? i32 (%\d+), (\d+)', e):
        # Preserve division/floor behavior as unknown if not obviously divisible.
        sub=norm(m.group(1),defs,depth+1,seen.copy())
        return Expr(unknown={f'({sub.sig()})>>{m.group(2)}':1})
    if m:=re.match(r'and i32 (%\d+), (\d+)', e):
        sub=norm(m.group(1),defs,depth+1,seen.copy())
        return Expr(unknown={f'({sub.sig()})&{m.group(2)}':1})
    if m:=re.match(r'or i32 (%\d+), (%\d+|-?\d+)', e):
        return Expr(unknown={f'OR({norm(m.group(1),defs,depth+1,seen.copy()).sig()},{norm(m.group(2),defs,depth+1,seen.copy()).sig()})':1})
    if m:=re.search(r'@dx\.op\.tertiary\.i32\(i32 49, i32 (-?\d+), i32 ([^,]+), i32 ([^\)]+)\)', e):
        scale=int(m.group(1)); a=m.group(2).strip(); b=m.group(3).strip()
        # DXIL tertiary op 49 behaves like IMad in these patterns: scale*a + b.
        return norm(a,defs,depth+1,seen.copy()).scale(scale).add(norm(b,defs,depth+1,seen.copy()))
    if 'phi i32' in e:
        return Expr(unknown={re.sub(r'%\d+','%v',e[:120]):1})
    if 'atomicCompareExchange' in e:
        return Expr(unknown={re.sub(r'%\d+','%v',e[:180]):1})
    return atom(x, defs)

def cls(name):
    if re.search(r'_pass\d+$', name): return 'main_pass'
    if re.search(r'_pass\d+_post$', name): return 'post_stage'
    if name.endswith('_prepass'): return 'prepass'
    if name.endswith('_postpass'): return 'final_postpass'
    return 'other'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0')); ap.add_argument('--out', type=Path, default=Path('reports/affine-ssa-formulas.json')); args=ap.parse_args()
    entries=[]; global_sigs=Counter()
    for path in sorted(args.dxil_dir.glob('*.ll')):
        text=path.read_text(errors='replace')
        for em in ENTRY_RE.finditer(text):
            ep=em.group(1)
            if not ep.startswith('fsr4_model_v07'): continue
            body=em.group('body'); defs={}
            for line in body.splitlines():
                m=DEF_RE.match(line)
                if m: defs[m.group(1)]=m.group(2)
            formulas=[]
            for line_no,line in enumerate(body.splitlines(),1):
                rm=RAW_RE.search(line)
                if rm:
                    out,handle,idx=rm.groups(); ex=norm(idx,defs); global_sigs[ex.sig()]+=1; formulas.append({'line':line_no,'kind':'rawBufferLoad.index','out':out,'handle':handle,'var':idx.strip(),'formula':ex.to_json(),'line_text':line.strip()[:400]})
                am=ATOMIC_RE.search(line)
                if am:
                    out,handle,key,cmpv,newv=am.groups()
                    for kind,var in [('atomic.compare',cmpv.strip()),('atomic.new',newv.strip())]:
                        ex=norm(var,defs); global_sigs[ex.sig()]+=1; formulas.append({'line':line_no,'kind':kind,'out':out,'handle':handle,'key':int(key),'var':var,'formula':ex.to_json(),'line_text':line.strip()[:400]})
            if formulas: entries.append({'file':str(path),'entrypoint':ep,'class':cls(ep),'formulas':formulas})
    out={'schema_version':1,'source':str(args.dxil_dir),'entries':entries,'global_formula_families':[{'signature':k,'count':v} for k,v in global_sigs.most_common(200)]}
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(out,indent=2)); print(f'wrote {args.out}: entries={len(entries)} families={len(global_sigs)}')
if __name__=='__main__': main()
