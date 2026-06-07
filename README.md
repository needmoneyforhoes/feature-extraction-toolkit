# feature-extraction-toolkit

Feature-matrix extraction and schema/snapshot inspection for Polymarket tick and
trade-tape data.

These are the offline research tools used to turn raw per-market logs from the
Polymarket **5-minute crypto up/down** bot (BTC/XRP) into flat feature matrices
and to mine those features for candidate trading rules. They are read-only:
nothing here connects to an exchange, signs an order, or moves funds.

## Why it exists

The live bot records each market as a fat JSONL row (raw order-book ticks, trade
tape, recap with per-fire PnL). To do research you need that wide row collapsed
into per-market, per-window features — and you need to understand the exact
schema before you can trust it. This repo does both: schema inspection,
feature extraction, and grid/atom search over the extracted features.

## What's inside

| Script | Purpose | Invocation |
|---|---|---|
| `inspect_big_file.py` | Dump the full schema of one `market_history.jsonl` record (top-level keys, `tick_columns`, `events`, `trade_tape`) to stdout + `inspect_report.txt`. Run this first on any new dump. | `python3 inspect_big_file.py market_history.jsonl [--skip N]` |
| `dump_columns.py` | Quick peek at `tick_columns` / `trade_tape_columns` plus the first/last sample rows. | `python3 dump_columns.py market_history.jsonl` |
| `vps_feature_extraction.py` | Build the main feature matrix: per-window (entry/early/mid/late/very_late) stats over 40+ indicators, joined to recap PnL. Writes `feature_matrix.json`. | `python3 vps_feature_extraction.py` |
| `vps_full_analysis.py` | Scenario/gate sweep: entry-spread and mid-market spread gates, `dn_live` $0.50-vs-$0.60 reform sim, per-scenario DN-winner PnL. Writes `full_analysis_results.json`. | `python3 vps_full_analysis.py` |
| `analyze_asymmetry.py` | Tests the UP/DN crash-timing asymmetry as a signal; grid-searches two mirror strategies (early-collapse → buy other side) with WR/Sharpe/PnL classification. Accepts a JSONL file **or** a directory of `replay_*.json`. | `python3 analyze_asymmetry.py <history.jsonl \| replays/>` |
| `analyze_snapshots.py` | Rule-discovery template over `market_snapshots.jsonl` (T1–T6 classification, depth/spike/trade-ratio rules) with train/test split. | `python3 analyze_snapshots.py market_snapshots.jsonl` |
| `analyze_snapshots_v2.py` | Faster v2-snapshot variant; uses pre-computed velocities, runs 2- and 3-atom rule search over the cheap-entry zone. | `python3 analyze_snapshots_v2.py market_snapshots_v2.jsonl [--ask-min --ask-max]` |
| `flipmed_feature_search.py` | Mines `race_test_btc-updown-5m-*.log` files for `flip_medium` SKIP events, labels each MISSED_WIN/GOOD_SKIP, and sweeps single-feature thresholds to find a relaxation filter. | `python3 flipmed_feature_search.py [log_dir]` |

## Requirements

- Python 3.8+ — **standard library only** (`json`, `statistics`, `re`, `glob`,
  `argparse`, `itertools`, `collections`). No pip install, no virtualenv needed.
- No wallet, private key, or network access — these scripts never trade.
- Input data files (see below).

## Usage

```bash
# 1. Understand the schema of a fresh dump
python3 inspect_big_file.py market_history.jsonl

# 2. Extract the feature matrix + run the gate/scenario sweep
python3 vps_feature_extraction.py     # -> feature_matrix.json
python3 vps_full_analysis.py          # -> full_analysis_results.json

# 3. Mine for candidate rules
python3 analyze_asymmetry.py market_history.jsonl
python3 analyze_snapshots_v2.py market_snapshots_v2.jsonl
python3 flipmed_feature_search.py /path/to/race_logs/
```

The `vps_*` scripts default to filenames in the **current working directory**
(`market_history.jsonl`, `market_recap_history.jsonl`), so run them from the
directory that holds the data — historically the live bot's working dir.

## Data

These tools consume the bot's recorded artifacts, which are **not committed**
here (`.json`/`.jsonl`/`.csv`/`.log` are gitignored). Obtain them from the
private **polymarket-data** repo or a live VPS dump and place them alongside the
scripts:

- `market_history.jsonl` — full per-market rows with raw `ticks` (note: the
  `*_lite` export has no `ticks` and will be skipped).
- `market_recap_history.jsonl` — per-market `fires` with `hypo_pnl` for PnL joins.
- `market_snapshots.jsonl` / `market_snapshots_v2.jsonl` — bucketed snapshots.
- `replay_*.json` — per-market replays (alternative input to `analyze_asymmetry.py`).
- `race_test_btc-updown-5m-*.log` — live bot run logs (for `flipmed_feature_search.py`).

> Private research software. No warranty; trades/handles real funds at your own risk.
