#!/usr/bin/env python3
"""Extract factual per-entrypoint evidence from FSR 4.1.0 LLVM IR dumps.

This is RE evidence, not documentation polish. It scans the disassembled DXIL LLVM
IR corpus and emits machine-readable facts for every fsr4_model_v07 entrypoint:
entrypoint names, source blobs, resource op counts, rough arithmetic/opcode
signals, threadgroup metadata, and constant/load/store patterns.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from collections import Counter, defaultdict
from pathlib import Path

ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
META_ENTRY_RE = re.compile(r'!\d+\s*=\s*!\{ptr @([^,]+), !"([^"]+)"')
NUMTHREADS_RE = re.compile(r'!\d+\s*=\s*!\{i32\s+(\d+),\s*i32\s+(\d+),\s*i32\s+(\d+)\}')

RESOURCE_PATTERNS = {
    "rawBufferLoad": r"dx\.op\.rawBufferLoad",
    "rawBufferStore": r"dx\.op\.rawBufferStore",
    "bufferLoad": r"dx\.op\.bufferLoad",
    "bufferStore": r"dx\.op\.bufferStore",
    "createHandle": r"dx\.op\.createHandle",
    "annotateHandle": r"dx\.op\.annotateHandle",
    "atomicBinOp": r"dx\.op\.atomicBinOp",
    "atomicCompareExchange": r"dx\.op\.atomicCompareExchange",
    "threadId": r"dx\.op\.threadId",
    "groupId": r"dx\.op\.groupId",
    "flattenedThreadIdInGroup": r"dx\.op\.flattenedThreadIdInGroup",
    "barrier": r"dx\.op\.barrier",
}
ARITH_PATTERNS = {
    "fadd": r"\bfadd\b", "fmul": r"\bfmul\b", "fsub": r"\bfsub\b", "fdiv": r"\bfdiv\b",
    "add": r"(?<![a-z])add\b", "mul": r"(?<![a-z])mul\b", "sub": r"(?<![a-z])sub\b", "shl": r"\bshl\b", "lshr": r"\blshr\b", "ashr": r"\bashr\b",
    "and": r"\band\b", "or": r"\bor\b", "xor": r"\bxor\b",
    "icmp": r"\bicmp\b", "fcmp": r"\bfcmp\b", "select": r"\bselect\b", "phi": r"\bphi\b",
    "call": r"\bcall\b",
}

DXOP_CALL_RE = re.compile(r"call\s+[^@]*@dx\.op\.([^\(]+)\([^)]*\)")
CALL_LINE_RE = re.compile(r"call\s+.*@dx\.op\.([^\(]+)\((.*)\)")

def dxop_hist(body: str):
    return dict(Counter(DXOP_CALL_RE.findall(body)))

def interesting_calls(body: str, limit=80):
    rows=[]
    for line in body.splitlines():
        if '@dx.op.' not in line:
            continue
        m=CALL_LINE_RE.search(line)
        if not m:
            continue
        op,args=m.group(1),m.group(2)
        if any(k in op for k in ['rawBufferLoad','rawBufferStore','atomic','binary','unary','tertiary','dot','wave','barrier']):
            rows.append({'op':op,'line':line.strip()[:500]})
        if len(rows)>=limit:
            break
    return rows

def opcode_name_hist(body: str):
    # DXIL op id is usually the first i32 argument in dx.op calls. Preserve ids for later manual mapping.
    c=Counter()
    for line in body.splitlines():
        if '@dx.op.' not in line:
            continue
        m=CALL_LINE_RE.search(line)
        if not m: continue
        op,args=m.group(1),m.group(2)
        idm=re.search(r'i32\s+(\d+)', args)
        c[f'{op}:{idm.group(1) if idm else "?"}']+=1
    return dict(c)

ACTIVATION_PATTERNS = {
    "relu_select_zero": r"select\s+i1\s+%[^,]+,\s+float\s+%[^,]+,\s+float\s+0\.0|select\s+i1\s+%[^,]+,\s+half\s+%[^,]+,\s+half\s+0xH0000",
    "maxnum": r"dx\.op\.binary\.f32.*FMax|dx\.op\.binary\.f16.*FMax|maxnum|fmax",
    "clamp_like": r"FMin|FMax|umin|umax|smin|smax",
}

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8', errors='replace')).hexdigest()

def classify(entry: str) -> str:
    if entry.endswith('_prepass'): return 'prepass'
    if entry.endswith('_postpass'): return 'final_postpass'
    if re.search(r'_pass\d+_post$', entry): return 'post_stage'
    if re.search(r'_pass\d+$', entry): return 'main_pass'
    return 'other'

def pass_index(entry: str):
    m=re.search(r'_pass(\d+)', entry)
    return int(m.group(1)) if m else None

def extract_offsets(body: str):
    # Conservative: collect literal byte-ish offsets used near rawBufferLoad/Store lines.
    vals=[]
    for line in body.splitlines():
        if 'rawBufferLoad' in line or 'rawBufferStore' in line or 'atomicBinOp' in line:
            for m in re.finditer(r'i32\s+(-?\d+)', line):
                v=int(m.group(1))
                if 0 <= v <= 200000:
                    vals.append(v)
    c=Counter(vals)
    return [{'value': k, 'count': v} for k,v in c.most_common(40)]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0'))
    ap.add_argument('--out', type=Path, default=Path('reports/dxil-ir-evidence.json'))
    args=ap.parse_args()
    entries=defaultdict(list)
    for p in sorted(args.dxil_dir.glob('*.ll')):
        text=p.read_text(errors='replace')
        for m in ENTRY_RE.finditer(text):
            name=m.group(1)
            if not name.startswith('fsr4_model_v07'):
                continue
            body=m.group('body')
            rec={
                'file': str(p), 'entrypoint': name, 'class': classify(name), 'pass_index': pass_index(name),
                'body_sha256': sha256(body), 'line_count': body.count('\n')+1,
                'resource_ops': {k: len(re.findall(rx, body)) for k,rx in RESOURCE_PATTERNS.items()},
                'arith_ops': {k: len(re.findall(rx, body)) for k,rx in ARITH_PATTERNS.items()},
                'dxop_hist': dxop_hist(body),
                'dxop_id_hist': opcode_name_hist(body),
                'interesting_dxop_calls': interesting_calls(body),
                'activation_signals': {k: len(re.findall(rx, body, re.I)) for k,rx in ACTIVATION_PATTERNS.items()},
                'raw_literal_offsets_top40': extract_offsets(body),
            }
            entries[name].append(rec)
    summary=[]
    for name,recs in sorted(entries.items()):
        agg={'entrypoint':name,'class':classify(name),'pass_index':pass_index(name),'variants':len(recs),'files':[r['file'] for r in recs]}
        for group in ['resource_ops','arith_ops','activation_signals']:
            keys=recs[0][group].keys()
            agg[group]={k: {'min': min(r[group][k] for r in recs), 'max': max(r[group][k] for r in recs), 'sum': sum(r[group][k] for r in recs)} for k in keys}
        for group in ['dxop_hist','dxop_id_hist']:
            cc=Counter()
            for r in recs:
                cc.update(r[group])
            agg[group]=dict(cc.most_common())
        # Keep one representative call sample per entrypoint.
        agg['interesting_dxop_calls_sample']=recs[0].get('interesting_dxop_calls', [])
        agg['line_count']={'min':min(r['line_count'] for r in recs),'max':max(r['line_count'] for r in recs)}
        # Merge offsets across variants.
        cc=Counter()
        for r in recs:
            for item in r['raw_literal_offsets_top40']:
                cc[item['value']]+=item['count']
        agg['raw_literal_offsets_top40']=[{'value':k,'count':v} for k,v in cc.most_common(40)]
        summary.append(agg)
    out={'schema_version':1,'source':str(args.dxil_dir),'unique_entrypoints':len(summary),'summary':summary,'variants':sum((recs for recs in entries.values()), [])}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f'wrote {args.out} with {len(summary)} unique entrypoints and {len(out["variants"])} variants')
if __name__=='__main__': main()
