# -*- coding: utf-8 -*-
"""V32C — vol 1.9 ma 1.40 walk-forward 직접 검증.

V31 결과:
  Fold 1 train winner = vol 1.9 ma 1.40 → test +81.5%
  Fold 2 train winner = vol 1.9 ma 1.40 → test +50.7%
  Fold 3 train winner = vol 1.9 ma 1.45 (vol 1.9 ma 1.40 test 안 함)

이 스크립트: vol 1.9 ma 1.40 을 모든 fold test 에 직접 적용.
V_FINAL (2.0, 1.45) 도 같이 비교.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, INIT_CAPITAL,
)
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v23_entry_quality import simulate_v23
from KOSDAQ_rocket_v25_extra import V25Cfg, V23CfgWrap
import KOSDAQ_rocket_v9_ensemble as v9
from KOSDAQ_rocket_v31_walkforward import make_screen_with_ma, run_one


def main():
    print("="*78)
    print("V32C — vol 1.9 ma 1.40 walk-forward direct test")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators]...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)

    folds = [
        ('Fold1', pd.Timestamp('2023-01-01'), pd.Timestamp('2024-06-30')),
        ('Fold2', pd.Timestamp('2024-01-01'), pd.Timestamp('2024-12-31')),
        ('Fold3', pd.Timestamp('2025-01-01'), pd.Timestamp('2026-05-31')),
    ]

    configs = [
        ('vol1.9_ma1.40', 1.9, 1.40),
        ('V_FINAL (2.0, 1.45)', 2.0, 1.45),
    ]

    results = {}
    for fname, te_s, te_e in folds:
        print(f"\n{'='*78}")
        print(f"[{fname}] Test {te_s.date()} ~ {te_e.date()}")
        print('='*78)
        results[fname] = {}
        for cname, vm, md in configs:
            r = run_one(data, data_ind, investor_data, check, te_s, te_e, vm, md)
            results[fname][cname] = r
            print(f"  [{cname}] CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% "
                  f"C/M {r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0:.2f} "
                  f"n={r['n']} win={r['win']:.0f}% +100%:{r['gt100']}")

    print(f"\n{'='*78}")
    print("[Walk-forward Test Summary]")
    print(f"{'='*78}\n")
    print(f"  {'Fold':>6s} {'Config':>22s} {'CAGR':>9s} {'MDD':>8s} {'C/M':>5s} "
          f"{'n':>3s} {'win':>4s} {'+100%':>5s}")
    for fname in [f[0] for f in folds]:
        for cname, _, _ in configs:
            r = results[fname][cname]
            cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
            print(f"  {fname:>6s} {cname:>22s} {r['cagr']:>+8.1f}% "
                  f"{r['mdd']:>+7.1f}% {cm:>5.2f} {r['n']:>3d} "
                  f"{r['win']:>3.0f}% {r['gt100']:>5d}")

    print(f"\n  Avg test CAGR comparison:")
    for cname, _, _ in configs:
        avgs = [results[fname][cname]['cagr'] for fname, _, _ in folds]
        print(f"    {cname:>22s}: avg {sum(avgs)/len(avgs):+.1f}% "
              f"(min {min(avgs):+.1f}%, max {max(avgs):+.1f}%)")


if __name__ == '__main__':
    main()
