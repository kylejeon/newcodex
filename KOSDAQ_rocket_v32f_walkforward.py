# -*- coding: utf-8 -*-
"""V32F — C7_B10 walk-forward direct test.

C7_B10 (HARDSTOP -7%, STALL @ max_gain >= 10%) 을 각 fold OOS test 에 적용.
vs baseline (vol 1.9 ma 1.40 + 기존 exit).

Folds (V31/V32C 동일):
  Fold 1: 2023-01 ~ 2024-06 test
  Fold 2: 2024-01 ~ 2024-12 test
  Fold 3: 2025-01 ~ 2026-05 test
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, UNIVERSE_CSV, INIT_CAPITAL,
)
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v32d_exit_improve import simulate_v32d, make_screen_vol19_ma140
import KOSDAQ_rocket_v9_ensemble as v9


def run_fold(data, data_ind, investor_data, check, sim_s, sim_e, hyp):
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    all_scan = all_dates[(all_dates >= sim_s) & (all_dates <= sim_e)]
    all_scan = all_scan[all_scan.weekday == 4]
    v9.screen_v9 = make_screen_vol19_ma140(investor_data)
    eq, tr = simulate_v32d(data, data_ind, all_scan, investor_data,
                            sim_s, sim_e, 6, check, hyp)
    cagr, mdd, final = stats(eq, INIT_CAPITAL)
    ts = trade_stats(tr)
    u100 = unique_100pct_count(tr)
    sells = tr[tr['side']=='SELL'] if len(tr)>0 else pd.DataFrame()
    if len(sells) > 0:
        loss_with_max = ((sells['max_gain_pct'] > 5) & (sells['pnl_pct'] <= 0)).sum()
    else:
        loss_with_max = 0
    return {'cagr': cagr, 'mdd': mdd, 'n': ts['n'] if ts else 0,
            'win': ts['win'] if ts else 0,
            'gt100': ts['gt100'] if ts else 0,
            'u100': u100, 'loss_with_max': loss_with_max,
            'eq': eq, 'tr': tr}


def main():
    print("="*78)
    print("V32F — C7_B10 walk-forward direct test")
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
        ('baseline (HS=10, STALL=30)', {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 30}),
        ('C7_B10 (HS=7, STALL=10)',    {'hardstop_pct': 0.07, 'be_thresh': None, 'stall_threshold': 10}),
    ]

    results = {}
    for fname, te_s, te_e in folds:
        print(f"\n{'='*78}")
        print(f"[{fname}] Test {te_s.date()} ~ {te_e.date()}")
        print('='*78)
        results[fname] = {}
        for cname, hyp in configs:
            r = run_fold(data, data_ind, investor_data, check, te_s, te_e, hyp)
            results[fname][cname] = r
            cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
            print(f"  [{cname}] CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% C/M {cm:.2f} "
                  f"n={r['n']} win={r['win']:.0f}% +100%:{r['gt100']} "
                  f"loss>5%:{r['loss_with_max']}")

    print(f"\n{'='*78}")
    print("[Summary — C7_B10 vs baseline (each fold)]")
    print('='*78)
    print(f"\n  {'Fold':>6s} {'Config':>32s} {'CAGR':>9s} {'MDD':>8s} {'C/M':>5s} "
          f"{'loss>5%':>7s}")
    for fname in [f[0] for f in folds]:
        for cname, _ in configs:
            r = results[fname][cname]
            cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
            print(f"  {fname:>6s} {cname:>32s} {r['cagr']:>+8.1f}% "
                  f"{r['mdd']:>+7.1f}% {cm:>5.2f} {r['loss_with_max']:>7d}")

    print(f"\n  Average:")
    for cname, _ in configs:
        avgs = [results[fname][cname]['cagr'] for fname, _, _ in folds]
        mdds = [results[fname][cname]['mdd'] for fname, _, _ in folds]
        print(f"    {cname}: avg CAGR {sum(avgs)/len(avgs):+.1f}%, "
              f"avg MDD {sum(mdds)/len(mdds):+.1f}%")


if __name__ == '__main__':
    main()
