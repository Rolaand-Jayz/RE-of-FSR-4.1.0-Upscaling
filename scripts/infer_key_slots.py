#!/usr/bin/env python3
"""Infer static key-slot roles from decoded atomic keys and use context."""
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

def slot_role(space, slot):
    # Static role names from use-context clusters; confidence is reported separately.
    if space == 'operand_or_accumulator':
        return {0x28:'tile_operand_or_accumulator_slot',0x29:'weight_index_indirection_slot',0x2f:'packed_pair_or_channel_slot',0x30:'packed_pair_or_channel_slot',0x32:'metadata_or_stride_slot',0x35:'expanded_operand_slot'}.get(slot,'operand_unknown_slot')
    if space == 'control_or_dimension_metadata':
        return {0x28:'control_tile_selector',0x29:'control_weight_or_loop_bound',0x2a:'dimension_or_loop_metadata',0x2f:'packed_control_pair',0x30:'packed_control_pair',0x32:'shape_or_stride_metadata',0x35:'expanded_control_slot'}.get(slot,'control_unknown_slot')
    if space == 'lane_vector_or_output_slots':
        return {0x28:'lane_vector_slot',0x29:'lane_vector_slot',0x2a:'lane_metadata_slot',0x2f:'output_or_channel_slot',0x30:'output_or_channel_slot',0x32:'post_or_stride_slot',0x35:'expanded_output_slot'}.get(slot,'vector_unknown_slot')
    return 'unknown_slot'

def confidence(space, slot, count):
    if slot in (0x28,0x29,0x2f,0x30,0x32,0x35) and count > 100: return 'medium'
    if count > 1000: return 'medium'
    return 'low'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--decoded', type=Path, default=Path('reports/decoded-buffer-addressing.json')); ap.add_argument('--out', type=Path, default=Path('spec/key-slot-semantics.json')); args=ap.parse_args()
    d=json.load(open(args.decoded))
    slots=defaultdict(Counter)
    examples=defaultdict(list)
    for k in d['global_top_keys']:
        key=(k['space'], k['slot_low8'])
        slots[key].update({k['hex']:k['count']})
        if len(examples[key])<20: examples[key].append(k)
    rows=[]
    for (space,slot), c in sorted(slots.items(), key=lambda kv:(kv[0][0],kv[0][1])):
        total=sum(c.values())
        rows.append({'space':space,'slot_low8':slot,'slot_hex':hex(slot),'inferred_static_role':slot_role(space,slot),'confidence':confidence(space,slot,total),'observed_count_top_keys':total,'unique_key_examples':len(c),'examples':examples[(space,slot)]})
    out={'schema_version':1,'basis':'static clustering of decoded atomic keys plus use context; runtime capture needed for final semantic naming','slots':rows}
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(out,indent=2)); print(f'wrote {args.out}: slots={len(rows)}')
if __name__=='__main__': main()
