#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_big_file.py — Inspect the schema of market_history.jsonl

Run this on VPS. It reads ONE market record and dumps everything about it:
  - top-level keys
  - tick_columns structure (dict-of-lists? list-of-dicts? nested?)
  - field names, types, sample values
  - first few ticks

Output: inspect_report.txt (plus prints to stdout)

This tells us what the big file actually looks like so we can fix the analyzer.
"""

import json
import sys
import argparse

def describe_value(v, depth=0, max_depth=3):
    """Human-readable type+sample description."""
    indent = "  " * depth
    if v is None: return "None"
    t = type(v).__name__
    if t in ("int", "float", "bool", "str"):
        val_str = repr(v)[:80]
        return f"{t}={val_str}"
    if t == "list":
        if len(v) == 0: return "list(empty)"
        sample = v[0]
        if depth >= max_depth:
            return f"list(len={len(v)}, item_type={type(sample).__name__})"
        s = describe_value(sample, depth+1, max_depth)
        return f"list(len={len(v)}, sample={s})"
    if t == "dict":
        if depth >= max_depth:
            return f"dict(len={len(v)}, keys={list(v.keys())[:5]})"
        parts = []
        for k in list(v.keys())[:10]:
            sub = describe_value(v[k], depth+1, max_depth)
            parts.append(f"\n{indent}  {k}: {sub}")
        return f"dict(len={len(v)}){''.join(parts)}"
    return f"{t}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="market_history.jsonl path")
    ap.add_argument("--skip", type=int, default=0,
                    help="Skip N markets, inspect the (N+1)th (default 0 = first)")
    ap.add_argument("--out", default="inspect_report.txt")
    args = ap.parse_args()
    
    out_lines = []
    def emit(line=""):
        print(line)
        out_lines.append(line)
    
    emit("=" * 90)
    emit(f"  INSPECTING: {args.path}")
    emit(f"  Skip: {args.skip}   Inspecting market #{args.skip+1}")
    emit("=" * 90)
    
    market = None
    with open(args.path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line: continue
            if i < args.skip: continue
            try:
                market = json.loads(line)
            except Exception as e:
                emit(f"  Line {i}: JSON error — {e}")
                continue
            break
    
    if market is None:
        emit("  ❌ No valid market found")
        sys.exit(1)
    
    emit(f"\n  Market slug: {market.get('slug')}")
    emit(f"  Market size (bytes as JSON): {len(json.dumps(market))}")
    emit(f"\n  TOP-LEVEL KEYS ({len(market.keys())} total):")
    for k in sorted(market.keys()):
        v = market[k]
        desc = describe_value(v, depth=0, max_depth=1)
        emit(f"    {k:>30}: {desc[:200]}")
    
    # Focus on tick_columns — the critical field
    tc = market.get("tick_columns")
    emit("\n" + "=" * 90)
    emit("  TICK_COLUMNS DEEP INSPECTION")
    emit("=" * 90)
    if tc is None:
        emit("  tick_columns is MISSING. Looking for alternatives...")
        for k in market.keys():
            if "tick" in k.lower() or "event" in k.lower() or "trade" in k.lower():
                emit(f"    Alternative candidate: {k}")
                emit(f"      {describe_value(market[k], depth=0, max_depth=2)[:400]}")
    elif isinstance(tc, list):
        emit(f"  tick_columns is a LIST of length {len(tc)}")
        if tc:
            emit(f"  First item type: {type(tc[0]).__name__}")
            if isinstance(tc[0], dict):
                emit(f"  First item keys: {sorted(tc[0].keys())}")
                emit(f"  First item values:")
                for k in sorted(tc[0].keys()):
                    emit(f"    {k:>25}: {repr(tc[0][k])[:80]}")
                if len(tc) > 1:
                    emit(f"\n  Second item (to verify schema consistency):")
                    for k in sorted(tc[1].keys()):
                        emit(f"    {k:>25}: {repr(tc[1][k])[:80]}")
            elif isinstance(tc[0], list):
                emit(f"  First item is a LIST of len={len(tc[0])}: {tc[0][:20]}")
    elif isinstance(tc, dict):
        emit(f"  tick_columns is a DICT with {len(tc)} keys")
        emit(f"  Keys: {sorted(tc.keys())}")
        for k in sorted(tc.keys())[:10]:
            v = tc[k]
            if isinstance(v, list):
                emit(f"    {k:>25}: list(len={len(v)}) sample={v[:5]}")
            else:
                emit(f"    {k:>25}: {type(v).__name__} = {repr(v)[:60]}")
    else:
        emit(f"  tick_columns is a {type(tc).__name__}: {repr(tc)[:200]}")
    
    # Also look at events
    ev = market.get("events")
    emit("\n" + "=" * 90)
    emit("  EVENTS FIELD")
    emit("=" * 90)
    if ev is None:
        emit("  events is MISSING")
    elif isinstance(ev, list):
        emit(f"  events is a LIST of length {len(ev)}")
        if ev:
            emit(f"  First event type: {type(ev[0]).__name__}")
            if isinstance(ev[0], dict):
                emit(f"  First event keys: {sorted(ev[0].keys())}")
                emit(f"  First event:")
                for k in sorted(ev[0].keys()):
                    emit(f"    {k:>25}: {repr(ev[0][k])[:80]}")
                emit(f"\n  Last event:")
                for k in sorted(ev[-1].keys()):
                    emit(f"    {k:>25}: {repr(ev[-1][k])[:80]}")
    else:
        emit(f"  events: {type(ev).__name__}")
    
    # trade_tape_columns
    ttc = market.get("trade_tape_columns")
    emit("\n" + "=" * 90)
    emit("  TRADE_TAPE_COLUMNS FIELD")
    emit("=" * 90)
    if ttc is None:
        emit("  trade_tape_columns is MISSING")
    elif isinstance(ttc, list):
        emit(f"  trade_tape_columns is LIST of len={len(ttc)}")
        if ttc and isinstance(ttc[0], dict):
            emit(f"  First trade keys: {sorted(ttc[0].keys())}")
            emit(f"  First trade: {ttc[0]}")
    elif isinstance(ttc, dict):
        emit(f"  trade_tape_columns is DICT with keys: {list(ttc.keys())}")
        for k, v in list(ttc.items())[:5]:
            if isinstance(v, list):
                emit(f"    {k}: list(len={len(v)}) sample={v[:3]}")
    
    # Save
    with open(args.out, "w") as f:
        f.write("\n".join(out_lines))
    emit(f"\n  Report saved: {args.out}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
