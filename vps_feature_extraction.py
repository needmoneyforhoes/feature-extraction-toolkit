#!/usr/bin/env python3
"""
Run on VPS:
  cd /home/polybot/polymarket-bot
  python3 vps_feature_extraction.py
"""
import json, statistics, os
from collections import defaultdict

HISTORY_PATH = 'market_history.jsonl'
RECAP_PATH   = 'market_recap_history.jsonl'
OUT_PATH     = 'feature_matrix.json'

def safe_avg(lst):
    lst = [x for x in lst if x is not None]
    return sum(lst)/len(lst) if lst else None

def safe_std(lst):
    lst = [x for x in lst if x is not None]
    return statistics.stdev(lst) if len(lst) >= 2 else None

def safe_min(lst):
    lst = [x for x in lst if x is not None]
    return min(lst) if lst else None

def safe_max(lst):
    lst = [x for x in lst if x is not None]
    return max(lst) if lst else None

def safe_slope(ys):
    ys = [y for y in ys if y is not None]
    n  = len(ys)
    if n < 3: return None
    xs = list(range(n))
    xm = sum(xs)/n; ym = sum(ys)/n
    num = sum((xs[i]-xm)*(ys[i]-ym) for i in range(n))
    den = sum((xs[i]-xm)**2 for i in range(n))
    return num/den if den else None

def pct_above(lst, thr):
    lst = [x for x in lst if x is not None]
    return sum(1 for x in lst if x > thr)/len(lst) if lst else None

def pct_below(lst, thr):
    lst = [x for x in lst if x is not None]
    return sum(1 for x in lst if x < thr)/len(lst) if lst else None

def consec_above(lst, thr):
    lst = [x for x in lst if x is not None]
    best = cur = 0
    for x in lst:
        cur = cur+1 if x > thr else 0
        best = max(best, cur)
    return best

def fire_cat(f):
    if f.get('pre_gate_held') or f.get('opp_gate_held'):        return 'HELD'
    if f.get('opp_gate_would_block') or f.get('opp_gate_blocked'): return 'WBLOCK'
    return 'FREE'

def pnl(lst):
    return round(sum(f.get('hypo_pnl', 0) for f in lst), 4)

# ── load recap ────────────────────────────────────────────────────────────
print("Loading recap...")
recap = {}
with open(RECAP_PATH) as fh:
    for line in fh:
        d = json.loads(line)
        slug   = d.get('slug', '')
        winner = d.get('winner')
        fires  = d.get('fires', [])
        if not slug or winner not in ('UP', 'DN'):
            continue
        for f in fires:
            f['_cat'] = fire_cat(f)
        gc_up     = [f for f in fires if f['_cat']=='FREE'   and f['side']=='UP']
        gc_dn     = [f for f in fires if f['_cat']=='FREE'   and f['side']=='DN']
        held_dn   = [f for f in fires if f['_cat']=='HELD'   and f['side']=='DN']
        wblock_dn = [f for f in fires if f['_cat']=='WBLOCK' and f['side']=='DN']
        recap[slug] = {
            'winner':     winner,
            's0':         pnl(gc_up) + pnl(gc_dn),
            's1':         pnl(gc_dn),
            's2':         pnl(gc_dn) + pnl(held_dn),
            'gc_up_pnl':  pnl(gc_up),
        }
print(f"  {len(recap)} markets")

WINDOWS = {
    'entry':     (240, 310),
    'early':     (200, 240),
    'mid':       (160, 200),
    'late':      (120, 160),
    'very_late': ( 90, 120),
}

print("Extracting features...")
records = []

with open(HISTORY_PATH) as fh:
    for raw in fh:
        d      = json.loads(raw)
        slug   = d.get('slug', '')
        winner = d.get('winner')
        cols   = d.get('tick_columns', [])
        ticks  = d.get('ticks', [])
        mw     = d.get('market_wide') or {}

        if not slug or winner not in ('UP', 'DN') or not ticks or not cols:
            continue
        if slug not in recap:
            continue

        ci = {c: i for i, c in enumerate(cols)}
        feat = {'slug': slug, 'winner': winner}
        feat.update(recap[slug])

        # market-wide summary stats
        feat['mw_up_bid_std']     = mw.get('up_bid_std')
        feat['mw_dn_bid_std']     = mw.get('dn_bid_std')
        feat['mw_lead_changes']   = mw.get('lead_changes')
        feat['mw_time_near_5050'] = mw.get('time_near_5050')
        feat['mw_bn_delta_start'] = mw.get('bn_delta_start')
        feat['mw_bn_delta_min']   = mw.get('bn_delta_min')
        feat['mw_bn_delta_max']   = mw.get('bn_delta_max')
        feat['mw_up_depth_max']   = mw.get('up_depth_max')
        feat['mw_dn_depth_max']   = mw.get('dn_depth_max')
        feat['mw_up_sr_max']      = mw.get('up_sr_max')
        feat['mw_dn_sr_max']      = mw.get('dn_sr_max')

        # per-window features
        def col(name, wt):
            if name not in ci:
                return [None] * len(wt)
            return [t[ci[name]] for t in wt]

        def crowd_num(x):
            if x is None: return None
            if isinstance(x, str): return 1 if x == 'DN' else 0
            return x

        for win_name, (cd_lo, cd_hi) in WINDOWS.items():
            wt = [t for t in ticks if cd_lo <= t[ci['cd']] <= cd_hi]
            pfx = win_name

            if not wt:
                # fill all window features with None
                for k in [
                    'n','up_ask_avg','up_ask_std','up_ask_slope','up_ask_min','up_ask_max',
                    'dn_ask_avg','dn_ask_std','dn_ask_slope','dn_ask_min','dn_ask_max',
                    'spread_avg','spread_std','spread_slope','spread_pct_dn',
                    'up_ema_avg','dn_ema_avg','ema_spread_avg',
                    'bn_avg','bn_std','bn_slope','bn_neg_pct','bn_pos_pct',
                    'crowd_dn_pct','conv_avg','conv_std',
                    'up_depth_avg','dn_depth_avg','depth_ratio_avg',
                    'up_sr_avg','dn_sr_avg','sr_ratio_avg',
                    'up_zc_avg','dn_zc_avg','ask_sum_avg',
                    'up_d3_avg','dn_d3_avg','up_d10_avg','dn_d10_avg',
                    'cl_delta_avg','cl_age_avg',
                    'up_pct_above50','dn_pct_above50','up_consec_above50',
                ]:
                    feat[f'{pfx}_{k}'] = None
                continue

            up_ask  = col('up_ask',  wt)
            dn_ask  = col('dn_ask',  wt)
            up_ema  = col('up_ema',  wt)
            dn_ema  = col('dn_ema',  wt)
            bn      = col('bn_delta_pct', wt)
            crowd_s = col('crowd_side',   wt)
            conv    = col('crowd_conviction', wt)
            up_dep  = col('up_depth',  wt)
            dn_dep  = col('dn_depth',  wt)
            up_sr   = col('up_sr',     wt)
            dn_sr   = col('dn_sr',     wt)
            up_zc   = col('up_zc',     wt)
            dn_zc   = col('dn_zc',     wt)
            ask_sum = col('ask_sum',   wt)
            up_d3   = col('up_delta_3s',  wt)
            dn_d3   = col('dn_delta_3s',  wt)
            up_d10  = col('up_delta_10s', wt)
            dn_d10  = col('dn_delta_10s', wt)
            cl_d    = col('cl_delta', wt)
            cl_a    = col('cl_age',   wt)

            spread  = [dn-up if dn is not None and up is not None else None
                       for dn, up in zip(dn_ask, up_ask)]
            ema_sp  = [dn-up if dn is not None and up is not None else None
                       for dn, up in zip(dn_ema, up_ema)]
            dep_rat = [dn/up if dn and up and up > 0 else None
                       for dn, up in zip(dn_dep, up_dep)]
            sr_rat  = [dn/up if dn and up and up > 0 else None
                       for dn, up in zip(dn_sr, up_sr)]
            crowd_n = [crowd_num(x) for x in crowd_s]

            feat[f'{pfx}_n']               = len(wt)
            feat[f'{pfx}_up_ask_avg']      = safe_avg(up_ask)
            feat[f'{pfx}_up_ask_std']      = safe_std(up_ask)
            feat[f'{pfx}_up_ask_slope']    = safe_slope(up_ask)
            feat[f'{pfx}_up_ask_min']      = safe_min(up_ask)
            feat[f'{pfx}_up_ask_max']      = safe_max(up_ask)
            feat[f'{pfx}_dn_ask_avg']      = safe_avg(dn_ask)
            feat[f'{pfx}_dn_ask_std']      = safe_std(dn_ask)
            feat[f'{pfx}_dn_ask_slope']    = safe_slope(dn_ask)
            feat[f'{pfx}_dn_ask_min']      = safe_min(dn_ask)
            feat[f'{pfx}_dn_ask_max']      = safe_max(dn_ask)
            feat[f'{pfx}_spread_avg']      = safe_avg(spread)
            feat[f'{pfx}_spread_std']      = safe_std(spread)
            feat[f'{pfx}_spread_slope']    = safe_slope(spread)
            feat[f'{pfx}_spread_pct_dn']   = pct_above(spread, 0)
            feat[f'{pfx}_up_ema_avg']      = safe_avg(up_ema)
            feat[f'{pfx}_dn_ema_avg']      = safe_avg(dn_ema)
            feat[f'{pfx}_ema_spread_avg']  = safe_avg(ema_sp)
            feat[f'{pfx}_bn_avg']          = safe_avg(bn)
            feat[f'{pfx}_bn_std']          = safe_std(bn)
            feat[f'{pfx}_bn_slope']        = safe_slope(bn)
            feat[f'{pfx}_bn_neg_pct']      = pct_below(bn, 0)
            feat[f'{pfx}_bn_pos_pct']      = pct_above(bn, 0)
            feat[f'{pfx}_crowd_dn_pct']    = safe_avg([x for x in crowd_n if x is not None])
            feat[f'{pfx}_conv_avg']        = safe_avg(conv)
            feat[f'{pfx}_conv_std']        = safe_std(conv)
            feat[f'{pfx}_up_depth_avg']    = safe_avg(up_dep)
            feat[f'{pfx}_dn_depth_avg']    = safe_avg(dn_dep)
            feat[f'{pfx}_depth_ratio_avg'] = safe_avg(dep_rat)
            feat[f'{pfx}_up_sr_avg']       = safe_avg(up_sr)
            feat[f'{pfx}_dn_sr_avg']       = safe_avg(dn_sr)
            feat[f'{pfx}_sr_ratio_avg']    = safe_avg(sr_rat)
            feat[f'{pfx}_up_zc_avg']       = safe_avg(up_zc)
            feat[f'{pfx}_dn_zc_avg']       = safe_avg(dn_zc)
            feat[f'{pfx}_ask_sum_avg']     = safe_avg(ask_sum)
            feat[f'{pfx}_up_d3_avg']       = safe_avg(up_d3)
            feat[f'{pfx}_dn_d3_avg']       = safe_avg(dn_d3)
            feat[f'{pfx}_up_d10_avg']      = safe_avg(up_d10)
            feat[f'{pfx}_dn_d10_avg']      = safe_avg(dn_d10)
            feat[f'{pfx}_cl_delta_avg']    = safe_avg(cl_d)
            feat[f'{pfx}_cl_age_avg']      = safe_avg(cl_a)
            feat[f'{pfx}_up_pct_above50']  = pct_above(up_ask, 0.50)
            feat[f'{pfx}_dn_pct_above50']  = pct_above(dn_ask, 0.50)
            feat[f'{pfx}_up_consec_above50'] = consec_above(up_ask, 0.50)

        # skip_counterfactuals — guard against None
        sc = d.get('skip_counterfactuals') or {}
        for snap, key in [('T-200','sc_200'),('T-150','sc_150'),
                           ('T-120','sc_120'),('T-90','sc_90')]:
            s = sc.get(snap) or {}
            feat[f'{key}_winner_ask'] = s.get('winner_ask')
            feat[f'{key}_loser_bid']  = s.get('loser_bid')
            cs = s.get('crowd_side')
            feat[f'{key}_crowd_dn']   = (1 if cs=='DN' else 0) if cs else None
            feat[f'{key}_crowd_conv'] = s.get('crowd_conv')
            feat[f'{key}_bn_delta']   = s.get('bn_delta')

        # v5_state — guard against None
        v5 = d.get('v5_state') or {}
        feat['v5_lead_changes']   = v5.get('lead_changes')
        feat['v5_bn_flipped']     = 1 if v5.get('bn_flipped') else 0
        feat['v5_edepth_at_120']  = v5.get('edepth_at_120')
        feat['v5_cdepth_at_120']  = v5.get('cdepth_at_120')
        feat['v5_csr_at_90']      = v5.get('csr_at_90')
        feat['v5_time_near_5050'] = v5.get('time_near_5050')
        feat['v5_tratio_200_120'] = v5.get('tratio_200_120')
        feat['v5_tratio_120_60']  = v5.get('tratio_120_60')

        feat['prev_winner_dn']  = 1 if d.get('prev_winner') == 'DN' else 0
        feat['bn_delta_final']  = d.get('bn_delta_final')
        feat['hour_utc']        = d.get('hour_utc')
        feat['day_of_week']     = d.get('day_of_week')

        records.append(feat)

print(f"  {len(records)} markets extracted")

with open(OUT_PATH, 'w') as f:
    json.dump(records, f)

n_feat = len([k for k in records[0] if k not in ('slug','winner','s0','s1','s2','gc_up_pnl')])
up_n = sum(1 for r in records if r['winner']=='UP')
dn_n = sum(1 for r in records if r['winner']=='DN')
print(f"  {n_feat} features per market")
print(f"  UP={up_n}  DN={dn_n}")
print(f"Saved to {OUT_PATH} — upload to Claude.")
