#!/usr/bin/env python3
"""
Run on VPS:
  cd .
  python3 vps_full_analysis.py

Reads market_history.jsonl + market_recap_history.jsonl
Outputs: full_analysis_results.json  (upload back to Claude)
"""
import json, os, statistics
from collections import defaultdict

HISTORY_PATH = 'market_history.jsonl'
RECAP_PATH   = 'market_recap_history.jsonl'
OUT_PATH     = 'full_analysis_results.json'

TICK_COLS = None  # populated from first market

def fire_cat(f):
    if f.get('pre_gate_held') or f.get('opp_gate_held'):
        return 'HELD'
    if f.get('opp_gate_would_block') or f.get('opp_gate_blocked'):
        return 'WBLOCK'
    return 'FREE'

def pnl(lst):
    return round(sum(f.get('hypo_pnl', 0) for f in lst), 4)

# ── 1. Load recap: per-market fire data ──────────────────────────────────
print("Loading recap history...")
recap = {}
with open(RECAP_PATH) as f:
    for line in f:
        d = json.loads(line)
        slug = d.get('slug','')
        winner = d.get('winner')
        fires  = d.get('fires', [])
        if not slug or not winner or winner not in ('UP','DN'):
            continue
        for fire in fires:
            fire['_cat'] = fire_cat(fire)
        recap[slug] = {'winner': winner, 'fires': fires}
print(f"  Recap markets loaded: {len(recap)}")

# ── 2. Load tick data: compute entry EMA spread + mid-market signal ──────
print("Loading tick history (this may take a moment)...")
tick_data = {}
total_lines = 0
with open(HISTORY_PATH) as f:
    for line in f:
        total_lines += 1
        d = json.loads(line)
        slug   = d.get('slug','')
        winner = d.get('winner')
        cols   = d.get('tick_columns', [])
        ticks  = d.get('ticks', [])
        if not slug or not winner or not ticks or not cols:
            continue

        # Build column index
        ci = {c: i for i, c in enumerate(cols)}

        # Need: cd, up_ask, dn_ask, up_ema, dn_ema
        required = ['cd','up_ask','dn_ask']
        has_ema  = 'up_ema' in ci and 'dn_ema' in ci
        if not all(c in ci for c in required):
            continue

        # Sort ticks by cd descending (highest cd = earliest in market)
        sorted_ticks = sorted(ticks, key=lambda t: t[ci['cd']], reverse=True)

        # ── GATE I: entry EMA spread ─────────────────────────────────────
        # First tick at cd >= 240
        entry_tick = None
        for t in sorted_ticks:
            if t[ci['cd']] >= 240:
                entry_tick = t
                break

        entry_up_ask   = entry_tick[ci['up_ask']]  if entry_tick else None
        entry_dn_ask   = entry_tick[ci['dn_ask']]  if entry_tick else None
        entry_up_ema   = entry_tick[ci['up_ema']]  if (entry_tick and has_ema) else None
        entry_dn_ema   = entry_tick[ci['dn_ema']]  if (entry_tick and has_ema) else None
        entry_cd       = entry_tick[ci['cd']]       if entry_tick else None

        # Use EMA if available, else raw ask
        e_up = entry_up_ema if entry_up_ema else entry_up_ask
        e_dn = entry_dn_ema if entry_dn_ema else entry_dn_ask
        entry_spread = round(e_dn - e_up, 4) if (e_up and e_dn) else None

        # ── GATE II: mid-market avg ask in cd=230→200 window ─────────────
        window_ticks = [t for t in sorted_ticks
                        if 200 <= t[ci['cd']] <= 230]
        if window_ticks:
            avg_up_200 = sum(t[ci['up_ask']] for t in window_ticks) / len(window_ticks)
            avg_dn_200 = sum(t[ci['dn_ask']] for t in window_ticks) / len(window_ticks)
            mid_spread_200 = round(avg_dn_200 - avg_up_200, 4)
        else:
            avg_up_200 = avg_dn_200 = mid_spread_200 = None

        # ── GATE III: mid-market at cd=190→160 ───────────────────────────
        window_ticks_160 = [t for t in sorted_ticks
                            if 160 <= t[ci['cd']] <= 190]
        if window_ticks_160:
            avg_up_160 = sum(t[ci['up_ask']] for t in window_ticks_160) / len(window_ticks_160)
            avg_dn_160 = sum(t[ci['dn_ask']] for t in window_ticks_160) / len(window_ticks_160)
            mid_spread_160 = round(avg_dn_160 - avg_up_160, 4)
        else:
            avg_up_160 = avg_dn_160 = mid_spread_160 = None

        # ── dn_live simulation: UP >= threshold sustained ─────────────────
        # Check if UP >= threshold for 2+ consecutive 10s samples at cd<=210
        # Simulate at $0.50 (current) and $0.60 (proposed reform)
        # 10s samples: take ticks spaced ~10s apart at cd<=210
        cd_210_ticks = [t for t in sorted_ticks if t[ci['cd']] <= 210]
        # Sample every 10s: group by floor(cd/10)
        sampled = {}
        for t in cd_210_ticks:
            bucket = int(t[ci['cd']] // 10)
            if bucket not in sampled:
                sampled[bucket] = t[ci['up_ask']]
        samples_210 = sorted(sampled.items(), reverse=True)  # high cd first

        def dn_live_triggers(threshold, min_consec=2):
            consec = 0
            for _, up_val in samples_210:
                if up_val >= threshold:
                    consec += 1
                    if consec >= min_consec:
                        return True
                else:
                    consec = 0
            return False

        dn_live_050 = dn_live_triggers(0.50)
        dn_live_060 = dn_live_triggers(0.60)

        tick_data[slug] = {
            'winner':          winner,
            'entry_spread':    entry_spread,
            'entry_cd':        entry_cd,
            'entry_up':        round(e_up, 4)  if e_up  else None,
            'entry_dn':        round(e_dn, 4)  if e_dn  else None,
            'mid_spread_200':  mid_spread_200,
            'mid_spread_160':  mid_spread_160,
            'dn_live_050':     dn_live_050,
            'dn_live_060':     dn_live_060,
            'n_ticks':         len(ticks),
        }

print(f"  Tick markets loaded: {len(tick_data)} (from {total_lines} lines)")

# ── 3. Merge and compute all scenarios ───────────────────────────────────
print("Computing scenarios...")
results = []
for slug, rec in recap.items():
    winner = rec['winner']
    fires  = rec['fires']

    gc_up     = [f for f in fires if f['_cat']=='FREE'   and f['side']=='UP']
    gc_dn     = [f for f in fires if f['_cat']=='FREE'   and f['side']=='DN']
    held_dn   = [f for f in fires if f['_cat']=='HELD'   and f['side']=='DN']
    wblock_dn = [f for f in fires if f['_cat']=='WBLOCK' and f['side']=='DN']

    s0 = pnl(gc_up) + pnl(gc_dn)            # current
    s1 = pnl(gc_dn)                          # block all UP GC
    s2 = pnl(gc_dn) + pnl(held_dn)          # + release HELD DN
    s3 = pnl(gc_dn) + pnl(held_dn) + pnl(wblock_dn)  # + release WBLOCK DN

    tick = tick_data.get(slug, {})
    entry_spread   = tick.get('entry_spread')
    mid_spread_200 = tick.get('mid_spread_200')
    mid_spread_160 = tick.get('mid_spread_160')
    dn_live_050    = tick.get('dn_live_050')
    dn_live_060    = tick.get('dn_live_060')

    # Gate I: entry_spread > 0 → block UP
    # If triggered: UP fires blocked = s1 base (only GC DN remains)
    # In UP market if triggered: catastrophic (loses UP profits)
    gate1_fires = (entry_spread is not None and entry_spread > 0)

    # Gate II candidates: various mid-market thresholds
    # For each threshold T: if avg_dn_200 - avg_up_200 > T → block UP
    # Simulate for T in [-0.10, -0.05, 0, +0.05, +0.10]
    gate2_results = {}
    for threshold in [-0.10, -0.05, 0.00, 0.05, 0.10, 0.15, 0.20]:
        if mid_spread_200 is not None:
            gate2_results[threshold] = mid_spread_200 > threshold
        else:
            gate2_results[threshold] = False

    gate3_results = {}
    for threshold in [-0.10, -0.05, 0.00, 0.05, 0.10, 0.15, 0.20]:
        if mid_spread_160 is not None:
            gate3_results[threshold] = mid_spread_160 > threshold
        else:
            gate3_results[threshold] = False

    results.append({
        'slug':    slug,
        'winner':  winner,
        's0': s0, 's1': s1, 's2': s2, 's3': s3,
        'gc_up_n':    len(gc_up),    'gc_up_pnl':    pnl(gc_up),
        'gc_dn_n':    len(gc_dn),    'gc_dn_pnl':    pnl(gc_dn),
        'held_dn_n':  len(held_dn),  'held_dn_pnl':  pnl(held_dn),
        'wblock_dn_n':len(wblock_dn),'wblock_dn_pnl':pnl(wblock_dn),
        'entry_spread':   entry_spread,
        'mid_spread_200': mid_spread_200,
        'mid_spread_160': mid_spread_160,
        'dn_live_050':    dn_live_050,
        'dn_live_060':    dn_live_060,
        'gate1_fires':    gate1_fires,
        'gate2':          gate2_results,
        'gate3':          gate3_results,
    })

# ── 4. Save results ───────────────────────────────────────────────────────
with open(OUT_PATH, 'w') as f:
    json.dump(results, f)
print(f"\nSaved {len(results)} markets to {OUT_PATH}")

# ── 5. Quick summary ──────────────────────────────────────────────────────
up_r = [r for r in results if r['winner']=='UP']
dn_r = [r for r in results if r['winner']=='DN']
print(f"\nTotal: {len(results)}  UP={len(up_r)}  DN={len(dn_r)}")

def avg(lst): return sum(lst)/len(lst) if lst else 0

print("\n=== DN WIN — scenario averages ===")
for lbl, key in [('S0 Current','s0'),('S1 UP blocked','s1'),
                  ('S2 +HELD DN','s2'),('S3 +WBLOCK DN','s3')]:
    vals = [r[key] for r in dn_r]
    hits = sum(1 for v in vals if v >= 5)
    neg  = sum(1 for v in vals if v < 0)
    print(f"  {lbl:20}: avg={avg(vals):>+7.2f}  neg={neg}/{len(vals)}  ≥+$5={hits}/{len(vals)}")

print("\n=== Gate I trigger stats ===")
g1_dn = [r for r in dn_r if r['gate1_fires']]
g1_up = [r for r in up_r if r['gate1_fires']]
print(f"  Triggers on DN markets: {len(g1_dn)}/{len(dn_r)}")
print(f"  Triggers on UP markets: {len(g1_up)}/{len(up_r)}  ← FALSE POSITIVES")
if g1_dn:
    print(f"  Avg s1 pnl when triggered (DN): {avg([r['s1'] for r in g1_dn]):>+7.2f}")

print("\n=== Gate II threshold sweep (cd=230→200 window) ===")
for t in [-0.10, -0.05, 0.00, 0.05, 0.10, 0.15, 0.20]:
    g2_dn_hits = sum(1 for r in dn_r if r['gate2'].get(t, False))
    g2_up_hits = sum(1 for r in up_r if r['gate2'].get(t, False))
    print(f"  T={t:>+5.2f}: DN triggers={g2_dn_hits}/{len(dn_r)} "
          f"UP triggers={g2_up_hits}/{len(up_r)}  "
          f"FP_rate={g2_up_hits/max(1,len(up_r))*100:.1f}%")

print("\n=== dn_live reform: $0.50 vs $0.60 ===")
for thresh, key in [('$0.50 (current)','dn_live_050'),('$0.60 (reform)','dn_live_060')]:
    dn_hits = sum(1 for r in dn_r if r.get(key))
    up_hits = sum(1 for r in up_r if r.get(key))
    print(f"  {thresh}: DN triggers={dn_hits}/{len(dn_r)}  UP triggers={up_hits}/{len(up_r)}")

print(f"\nDone. Upload {OUT_PATH} back to Claude for full analysis.")
