#!/usr/bin/env python3
"""Extract static activation / nonlinearity evidence from FSR 4.1.0 DXIL LLVM IR.

This is intentionally conservative: it records DXIL opcode ids, LLVM compare/select
instructions, and local producer/consumer context. It does not claim a runtime
activation name unless the static opcode pattern is direct (e.g. FMax(x, 0)).
"""
from __future__ import annotations
import argparse, hashlib, json, re
from collections import Counter, defaultdict
from pathlib import Path

ENTRY_RE = re.compile(r"define\s+[^@]*@([^\(]+)\s*\([^)]*\)\s*\{(?P<body>.*?)(?=^}\s*$)", re.S|re.M)
ASSIGN_RE = re.compile(r"^\s*(%[\w.]+)\s*=\s*(.*)$")
CALL_RE = re.compile(r"@dx\.op\.(?P<family>[^(]+)\((?P<args>.*)\)")
ID_RE = re.compile(r"i32\s+(-?\d+)")
CONST_ZERO_RE = re.compile(r"\b(?:float|half|double|i\d+)\s+(?:0(?:\.000000e\+00)?|0xH0000|0x0000000000000000)\b")
CONST_ONE_RE = re.compile(r"\b(?:float|half|double|i\d+)\s+(?:1(?:\.000000e\+00)?|0xH3C00|0x3FF0000000000000)\b")

# DXIL op ids used here. Names are factual enough for the shader-model docs but
# still preserved as ids in output so the claim does not depend on this map alone.
BINARY_NAMES = {
    35: "FMax", 36: "FMin", 37: "IMax", 38: "IMin", 39: "UMax", 40: "UMin",
}
UNARY_NAMES = {
    21: "Log", 22: "Exp", 23: "Sqrt", 24: "Rsqrt", 25: "Round_ne", 26: "Round_ni", 27: "Round_pi", 28: "Round_z",
}

def classify(entry: str) -> str:
    if entry.endswith('_prepass'): return 'prepass'
    if entry.endswith('_postpass'): return 'final_postpass'
    if re.search(r'_pass\d+_post$', entry): return 'post_stage'
    if re.search(r'_pass\d+$', entry): return 'main_pass'
    return 'other'

def pass_index(entry: str):
    m=re.search(r'_pass(\d+)', entry)
    return int(m.group(1)) if m else None

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8', errors='replace')).hexdigest()

def parse_id(args: str):
    m = ID_RE.search(args)
    return int(m.group(1)) if m else None

def type_from_line(line: str) -> str:
    m = re.search(r"call\s+([^@]+)\s+@dx\.op", line)
    if m: return m.group(1).strip()
    m = re.search(r"\b(?:fcmp|icmp)\s+\w+\s+([^,]+)", line)
    if m: return m.group(1).strip()
    m = re.search(r"\bselect\s+i1\s+[^,]+,\s+([^,]+)", line)
    return m.group(1).strip() if m else "unknown"

def direct_pattern(kind: str, op_name: str, line: str) -> str:
    if op_name == 'FMax' and CONST_ZERO_RE.search(line): return 'direct_relu_or_lower_clamp_zero'
    if op_name == 'FMin' and CONST_ONE_RE.search(line): return 'direct_upper_clamp_one'
    if op_name == 'FMin' and CONST_ZERO_RE.search(line): return 'direct_upper_clamp_zero'
    if op_name in {'IMax','UMax'} and CONST_ZERO_RE.search(line): return 'integer_lower_clamp_zero'
    if op_name in {'IMin','UMin'} and CONST_ONE_RE.search(line): return 'integer_upper_clamp_one'
    if kind == 'select' and CONST_ZERO_RE.search(line): return 'select_zero_gate_or_relu_candidate'
    return 'nonlinear_or_control'

def collect_context(lines, idx, radius=3):
    lo=max(0, idx-radius); hi=min(len(lines), idx+radius+1)
    return [{'line_no': j+1, 'text': lines[j].strip()} for j in range(lo, hi)]

def analyze_body(entry, file, body):
    lines=body.splitlines()
    events=[]; defs={}
    for i,line in enumerate(lines):
        m=ASSIGN_RE.match(line)
        if m: defs[m.group(1)] = {'line_no': i+1, 'text': line.strip()}
    for i,line in enumerate(lines):
        stripped=line.strip()
        kind=None; op_id=None; op_name=None; family=None
        cm=CALL_RE.search(line)
        if cm and (cm.group('family').startswith('binary.') or cm.group('family').startswith('unary.')):
            family=cm.group('family')
            op_id=parse_id(cm.group('args'))
            if family.startswith('binary'):
                op_name=BINARY_NAMES.get(op_id, f'binary_{op_id}')
                if op_name not in {'FMax','FMin','IMax','IMin','UMax','UMin'}:
                    continue
                kind='dxil_binary_extremum'
            elif family.startswith('unary'):
                op_name=UNARY_NAMES.get(op_id, f'unary_{op_id}')
                if op_name not in {'Log','Exp','Sqrt','Rsqrt'}:
                    continue
                kind='dxil_unary_nonlinear'
        elif re.search(r'\bfcmp\b', line):
            kind='llvm_fcmp'; op_name=(re.search(r'\bfcmp\s+(?:fast\s+)?([a-z]+)', line).group(1) if re.search(r'\bfcmp\s+(?:fast\s+)?([a-z]+)', line) else 'unknown'); family='llvm.fcmp'
        elif re.search(r'\bicmp\b', line):
            kind='llvm_icmp'; op_name=re.search(r'\bicmp\s+([a-z]+)', line).group(1); family='llvm.icmp'
        elif re.search(r'\bselect\b', line):
            kind='llvm_select'; op_name='select'; family='llvm.select'
        else:
            continue
        lhs=None
        am=ASSIGN_RE.match(line)
        if am: lhs=am.group(1)
        ev={
            'file': str(file), 'entrypoint': entry, 'line_no': i+1, 'kind': kind, 'family': family,
            'dxil_op_id': op_id, 'op_name': op_name, 'result': lhs, 'type': type_from_line(line),
            'pattern': direct_pattern(kind, op_name, line), 'line': stripped,
            'context': collect_context(lines, i, 2),
        }
        events.append(ev)
    return events

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dxil-dir', type=Path, default=Path('build/llvm_ir/4_1_0'))
    ap.add_argument('--out', type=Path, default=Path('reports/activation-nonlinearity-evidence.json'))
    args=ap.parse_args()
    all_events=[]; per=defaultdict(list); variants=0
    for p in sorted(args.dxil_dir.glob('*.ll')):
        text=p.read_text(errors='replace')
        for m in ENTRY_RE.finditer(text):
            name=m.group(1)
            if not name.startswith('fsr4_model_v07'): continue
            variants+=1
            evs=analyze_body(name, p, m.group('body'))
            all_events.extend(evs); per[name].append({'file':str(p), 'events':evs, 'body_sha256':sha256(m.group('body'))})
    summary=[]
    for name,recs in sorted(per.items()):
        c=Counter(); pat=Counter(); op=Counter(); samples=[]
        for r in recs:
            for e in r['events']:
                c[e['kind']]+=1; pat[e['pattern']]+=1; op[f"{e['family']}:{e['dxil_op_id'] if e['dxil_op_id'] is not None else e['op_name']}"]+=1
                if len(samples)<25 and e['pattern'] != 'nonlinear_or_control': samples.append(e)
        summary.append({
            'entrypoint':name,'class':classify(name),'pass_index':pass_index(name),'variants':len(recs),
            'event_count':sum(c.values()),'kind_counts':dict(c),'pattern_counts':dict(pat),'opcode_counts':dict(op),
            'has_direct_relu_or_lower_clamp_zero': pat.get('direct_relu_or_lower_clamp_zero',0)>0,
            'has_direct_upper_clamp_one': pat.get('direct_upper_clamp_one',0)>0,
            'sample_events': samples,
        })
    global_kind=Counter(e['kind'] for e in all_events)
    global_pattern=Counter(e['pattern'] for e in all_events)
    global_opcode=Counter(f"{e['family']}:{e['dxil_op_id'] if e['dxil_op_id'] is not None else e['op_name']}" for e in all_events)
    out={
        'schema_version':1,
        'basis':'static DXIL LLVM IR only; runtime activation behavior not validated',
        'dxil_op_id_notes': {'binary.35':'FMax','binary.36':'FMin','binary.37':'IMax','binary.38':'IMin','binary.39':'UMax','binary.40':'UMin','unary.21':'Log','unary.22':'Exp','unary.23':'Sqrt','unary.24':'Rsqrt'},
        'unique_entrypoints':len(summary),'shader_variants':variants,
        'global_kind_counts':dict(global_kind),'global_pattern_counts':dict(global_pattern),'global_opcode_counts':dict(global_opcode),
        'summary':summary,
        'events_sample':all_events[:300],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f"wrote {args.out} with {len(summary)} entrypoints, {variants} variants, {len(all_events)} events")
    print('patterns', dict(global_pattern))
if __name__=='__main__': main()
