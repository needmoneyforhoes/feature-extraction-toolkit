#!/usr/bin/env python3
"""
ASYMMETRY RESEARCH SCRIPT
=========================
Tests whether the UP/DN crash-timing asymmetry is a profitable signal.

Accepts EITHER:
  - A single JSONL file (one market per line, with 'ticks' field)
  - A directory of replay_*.json files (one per market)

Run:
  python3 analyze_asymmetry.py /path/to/market_history.jsonl
  python3 analyze_asymmetry.py /path/to/replay_directory/
"""
import json
import os
import sys
import statistics
from collections import defaultdict


def load_markets(path):
    """Load markets from either a JSONL file or a directory of replay JSONs.
    Skip markets that don't have tick data (e.g., 'lite' versions)."""
    markets = []
    skipped_no_ticks = 0
    
    if os.path.isdir(path):
        files = sorted(f for f in os.listdir(path) if f.startswith("replay_") and f.endswith(".json"))
        print(f"Loading {len(files)} replay files from directory {path}...")
        for fname in files:
            try:
                with open(os.path.join(path, fname)) as f:
                    data = json.load(f)
                if data.get("ticks"):
                    markets.append(data)
                else:
                    skipped_no_ticks += 1
            except Exception as e:
                print(f"  Skipping {fname}: {e}")
    elif os.path.isfile(path):
        print(f"Loading markets from JSONL file {path}...")
        line_no = 0
        try:
            with open(path) as f:
                for line in f:
                    line_no += 1
                    if not line.strip(): continue
                    try:
                        data = json.loads(line)
                        if data.get("ticks"):
                            markets.append(data)
                        else:
                            skipped_no_ticks += 1
                    except json.JSONDecodeError as e:
                        print(f"  Skipping line {line_no}: {e}")
        except Exception as e:
            print(f"Error reading file: {e}")
            sys.exit(1)
    else:
        print(f"Error: {path} is neither a file nor a directory.")
        sys.exit(1)
    
    print(f"Loaded {len(markets)} markets with tick data.")
    if skipped_no_ticks > 0:
        print(f"⚠️  Skipped {skipped_no_ticks} markets without 'ticks' field "
              f"(this is the 'lite' format — needs full market_history.jsonl with raw ticks).")
    
    if len(markets) == 0:
        print()
        print("="*72)
        print("NO MARKETS WITH TICK DATA FOUND")
        print("="*72)
        print()
        print("The file you provided has no 'ticks' field in any market.")
        print()
        print("This is likely a 'lite' export. The bot generates two files per market:")
        print("  - market_history_lite.jsonl  (slim, no ticks)")
        print("  - market_history.jsonl       (full, with raw ticks)")
        print()
        print("On your VPS, look for individual replay_*.json files instead:")
        print("  $ ls ./replays/replay_btc-updown-5m-*.json")
        print()
        print("Then run:")
        print("  $ python3 analyze_asymmetry.py ./replays/")
        print()
        sys.exit(1)
    
    return markets


def compute_microstructure_stats(markets):
    """Stat #1: cross-market timing of price collapses."""
    print("\n" + "="*100)
    print("MICROSTRUCTURE STATS: when does each side crash to ≤$0.05?")
    print("="*100)
    
    dn_crash_cds = []
    up_crash_cds = []
    dn_winner_count = 0
    up_winner_count = 0
    
    for m in markets:
        winner = m.get("winner")
        ticks = m.get("ticks") or []
        if not ticks: continue
        TC = {col: i for i, col in enumerate(m["tick_columns"])}
        
        first_dn_crash = None
        first_up_crash = None
        for t in ticks:
            cd = t[TC["cd"]]
            dn = t[TC["dn_ask"]] if t[TC["dn_ask"]] else 0
            up = t[TC["up_ask"]] if t[TC["up_ask"]] else 0
            if dn > 0 and dn <= 0.05 and first_dn_crash is None:
                first_dn_crash = cd
            if up > 0 and up <= 0.05 and first_up_crash is None:
                first_up_crash = cd
            if first_dn_crash is not None and first_up_crash is not None:
                break
        
        if first_dn_crash is not None: dn_crash_cds.append(first_dn_crash)
        if first_up_crash is not None: up_crash_cds.append(first_up_crash)
        if winner == "DN": dn_winner_count += 1
        elif winner == "UP": up_winner_count += 1
    
    print(f"\nWinner distribution:")
    print(f"  UP winners: {up_winner_count} ({up_winner_count/len(markets)*100:.1f}%)")
    print(f"  DN winners: {dn_winner_count} ({dn_winner_count/len(markets)*100:.1f}%)")
    
    if dn_crash_cds:
        print(f"\nDN side crashes (n={len(dn_crash_cds)} markets where DN reached ≤$0.05):")
        print(f"  Median CD: {statistics.median(dn_crash_cds):.1f}s")
        print(f"  Max CD:    {max(dn_crash_cds):.1f}s")
        print(f"  Min CD:    {min(dn_crash_cds):.1f}s")
        print(f"  CD ≥ 25s:  {sum(1 for c in dn_crash_cds if c >= 25)} ({sum(1 for c in dn_crash_cds if c >= 25)/len(dn_crash_cds)*100:.1f}%)")
        print(f"  CD ≥ 60s:  {sum(1 for c in dn_crash_cds if c >= 60)} ({sum(1 for c in dn_crash_cds if c >= 60)/len(dn_crash_cds)*100:.1f}%)")
    
    if up_crash_cds:
        print(f"\nUP side crashes (n={len(up_crash_cds)} markets where UP reached ≤$0.05):")
        print(f"  Median CD: {statistics.median(up_crash_cds):.1f}s")
        print(f"  Max CD:    {max(up_crash_cds):.1f}s")
        print(f"  Min CD:    {min(up_crash_cds):.1f}s")
        print(f"  CD ≥ 25s:  {sum(1 for c in up_crash_cds if c >= 25)} ({sum(1 for c in up_crash_cds if c >= 25)/len(up_crash_cds)*100:.1f}%)")
        print(f"  CD ≥ 60s:  {sum(1 for c in up_crash_cds if c >= 60)} ({sum(1 for c in up_crash_cds if c >= 60)/len(up_crash_cds)*100:.1f}%)")


def test_strategy_h1(markets, up_thresh, cd_min, max_dn_entry, br=25.0):
    """H1: when up_ask ≤ X AND cd ≥ Y → BUY DN (signal = early UP collapse)"""
    fires = []
    for m in markets:
        winner = m.get("winner")
        ticks = m.get("ticks") or []
        if not ticks: continue
        TC = {col: i for i, col in enumerate(m["tick_columns"])}
        
        for t in ticks:
            cd = t[TC["cd"]]
            dn = t[TC["dn_ask"]] if t[TC["dn_ask"]] else 0
            up = t[TC["up_ask"]] if t[TC["up_ask"]] else 0
            if (up > 0 and up <= up_thresh 
                and cd >= cd_min
                and dn > 0 and dn <= max_dn_entry):
                shares = 5
                cost = shares * dn
                if cost < 1.00:
                    bumped = max(15, min(30, int(0.05 * br / dn)))
                    cost = bumped * dn
                    if cost < 1.00:
                        break
                    shares = bumped
                
                pnl = (shares * (1.0 - dn)) if winner == "DN" else -cost
                fires.append({"slug": m.get("slug", "?"), "cd": cd, "dn": dn, "up": up,
                              "shares": shares, "winner": winner, "pnl": pnl})
                break
    return fires


def test_strategy_h2(markets, dn_thresh, cd_min, max_up_entry, br=25.0):
    """H2 (mirror): when dn_ask ≤ X AND cd ≥ Y → BUY UP"""
    fires = []
    for m in markets:
        winner = m.get("winner")
        ticks = m.get("ticks") or []
        if not ticks: continue
        TC = {col: i for i, col in enumerate(m["tick_columns"])}
        
        for t in ticks:
            cd = t[TC["cd"]]
            dn = t[TC["dn_ask"]] if t[TC["dn_ask"]] else 0
            up = t[TC["up_ask"]] if t[TC["up_ask"]] else 0
            if (dn > 0 and dn <= dn_thresh 
                and cd >= cd_min
                and up > 0 and up <= max_up_entry):
                shares = 5
                cost = shares * up
                if cost < 1.00:
                    bumped = max(15, min(30, int(0.05 * br / up)))
                    cost = bumped * up
                    if cost < 1.00:
                        break
                    shares = bumped
                
                pnl = (shares * (1.0 - up)) if winner == "UP" else -cost
                fires.append({"slug": m.get("slug", "?"), "cd": cd, "dn": dn, "up": up,
                              "shares": shares, "winner": winner, "pnl": pnl})
                break
    return fires


def grid_search_strategy(markets, hypothesis_name, fn, param_grid, min_fires=5):
    """Run param grid search and report best."""
    print(f"\n{'='*100}")
    print(f"GRID SEARCH: {hypothesis_name}")
    print('='*100)
    print(f"{'Params':<60}{'Fires':<8}{'Total':<12}{'WinRate':<10}{'Avg/fire':<10}{'Sharpe':<10}{'Status'}")
    print("-"*120)
    
    results = []
    for params in param_grid:
        fires = fn(markets, *params)
        n = len(fires)
        if n < min_fires: continue
        pnls = [f["pnl"] for f in fires]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / n
        avg = total / n
        sd = statistics.stdev(pnls) if n > 1 else 1
        sharpe = avg / sd if sd > 0 else 0
        results.append((params, n, total, wr, avg, sharpe))
    
    results.sort(key=lambda x: -x[2])
    for params, n, total, wr, avg, sharpe in results[:20]:
        params_str = f"{params}"[:55]
        # Status classification
        if total >= 10 and wr >= 0.60 and sharpe >= 0.10 and n >= 30:
            status = "🟢 PASS — add as SHADOW"
        elif total >= 5 and sharpe >= 0.05 and n >= 20:
            status = "🟡 PROMISING — needs more data"
        elif total > 0:
            status = "🟠 marginal positive"
        else:
            status = "🔴 negative — drop"
        print(f"  {params_str:<60}{n:<8}${total:+<11.2f}{wr*100:<9.0f}%${avg:+<9.2f}{sharpe:+<9.3f}{status}")
    
    return results


def show_detail(markets, fn, params):
    """Show fire-by-fire detail for the top config."""
    fires = fn(markets, *params)
    print(f"\nDetailed fires ({len(fires)}):")
    print(f"{'Slug':<30}{'cd':<8}{'dn':<8}{'up':<8}{'winner':<8}{'shares':<8}{'PnL':<10}")
    print("-"*90)
    for f in fires[:30]:
        marker = "✅" if f["pnl"] > 0 else "❌"
        slug = f["slug"][-25:] if len(f["slug"]) > 25 else f["slug"]
        print(f"  {slug:<28}{f['cd']:<7.1f} ${f['dn']:<6.3f} ${f['up']:<6.3f} {f['winner']:<7}{f['shares']:<8}${f['pnl']:+<8.2f} {marker}")
    if len(fires) > 30:
        print(f"  ... and {len(fires) - 30} more")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <jsonl_file_or_replay_dir>")
        print()
        print("Examples:")
        print(f"  {sys.argv[0]} ./market_history.jsonl")
        print(f"  {sys.argv[0]} ./replays/")
        sys.exit(1)
    
    path = sys.argv[1]
    markets = load_markets(path)
    
    # Stat 1: microstructure
    compute_microstructure_stats(markets)
    
    # H1: early UP collapse → buy DN
    h1_grid = [
        (ut, cd, mdn)
        for ut in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
        for cd in [60, 90, 120, 150, 200, 240]
        for mdn in [0.30, 0.50, 0.70, 0.85, 0.95]
    ]
    h1_results = grid_search_strategy(markets, "H1: early UP collapse → buy DN",
                                       test_strategy_h1, h1_grid)
    
    # H2: mirror — early DN collapse → buy UP
    h2_grid = [
        (dt, cd, mup)
        for dt in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
        for cd in [60, 90, 120, 150, 200, 240]
        for mup in [0.30, 0.50, 0.70, 0.85, 0.95]
    ]
    h2_results = grid_search_strategy(markets, "H2: early DN collapse → buy UP (mirror)",
                                       test_strategy_h2, h2_grid)
    
    # Top configs detail
    if h1_results and h1_results[0][2] > 0:
        print("\n" + "="*100)
        print("H1 TOP CONFIG DETAIL")
        print("="*100)
        top = h1_results[0]
        print(f"\nConfig: UP ≤ ${top[0][0]:.2f}, CD ≥ {top[0][1]}s, DN entry ≤ ${top[0][2]:.2f}")
        show_detail(markets, test_strategy_h1, top[0])
    
    if h2_results and h2_results[0][2] > 0:
        print("\n" + "="*100)
        print("H2 TOP CONFIG DETAIL")
        print("="*100)
        top = h2_results[0]
        print(f"\nConfig: DN ≤ ${top[0][0]:.2f}, CD ≥ {top[0][1]}s, UP entry ≤ ${top[0][2]:.2f}")
        show_detail(markets, test_strategy_h2, top[0])
    
    print("\n" + "="*100)
    print("INTERPRETATION GUIDE")
    print("="*100)
    print("""
    🟢 PASS criteria (add as SHADOW strategy):
       Total PnL ≥ +$10  AND  win rate ≥ 60%  AND  Sharpe ≥ +0.10  AND  n ≥ 30
    
    🟡 PROMISING:
       Total ≥ +$5  AND  Sharpe ≥ +0.05  AND  n ≥ 20  → run on more markets
    
    🔴 DROP if total ≤ $0 or Sharpe < 0.
    
    NEXT STEP: 
      1. If a config 🟢 PASSes, add it as a SHADOW strategy in the bot
      2. Wait for 30+ shadow fires to confirm baseline
      3. SPRT pipeline auto-promotes to PROBATION → LIVE if μ holds up
      4. NEVER bypass SHADOW — historical data must prove out in real LIVE
    """)


if __name__ == "__main__":
    main()
