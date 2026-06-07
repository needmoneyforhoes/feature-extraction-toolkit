#!/usr/bin/env python3
"""Dump exact tick_columns + trade_tape_columns + sample rows.
Run: python3 dump_columns.py market_history.jsonl"""
import json, sys

path = sys.argv[1]
with open(path) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        m = json.loads(line)
        break

print("=" * 70)
print(f"Slug: {m.get('slug')}")
print("=" * 70)

tc = m.get("tick_columns") or []
print(f"\ntick_columns ({len(tc)} columns):")
for i, col in enumerate(tc):
    print(f"  [{i:>2}] {col}")

ticks = m.get("ticks") or []
print(f"\nticks: list of {len(ticks)} rows")
if ticks:
    print("\nFirst 3 tick rows (as column=value):")
    for row_idx, row in enumerate(ticks[:3]):
        print(f"\n  Row {row_idx} (len={len(row)}):")
        for i, col in enumerate(tc):
            val = row[i] if i < len(row) else None
            print(f"    {col:>20} = {val}")
    print("\nLast tick row:")
    row = ticks[-1]
    for i, col in enumerate(tc):
        val = row[i] if i < len(row) else None
        print(f"    {col:>20} = {val}")

ttc = m.get("trade_tape_columns") or []
tt = m.get("trade_tape") or []
print(f"\n{'='*70}")
print(f"trade_tape_columns ({len(ttc)}): {ttc}")
print(f"trade_tape: {len(tt)} rows")
if tt:
    print("First 3 trade rows:")
    for row in tt[:3]:
        print(f"  " + ", ".join(f"{ttc[i]}={row[i]}" for i in range(min(len(ttc), len(row)))))

# Also peek at event_stream schema
es = m.get("event_stream") or []
print(f"\n{'='*70}")
print(f"event_stream: {len(es)} events")
if es and isinstance(es[0], dict):
    print(f"First event keys: {sorted(es[0].keys())}")
    print(f"First event: {es[0]}")
    print(f"Sample mid event: {es[len(es)//2]}")
