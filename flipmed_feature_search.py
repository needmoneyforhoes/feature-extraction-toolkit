#!/usr/bin/env python3
"""
flipmed_feature_search.py — Find the best indicator that would let flip_medium
fire on its CURRENT skips and capture more wins.

WHAT IT DOES
  Walks all race_test_btc-updown-5m-*.log files, finds every flip_medium SKIPPED
  event (the rule matched but state filters blocked), pulls the market winner,
  and labels each skip as:
    - "MISSED_WIN":  side==winner → should have fired (we left money on table)
    - "GOOD_SKIP":   side!=winner → correctly avoided losing fire

  Then for each skip, extracts ~20 features at skip time (price context, signal
  context, BN velocity over multiple windows, depth ratios). For every numeric
  feature, sweeps thresholds to find the one that BEST separates MISSED_WINS
  from GOOD_SKIPS — same scoring as cusp_feature_search.py.

USAGE
  cd ~/polymarket-bot
  python3 flipmed_feature_search.py

OUTPUT
  - Skip catalog (each skipped attempt + outcome)
  - Per-side W/L breakdown
  - Single-feature separator search ranked by quality
  - Estimated PnL impact of relaxing flip_medium with each candidate filter

DOES NOT MODIFY ANY FILES.
"""

import os
import re
import sys
import glob
from collections import defaultdict, Counter

# ── Regexes ──────────────────────────────────────────────────────────────────
RE_FLIPMED_SKIP = re.compile(
    r'\[v5-flipmed\] base-rule matched but state filter failed '
    r'\((UP|DN)\): (.+?) — SKIPPED'
)
RE_FLIPMED_FIRE = re.compile(
    r'\[v5-flipmed\] 🔔 FLIP MEDIUM at cd=(\d+(?:\.\d+)?): '
    r'(UP|DN) ask=\$(\d+\.\d+)'
)
RE_PRICE = re.compile(
    r'\[price\] (\d+(?:\.\d+)?)s \| UP bid=(\d+\.\d+) ask=(\d+\.\d+) \| '
    r'DN bid=(\d+\.\d+) ask=(\d+\.\d+) \| ask_sum=(\d+\.\d+) bid_sum=(\d+\.\d+) \| '
    r'Δ=([+-]?\d+\.\d+)%'
)
RE_SIGNAL = re.compile(
    r'\[signal\] (\d+(?:\.\d+)?)s \| crowd=(\w+) \| conv=(\d+\.\d+) \| '
    r'vel=([+-]?\d+\.\d+) \| ema_up=(\d+\.\d+) \| ema_dn=(\d+\.\d+) \| '
    r'Δ3s_up=([+-]?\d+\.\d+) \| Δ3s_dn=([+-]?\d+\.\d+) \| '
    r'Δ10s_up=([+-]?\d+\.\d+) \| Δ10s_dn=([+-]?\d+\.\d+)'
)
# Reason fields parsed from skip line
RE_RFDP   = re.compile(r'r_fdp=(\d+\.\d+)')
RE_BNABS  = re.compile(r'bn_abs=(\d+\.\d+)')
# Get bn_pct from the price line (Δ field) AND signal-line context
# bn_pct is the BTC delta % — sign tells direction


def parse_log(path):
    """Find every flip_medium skip + its market context + outcome."""
    skips = []
    fires = []  # successful fires (rare in shadow, but possible)
    bn_history = []  # (cd, bn_pct) for velocity computation
    last_price = None
    last_signal = None

    try:
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return [], []

    # Find market winner
    winner = None
    for L in lines:
        m = re.search(r'winner=(UP|DN)', L)
        if m:
            winner = m.group(1)
            break
    if not winner:
        return [], []

    for L in lines:
        m = RE_PRICE.search(L)
        if m:
            (cd_p, ub_up, ask_up, ub_dn, ask_dn, ask_sum, bid_sum, btc_pct) = m.groups()
            last_price = {
                'cd': float(cd_p),
                'up_bid': float(ub_up), 'up_ask': float(ask_up),
                'dn_bid': float(ub_dn), 'dn_ask': float(ask_dn),
                'ask_sum': float(ask_sum), 'bid_sum': float(bid_sum),
                'btc_pct': float(btc_pct),
            }
            # Track BN trajectory for velocity
            bn_history.append((float(cd_p), float(btc_pct)))
            continue

        m = RE_SIGNAL.search(L)
        if m:
            (cd_s, crowd, conv, vel, ema_up, ema_dn,
             d3up, d3dn, d10up, d10dn) = m.groups()
            last_signal = {
                'crowd': crowd, 'conv': float(conv), 'vel': float(vel),
                'ema_up': float(ema_up), 'ema_dn': float(ema_dn),
                'd3s_up': float(d3up), 'd3s_dn': float(d3dn),
                'd10s_up': float(d10up), 'd10s_dn': float(d10dn),
            }
            continue

        m = RE_FLIPMED_SKIP.search(L)
        if m:
            side, reason = m.groups()
            r_fdp_m = RE_RFDP.search(reason)
            bn_abs_m = RE_BNABS.search(reason)
            skip = {
                'log': os.path.basename(path),
                'winner': winner,
                'side': side,
                'reason': reason,
                'r_fdp': float(r_fdp_m.group(1)) if r_fdp_m else None,
                'bn_abs': float(bn_abs_m.group(1)) if bn_abs_m else None,
                'cd_skip': last_price['cd'] if last_price else None,
            }
            if last_price:
                skip.update({k: v for k, v in last_price.items() if k != 'cd'})
            if last_signal:
                skip.update(last_signal)
            # Compute BN velocity over 30s window
            if last_price and bn_history:
                cd_now = last_price['cd']
                # Find tick ~30s ago
                back = [(c, b) for c, b in bn_history if abs(c - (cd_now + 30)) < 5]
                if back:
                    bn_now = last_price['btc_pct']
                    bn_back = back[0][1]
                    skip['bn_velocity_30s'] = (bn_now - bn_back) / 30
                    skip['bn_30s_back'] = bn_back
                else:
                    skip['bn_velocity_30s'] = None
                    skip['bn_30s_back'] = None
            skips.append(skip)
            continue

        m = RE_FLIPMED_FIRE.search(L)
        if m:
            cd, side, ask = m.groups()
            fires.append({
                'log': os.path.basename(path),
                'winner': winner,
                'cd': float(cd), 'side': side, 'ask': float(ask),
            })

    return skips, fires


def add_derived(s):
    side_sign = 1 if s['side'] == 'UP' else -1
    if s.get('vel') is not None:
        s['vel_with_bet'] = s['vel'] * side_sign
    if s.get('bn_velocity_30s') is not None:
        s['bn_velocity_with_bet'] = s['bn_velocity_30s'] * side_sign * 1000  # scale for readability
    if 'd10s_up' in s and 'd10s_dn' in s:
        s['d10s_with_bet'] = (s['d10s_up'] - s['d10s_dn']) * side_sign
    if 'd3s_up' in s and 'd3s_dn' in s:
        s['d3s_with_bet'] = (s['d3s_up'] - s['d3s_dn']) * side_sign
    if s.get('btc_pct') is not None:
        s['btc_pct_with_bet'] = s['btc_pct'] * side_sign  # positive = BTC moving toward our bet
    if 'ema_up' in s and 'ema_dn' in s:
        s['ema_with_bet'] = (s['ema_up'] - s['ema_dn']) * side_sign
    return s


def evaluate_threshold(skips, feature, threshold, direction, side_filter=None):
    """Apply rule: KEEP skip's-rejection-decision if feature {direction} threshold.
    direction '<=' or '>=' — if matched, the skip is RELAXED (would now fire).
    Score MISSED_WINS that get fired (good) and GOOD_SKIPS that stay blocked (good)."""
    rec = {'fired_win': 0, 'fired_loss': 0, 'kept_skip_loss': 0, 'kept_skip_win': 0}
    pnl = 0.0
    for s in skips:
        if side_filter and s['side'] != side_filter:
            continue
        v = s.get(feature)
        if v is None:
            continue
        is_winner_side = s['side'] == s['winner']  # MISSED_WIN if true
        if direction == '>=':
            relax = v >= threshold
        else:
            relax = v <= threshold
        # Compute fire-time PnL for the skipped opportunity (hold-to-settle 5 shares)
        ask = s.get('up_ask' if s['side']=='UP' else 'dn_ask', 0.5)
        cost = 5 * (ask + 0.01)
        per_fire = (5 * 1.00 - cost) if is_winner_side else (-cost)
        if relax:
            # Now fires — record outcome
            if is_winner_side:
                rec['fired_win'] += 1
            else:
                rec['fired_loss'] += 1
            pnl += per_fire
        else:
            # Stays skipped — outcome doesn't affect PnL
            if is_winner_side:
                rec['kept_skip_win'] += 1  # missed opportunity stays missed
            else:
                rec['kept_skip_loss'] += 1  # correctly avoided
    score = rec['fired_win'] * 10 + rec['kept_skip_loss'] * 2 - rec['fired_loss'] * 5
    return rec, pnl, score


def find_best_threshold(skips, feature, side_filter=None):
    vals = sorted(set(s[feature] for s in skips
                      if s.get(feature) is not None
                      and (not side_filter or s['side'] == side_filter)))
    if len(vals) < 2:
        return None
    candidates = list(vals)
    for i in range(len(vals) - 1):
        candidates.append((vals[i] + vals[i+1]) / 2)
    best = None
    for t in candidates:
        for d in ('>=', '<='):
            rec, pnl, score = evaluate_threshold(skips, feature, t, d, side_filter)
            if best is None or score > best[0]:
                best = (score, t, d, rec, pnl)
    return best


def main():
    log_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    pattern = os.path.join(log_dir, 'race_test_btc-updown-5m-*.log')
    log_files = sorted(glob.glob(pattern))
    if not log_files:
        print(f"❌ No race_test_*.log files in {log_dir!r}")
        sys.exit(1)

    print(f"📂 Scanning {len(log_files)} log files for flip_medium activity...")

    all_skips = []
    all_fires = []
    for path in log_files:
        skips, fires = parse_log(path)
        for s in skips:
            add_derived(s)
            all_skips.append(s)
        all_fires.extend(fires)

    print(f"🔍 flip_medium SKIPPED events: {len(all_skips)}")
    print(f"🎯 flip_medium FIRED events:   {len(all_fires)}")
    if all_fires:
        for f in all_fires[:10]:
            print(f"    cd={f['cd']:.0f}  {f['side']} ask=${f['ask']:.3f}  log={f['log']}")
    print()

    if not all_skips:
        print("No skips to analyze.")
        sys.exit(0)

    # Per-market skip-outcome summary
    by_market = defaultdict(list)
    for s in all_skips:
        by_market[s['log']].append(s)
    missed_win_markets = sum(1 for log, skips in by_market.items()
                             if any(s['side'] == s['winner'] for s in skips))
    print(f"📊 Markets with at least one MISSED_WIN: {missed_win_markets}/{len(by_market)}")

    # Side breakdown
    by_outcome = Counter()
    for s in all_skips:
        out = "MISSED_WIN" if s['side'] == s['winner'] else "GOOD_SKIP"
        by_outcome[out] += 1
    print(f"   - MISSED_WIN skips: {by_outcome['MISSED_WIN']} (UP-or-DN side matched winner)")
    print(f"   - GOOD_SKIP  skips: {by_outcome['GOOD_SKIP']} (correctly avoided losing fire)")
    print()

    # Hypothetical PnL of "relax all skips" baseline
    print("=" * 110)
    print("Baseline — what if flip_medium fired EVERY skip (no filter at all)?")
    print("=" * 110)
    rec, pnl, _ = evaluate_threshold(all_skips, 'r_fdp', 9999, '<=')  # always-true
    print(f"  Fires: {rec['fired_win']+rec['fired_loss']}  ({rec['fired_win']}W/{rec['fired_loss']}L)  hypo=${pnl:+.2f}")
    print()

    # Single-feature separator search
    excluded = {'cd', 'cd_skip', 'log', 'winner', 'side', 'crowd', 'reason'}
    numeric_features = []
    for k in all_skips[0].keys():
        if k in excluded:
            continue
        v = all_skips[0].get(k)
        if isinstance(v, (int, float)):
            if all(isinstance(s.get(k), (int, float)) for s in all_skips if s.get(k) is not None):
                numeric_features.append(k)

    print("=" * 110)
    print(f"FEATURE SEARCH — what filter best separates MISSED_WINS from GOOD_SKIPS?")
    print("=" * 110)
    print(f"Score = fired_wins×10 + good_skips_kept×2 - fired_losses×5")
    print()
    results = []
    for feat in numeric_features:
        r = find_best_threshold(all_skips, feat)
        if r:
            results.append((feat, r))
    results.sort(key=lambda x: -x[1][0])

    print(f"{'feature':<22} {'rule':<28} {'fires':>5} {'W':>3} {'L':>3} {'kept':>5} "
          f"{'pnl':>8} {'score':>6}")
    print("-" * 90)
    for feat, (score, t, d, rec, pnl) in results[:15]:
        rule = f"{feat} {d} {t:.4f}"
        total_fired = rec['fired_win'] + rec['fired_loss']
        total_kept = rec['kept_skip_win'] + rec['kept_skip_loss']
        print(f"{feat:<22} {rule:<28} {total_fired:>5} {rec['fired_win']:>3} {rec['fired_loss']:>3} "
              f"{total_kept:>5} ${pnl:>+7.2f} {score:>6.1f}")
    print()

    print("=" * 110)
    print("HOW TO READ")
    print("=" * 110)
    print("Each row is a candidate filter. 'fires' = how many skipped opportunities")
    print("would now fire if you relaxed flip_medium with this rule. W/L = win/loss.")
    print("'kept' = how many skips would still be blocked. 'pnl' = hypo profit at")
    print("hold-to-settle 5-share sizing.")
    print()
    print("Look for filters with HIGH 'pnl' AND positive W/L ratio AND meaningful")
    print("'kept' count (means the filter is selective, not just letting everything through).")
    print()
    print("Don't deploy any filter with N<10 fires — it's overfit. Wait for more data.")


if __name__ == '__main__':
    main()
