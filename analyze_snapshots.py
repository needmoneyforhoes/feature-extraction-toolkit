#!/usr/bin/env python3
"""
Example: analyze market snapshots extracted by extract_market_snapshots.py

Shows how to use the rich per-tick indicators (depth, sr, zc, trat, etc.) to
search for T4-nonfiring strategies.

USAGE:
  python3 analyze_snapshots.py market_snapshots.jsonl
"""

import json
import sys


def classify(rec):
    """Classify market using lc_final and flip_final from snapshot."""
    lc = rec.get('lc_final', 0) or 0
    flipped = rec.get('flip_final', False)
    bn = rec.get('bn_final', 0) or 0
    if lc >= 4:
        return 'T4'
    if lc == 0 and not flipped:
        return 'T1' if abs(bn) > 0.06 else 'T6'
    if lc == 0 and flipped:
        return 'T6'
    if 1 <= lc <= 3 and not flipped:
        return 'T2'
    if 1 <= lc <= 3 and flipped:
        return 'T3'
    return 'unknown'


def is_t4_nonfiring(rec):
    """T4 markets where main conviction at T-120 doesn't fire (cv < 0.75)."""
    if classify(rec) != 'T4':
        return False
    b = rec.get('bk', {}).get('T-120') or {}
    cv = b.get('cv', 0) or 0
    cs = b.get('cs')
    return not (cv >= 0.75 and cs in ('UP', 'DN'))


def eval_rule(rule_fn, records):
    """rule_fn(rec) → (side, entry_price) or None. Returns (fires, wins, pnl)."""
    fires, wins, pnl = 0, 0, 0
    for r in records:
        result = rule_fn(r)
        if result is None:
            continue
        side, entry = result
        fires += 1
        if side == r.get('winner'):
            wins += 1
            shares = 1.0 / (entry + 0.01)
            pnl += shares * (1.0 - entry - 0.01)
        else:
            pnl += -1.0
    return fires, wins, pnl


def fmt(r):
    if r[0] == 0:
        return "N=0"
    return f"N={r[0]} W={r[1]} {100*r[1]/r[0]:.0f}% ${r[2]/r[0]:+.2f}"


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} market_snapshots.jsonl", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        records = [json.loads(l) for l in f if l.strip()]

    print(f"Loaded {len(records)} market snapshots\n")

    # Show classification breakdown
    from collections import Counter
    types = Counter(classify(r) for r in records)
    print("Market type distribution:")
    for t, n in sorted(types.items()):
        print(f"  {t}: {n} ({100*n/len(records):.0f}%)")
    print()

    # Find T4-nonfiring
    t4_nf = [r for r in records if is_t4_nonfiring(r)]
    print(f"T4 non-firing (target for new strategies): {len(t4_nf)} markets")
    print()

    # Split train/test 70/30
    records_sorted = sorted(records, key=lambda r: r.get('ts', ''))
    split = int(len(records_sorted) * 0.7)
    train_slugs = set(r['slug'] for r in records_sorted[:split])
    t4_nf_train = [r for r in t4_nf if r['slug'] in train_slugs]
    t4_nf_test = [r for r in t4_nf if r['slug'] not in train_slugs]
    print(f"Train: {len(t4_nf_train)} | Test: {len(t4_nf_test)}")
    print()

    # ── RULE 1: depth imbalance at T-120 ──
    # The side with deeper book at T-120 might be more "committed"
    print("=" * 80)
    print("RULE 1: depth imbalance at T-120 (ud vs dd)")
    print("=" * 80)

    def depth_rule(rec, ratio):
        b = rec.get('bk', {}).get('T-120') or {}
        ud = b.get('ud', 0) or 0
        dd = b.get('dd', 0) or 0
        if ud == 0 or dd == 0:
            return None
        if ud / dd > ratio:
            side = 'UP'
            entry = b.get('ua', 0.65) or 0.65
        elif dd / ud > ratio:
            side = 'DN'
            entry = b.get('da', 0.65) or 0.65
        else:
            return None
        return side, entry

    print(f"  {'Ratio':<10} {'TRAIN':<22} {'TEST':<22}")
    for ratio in [1.2, 1.5, 2.0, 3.0, 5.0]:
        tr = eval_rule(lambda r, x=ratio: depth_rule(r, x), t4_nf_train)
        te = eval_rule(lambda r, x=ratio: depth_rule(r, x), t4_nf_test)
        print(f"  {ratio:<10} {fmt(tr):<22} {fmt(te):<22}")

    # ── RULE 2: spike ratio at T-120 ──
    # High spike ratio on one side = pressure on that side
    print()
    print("=" * 80)
    print("RULE 2: spike_ratio at T-120 (usr vs dsr)")
    print("=" * 80)

    def sr_rule(rec, thresh):
        b = rec.get('bk', {}).get('T-120') or {}
        usr = b.get('usr', 0) or 0
        dsr = b.get('dsr', 0) or 0
        # Hypothesis: high spike = crushed (contrarian buy)
        if usr > thresh and usr > dsr + 1.0:
            side = 'DN'
            entry = b.get('da', 0.65) or 0.65
        elif dsr > thresh and dsr > usr + 1.0:
            side = 'UP'
            entry = b.get('ua', 0.65) or 0.65
        else:
            return None
        return side, entry

    print(f"  {'Threshold':<12} {'TRAIN':<22} {'TEST':<22}")
    for thresh in [2, 3, 5, 8, 10]:
        tr = eval_rule(lambda r, x=thresh: sr_rule(r, x), t4_nf_train)
        te = eval_rule(lambda r, x=thresh: sr_rule(r, x), t4_nf_test)
        print(f"  {thresh:<12} {fmt(tr):<22} {fmt(te):<22}")

    # ── RULE 3: trade ratio (depth-flip indicator from T5) ──
    print()
    print("=" * 80)
    print("RULE 3: trade ratio (cheap/exp) at T-120")
    print("=" * 80)

    def trat_rule(rec, thresh):
        b = rec.get('bk', {}).get('T-120') or {}
        trat = b.get('trat', 0) or 0
        # High trat = cheap side getting bought = reversal coming (buy cheap side)
        if trat > thresh:
            # Which side is cheap?
            ua = b.get('ua', 0.5) or 0.5
            da = b.get('da', 0.5) or 0.5
            if ua < da:
                side = 'UP'
                entry = ua
            else:
                side = 'DN'
                entry = da
            return side, entry
        return None

    print(f"  {'Threshold':<12} {'TRAIN':<22} {'TEST':<22}")
    for thresh in [1.0, 1.5, 2.0, 3.0, 5.0]:
        tr = eval_rule(lambda r, x=thresh: trat_rule(r, x), t4_nf_train)
        te = eval_rule(lambda r, x=thresh: trat_rule(r, x), t4_nf_test)
        print(f"  {thresh:<12} {fmt(tr):<22} {fmt(te):<22}")

    # ── RULE 4: depth velocity at T-120 ──
    print()
    print("=" * 80)
    print("RULE 4: depth velocity at T-120 (dvu, dvd)")
    print("=" * 80)
    print("(requires more data — leaving skeleton)")
    print()

    # ── RULE 5: combined depth + crowd at T-120 ──
    print("=" * 80)
    print("RULE 5: COMBINED — crowd side + deep depth on crowd side")
    print("=" * 80)

    def combo_rule(rec, cv_min, depth_ratio):
        b = rec.get('bk', {}).get('T-120') or {}
        cv = b.get('cv', 0) or 0
        cs = b.get('cs')
        if cv < cv_min or cs not in ('UP', 'DN'):
            return None
        ud = b.get('ud', 0) or 0
        dd = b.get('dd', 0) or 0
        if ud == 0 or dd == 0:
            return None
        # Crowd picks a side AND that side has deeper book
        if cs == 'UP' and ud / dd >= depth_ratio:
            return 'UP', b.get('ua', 0.65) or 0.65
        if cs == 'DN' and dd / ud >= depth_ratio:
            return 'DN', b.get('da', 0.65) or 0.65
        return None

    print(f"  {'cv_min':<8} {'dratio':<8} {'TRAIN':<22} {'TEST':<22}")
    for cv_min in [0.55, 0.60, 0.65, 0.70]:
        for dratio in [1.0, 1.3, 1.5, 2.0]:
            tr = eval_rule(lambda r, c=cv_min, d=dratio: combo_rule(r, c, d), t4_nf_train)
            te = eval_rule(lambda r, c=cv_min, d=dratio: combo_rule(r, c, d), t4_nf_test)
            if tr[0] >= 3 and te[0] >= 3:
                marker = ""
                if tr[0] > 0 and te[0] > 0:
                    tr_wr = tr[1] / tr[0]
                    te_wr = te[1] / te[0]
                    if tr_wr >= 0.80 and te_wr >= 0.80 and tr[2] > 0 and te[2] > 0:
                        marker = " ⭐"
                    elif tr_wr >= 0.75 and te_wr >= 0.75:
                        marker = " 🟡"
                print(f"  {cv_min:<8} {dratio:<8} {fmt(tr):<22} {fmt(te):<22}{marker}")

    print()
    print("This is a TEMPLATE — run on a larger snapshot file (100+ markets)")
    print("to find rules with enough statistical power to validate.")


if __name__ == '__main__':
    main()
