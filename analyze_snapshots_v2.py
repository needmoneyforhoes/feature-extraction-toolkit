#!/usr/bin/env python3
"""
Rule discovery analysis using v2 snapshot format.

Leverages v2 pre-computed fields:
  - `class.cheap_side_won`:   instant filter for flip markets (no recompute)
  - `settle.up_peak_incl_settle` / `dn_peak_incl_settle`: correct peaks
  - `bk[tk].v`:                pre-computed velocities (v1_ua, r_fdp, etc.)
  - `events.*`:                dynamic event markers

Much faster than v1 — no velocity recomputation per event.

USAGE:
  python3 analyze_snapshots_v2.py market_snapshots_v2.jsonl
"""

import json
import sys
import argparse
from collections import defaultdict
from itertools import combinations


def load_records(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def extract_entry_events(records, ask_min=0.01, ask_max=0.10):
    """
    For each record, generate entry events (one per bucket where cheap side was
    in [ask_min, ask_max]). Returns list of dicts with all features pre-ready.
    """
    events = []
    for r in records:
        if 'error' in r: continue
        if r.get('v') != 2: continue  # skip v1 records
        winner = r.get('winner')
        if winner not in ('UP', 'DN'): continue

        buckets = r.get('bk') or {}
        # Sort buckets by cd descending (T-200 → T-5)
        tk_sorted = sorted(buckets.keys(), key=lambda tk: -int(tk.split('-')[1]))

        for side in ('UP', 'DN'):
            ask_key = 'ua' if side == 'UP' else 'da'
            # udp = own depth (UP side: ud, DN side: dd)
            udp_key = 'ud' if side == 'UP' else 'dd'
            fdp_key = 'dd' if side == 'UP' else 'ud'
            # Velocity keys: for UP side we care about r_dd (fav depth = DN),
            # for DN side we care about r_ud.
            r_fdp_key = 'r_dd' if side == 'UP' else 'r_ud'
            r_udp_key = 'r_ud' if side == 'UP' else 'r_dd'
            v1_ask_key = 'v1_ua' if side == 'UP' else 'v1_da'

            for tk in tk_sorted:
                b = buckets[tk]
                ask = b.get(ask_key, 0) or 0
                if not (ask_min <= ask <= ask_max): continue
                udp = b.get(udp_key, 0) or 0
                fdp = b.get(fdp_key, 0) or 0
                cv = b.get('cv', 0) or 0
                bn = b.get('bn_d', 0) or 0

                vel = b.get('v') or {}
                v1_ask = vel.get(v1_ask_key)
                r_fdp = vel.get(r_fdp_key)
                r_udp = vel.get(r_udp_key)

                # Did this side win at settle?
                won = (winner == side)
                if won:
                    settle_val = 1.00
                else:
                    settle_val = 0.00
                gain_abs = settle_val - ask  # absolute gain if held to settle

                events.append({
                    'slug': r['slug'],
                    'side': side,
                    'tk':   tk,
                    'won':  won,
                    'ask':  ask,
                    'udp':  udp,
                    'fdp':  fdp,
                    'cv':   cv,
                    'bn':   bn,
                    'bn_abs': abs(bn),
                    'ratio': udp / max(1, fdp),
                    'v1_ask': v1_ask,  # may be None for T-200
                    'r_fdp':  r_fdp,
                    'r_udp':  r_udp,
                    'gain_abs': gain_abs,
                })
    return events


def sim_ev(events, rule, shares=5, slip=0.01):
    """Simulate hold-to-settle PnL with fixed-share position."""
    fires = [e for e in events if rule(e)]
    n = len(fires)
    if n == 0:
        return {'n': 0}
    wins = sum(1 for e in fires if e['won'])
    unique_mkts = len(set((e['slug'], e['side']) for e in fires if e['won']))
    total_cost = 0; total_pnl = 0
    for e in fires:
        cost = shares * (e['ask'] + slip)
        total_cost += cost
        if e['won']:
            total_pnl += shares * 1.00 - cost
        else:
            total_pnl += 0 - cost
    return {
        'n': n,
        'wins': wins,
        'wr': 100 * wins / n,
        'unique_markets': unique_mkts,
        'total_cost': total_cost,
        'total_pnl': total_pnl,
        'ev_per_trade': total_pnl / n,
    }


def test_rules(events, rules):
    """Run a named set of rules and print comparison table."""
    print(f"{'Rule':<40} {'Fires':<6} {'Wins':<5} {'WR%':<5} {'Mkts':<5} {'Cost':<8} {'PnL':<10} {'EV':<10}")
    print('-' * 100)
    for name, rule in rules:
        r = sim_ev(events, rule)
        if r['n'] == 0:
            print(f"  {name:<40} no fires")
            continue
        m = ' ⭐⭐' if r['ev_per_trade'] >= 2 else ' ⭐' if r['ev_per_trade'] >= 0.5 else ' ✅' if r['ev_per_trade'] > 0 else ' ❌'
        print(f"  {name:<40} {r['n']:<6} {r['wins']:<5} {r['wr']:<5.0f} {r['unique_markets']:<5} "
              f"${r['total_cost']:<7.2f} ${r['total_pnl']:<+9.2f} ${r['ev_per_trade']:<+9.2f}{m}")


def main():
    ap = argparse.ArgumentParser(description='v2-powered analysis of flip/cusp rules')
    ap.add_argument('input_file', help='v2 market_snapshots.jsonl file')
    ap.add_argument('--ask-min', type=float, default=0.01)
    ap.add_argument('--ask-max', type=float, default=0.10)
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    records = load_records(args.input_file)
    v2_count = sum(1 for r in records if r.get('v') == 2)
    print(f"Loaded {len(records)} records ({v2_count} v2)")

    # Summary from pre-computed class flags
    cheap_won = [r for r in records if r.get('class', {}).get('cheap_side_won')]
    flipped = [r for r in records if r.get('class', {}).get('flipped_across_50')]
    print(f"  cheap_side_won markets: {len(cheap_won)}")
    print(f"  flipped_across_50:      {len(flipped)}")

    # Show cheap-side-won markets with pre-computed details
    print(f"\n🏆 CHEAP-SIDE-WON MARKETS (from v2 class flags):")
    print(f"  {'slug':<32} {'side':<4} {'cheap_min':<10} {'at':<6} {'settle_peak':<12}")
    for r in cheap_won:
        c = r.get('class', {})
        s = r.get('settle', {})
        if c.get('cheap_side_winner') == 'UP':
            side, cheap, tk, peak = 'UP', c['cheap_min_ask_up'], c.get('cheap_min_tk_up'), s['up_peak_incl_settle']
        else:
            side, cheap, tk, peak = 'DN', c['cheap_min_ask_dn'], c.get('cheap_min_tk_dn'), s['dn_peak_incl_settle']
        print(f"  {r['slug']:<32} {side:<4} ${cheap:<9.3f} {tk or '-':<6} ${peak:.2f}")

    # Extract entry events in the cheap zone
    events = extract_entry_events(records, args.ask_min, args.ask_max)
    print(f"\n📊 Entry events in ask [${args.ask_min}-${args.ask_max}]: {len(events)}")
    print(f"  Winners (side won at settle): {sum(1 for e in events if e['won'])}")

    # Test the SAME rules we discovered but now with v2 data
    print("\n" + "="*100)
    print("🎯 FLIP RULE DISCOVERY (v2 pre-computed velocities)")
    print("="*100)

    # Our TIGHT + MEDIUM rules (the LIVE + SHADOW strategies in the bot)
    base_rules = [
        ('FLIP_TIGHT R1 (cv≥0.95 + v1_ask≥0.01 + r_fdp≤0.7)',
            lambda e: e['cv'] >= 0.95 and (e['v1_ask'] or 0) >= 0.01 and (e['r_fdp'] or 1) <= 0.7),
        ('FLIP_TIGHT R2 (udp≥1000 + fdp≥3000 + ask≤0.03)',
            lambda e: e['udp'] >= 1000 and e['fdp'] >= 3000 and e['ask'] <= 0.03),
        ('FLIP_TIGHT R1 OR R2 (ensemble)',
            lambda e: (e['cv'] >= 0.95 and (e['v1_ask'] or 0) >= 0.01 and (e['r_fdp'] or 1) <= 0.7)
                     or (e['udp'] >= 1000 and e['fdp'] >= 3000 and e['ask'] <= 0.03)),
        ('FLIP_MEDIUM (cv≥0.94 + fdp≥500 + udp≥300)',
            lambda e: e['cv'] >= 0.94 and e['fdp'] >= 500 and e['udp'] >= 300 and e['ask'] <= 0.10),
        ('WIDE (cv≥0.90)',
            lambda e: e['cv'] >= 0.90),
        ('ALL CHEAP (baseline)',
            lambda e: True),
    ]
    test_rules(events, base_rules)

    # Explore 2-atom space with v2-cached features
    print("\n" + "="*100)
    print("🔬 2-ATOM RULE SEARCH (fast — using pre-computed v1/r features)")
    print("="*100)

    thresh_grid = {
        'cv':      [(v, 'ge') for v in [0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98]],
        'udp':     [(v, 'ge') for v in [200, 300, 500, 1000, 1500, 2000]],
        'fdp':     [(v, 'ge') for v in [300, 500, 1000, 2000, 3000]] + [(v, 'le') for v in [300, 500, 1000]],
        'ratio':   [(v, 'ge') for v in [0.3, 0.5, 1, 2, 5]] + [(v, 'le') for v in [2, 5, 10]],
        'bn_abs':  [(v, 'ge') for v in [0.05, 0.10]],
        'v1_ask':  [(v, 'ge') for v in [0, 0.01, 0.02]],
        'r_fdp':   [(v, 'le') for v in [0.5, 0.7, 1.0]],
        'r_udp':   [(v, 'ge') for v in [1.0, 1.5, 2.0]],
        'ask':     [(v, 'le') for v in [0.03, 0.05, 0.07]],
    }

    # Build atoms (sets of (winner_idx, loser_idx))
    atoms = {}
    for feat, thrs in thresh_grid.items():
        for th, d in thrs:
            key = f"{feat}{'>=' if d == 'ge' else '<='}{th}"
            w = set(); l = set()
            for i, e in enumerate(events):
                v = e.get(feat)
                if v is None: continue
                if (d == 'ge' and v >= th) or (d == 'le' and v <= th):
                    if e['won']: w.add(i)
                    else:       l.add(i)
            atoms[key] = (w, l)

    # 2-atom search targeting WR >= 60% with market diversity >= 2
    print(f"\n2-atom rules (WR≥60%, ≥2 unique markets won):")
    print(f"{'Rule':<55} {'Win':<4} {'Lose':<5} {'WR%':<5} {'Mkts'}")
    keys = list(atoms.keys())
    best2 = []
    for k1, k2 in combinations(keys, 2):
        f1 = k1.split('>')[0].split('<')[0]
        f2 = k2.split('>')[0].split('<')[0]
        if f1 == f2: continue
        w1, l1 = atoms[k1]; w2, l2 = atoms[k2]
        ws = w1 & w2; ls = l1 & l2
        wh = len(ws); lh = len(ls); N = wh + lh
        if wh < 3 or N < 4: continue
        wr = wh / N
        if wr < 0.60: continue
        mkts = len(set((events[i]['slug'], events[i]['side']) for i in ws))
        if mkts < 2: continue
        best2.append((k1, k2, wh, lh, wr, mkts))
    best2.sort(key=lambda x: (x[4], x[5], x[2]), reverse=True)

    seen = set()
    for k1, k2, wh, lh, wr, mkts in best2:
        key = (round(wr, 2), wh, lh, mkts)
        if key in seen: continue
        seen.add(key)
        m = ' ⭐⭐' if wr >= 0.90 else ' ⭐' if wr >= 0.75 else ''
        print(f"  {k1} AND {k2:<25}  {wh:<4} {lh:<5} {int(100*wr):<5} {mkts}{m}")
        if len(seen) >= 20: break

    # 3-atom: tighten top 2-atom rules
    print(f"\n3-atom rules (WR≥75%, ≥2 unique markets won):")
    print(f"{'Rule':<80} {'Win':<4} {'Lose':<5} {'WR%':<5} {'Mkts'}")
    best3 = []
    for k1, k2, _, _, _, _ in best2[:40]:
        w1, l1 = atoms[k1]; w2, l2 = atoms[k2]
        for k3 in keys:
            if k3 in (k1, k2): continue
            f1 = k1.split('>')[0].split('<')[0]
            f2 = k2.split('>')[0].split('<')[0]
            f3 = k3.split('>')[0].split('<')[0]
            if f3 in (f1, f2): continue
            w3, l3 = atoms[k3]
            ws = w1 & w2 & w3; ls = l1 & l2 & l3
            wh = len(ws); lh = len(ls); N = wh + lh
            if wh < 3 or N < 4: continue
            wr = wh / N
            if wr < 0.75: continue
            mkts = len(set((events[i]['slug'], events[i]['side']) for i in ws))
            if mkts < 2: continue
            best3.append((k1, k2, k3, wh, lh, wr, mkts))
    best3.sort(key=lambda x: (x[5], x[6], x[3]), reverse=True)

    seen = set()
    for k1, k2, k3, wh, lh, wr, mkts in best3:
        key = (round(wr, 2), wh, lh, mkts)
        if key in seen: continue
        seen.add(key)
        m = ' ⭐⭐' if wr >= 0.90 else ' ⭐' if wr >= 0.80 else ''
        rule_str = f"{k1} AND {k2} AND {k3}"
        print(f"  {rule_str:<80}  {wh:<4} {lh:<5} {int(100*wr):<5} {mkts}{m}")
        if len(seen) >= 15: break

    print("\n" + "="*100)
    print("✅ Analysis complete. v2 cached velocities made this ~3-5x faster than v1 recompute path.")
    print("="*100)


if __name__ == '__main__':
    main()
