# feature-extraction-toolkit

Offline tools that turn raw Polymarket per-market logs into flat feature matrices and mine them for candidate trading rules.

Input is the 5-minute crypto up/down bot logs (BTC/XRP): order-book ticks, trade tape, and recap rows with per-fire PnL. Everything here is read-only. Nothing connects to an exchange, signs an order, or moves funds.

## Scripts

- `inspect_big_file.py`: dumps the full schema of one `market_history.jsonl` record (top-level keys, `tick_columns`, `events`, `trade_tape`) to stdout and `inspect_report.txt`. Run first on any new dump.
- `dump_columns.py`: prints `tick_columns` / `trade_tape_columns` plus the first and last sample rows.
- `vps_feature_extraction.py`: builds the main feature matrix. Per-window (entry/early/mid/late/very_late) stats over 40+ indicators, joined to recap PnL. Writes `feature_matrix.json`.
- `vps_full_analysis.py`: entry-spread and mid-market spread gate sweep, `dn_live` $0.50-vs-$0.60 reform sim, per-scenario DN-winner PnL. Writes `full_analysis_results.json`.
- `analyze_asymmetry.py`: grid-searches two mirror strategies on UP/DN crash-timing asymmetry (early-collapse, buy other side) with WR/Sharpe/PnL classification. Takes a JSONL file or a directory of `replay_*.json`.
- `analyze_snapshots.py`: rule-discovery template over `market_snapshots.jsonl` (T1-T6 classification, depth/spike/trade-ratio rules) with train/test split.
- `analyze_snapshots_v2.py`: v2-snapshot variant using pre-computed velocities. Runs 2- and 3-atom rule search over the cheap-entry zone.
- `flipmed_feature_search.py`: parses `race_test_btc-updown-5m-*.log` for `flip_medium` SKIP events, labels each MISSED_WIN/GOOD_SKIP, and sweeps single-feature thresholds for a relaxation filter.

## Usage

```bash
# Inspect the schema of a fresh dump
python3 inspect_big_file.py market_history.jsonl

# Extract the feature matrix and run the gate/scenario sweep
python3 vps_feature_extraction.py   # -> feature_matrix.json
python3 vps_full_analysis.py        # -> full_analysis_results.json

# Mine for candidate rules
python3 analyze_asymmetry.py market_history.jsonl
python3 analyze_snapshots_v2.py market_snapshots_v2.jsonl
python3 flipmed_feature_search.py $DATA_DIR/race_logs/
```

The `vps_*` scripts default to `market_history.jsonl` and `market_recap_history.jsonl` in the current working directory, so run them from the directory holding the data.

## Requirements

Python 3.8+, standard library only (`json`, `statistics`, `re`, `glob`, `argparse`, `itertools`, `collections`). No pip install or virtualenv.

## Data

Input artifacts are not committed (`.json`/`.jsonl`/`.csv`/`.log` are gitignored). Get them from the private polymarket-data repo or a VPS dump and place them alongside the scripts under `$DATA_DIR`:

- `market_history.jsonl`: full per-market rows with raw `ticks`. The `*_lite` export has no `ticks` and is skipped.
- `market_recap_history.jsonl`: per-market `fires` with `hypo_pnl` for PnL joins.
- `market_snapshots.jsonl` / `market_snapshots_v2.jsonl`: bucketed snapshots.
- `replay_*.json`: per-market replays (alternative input to `analyze_asymmetry.py`).
- `race_test_btc-updown-5m-*.log`: live bot run logs (for `flipmed_feature_search.py`).
