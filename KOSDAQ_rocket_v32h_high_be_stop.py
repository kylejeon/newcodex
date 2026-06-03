# -*- coding: utf-8 -*-
"""V32H — B_stall_10 단독 + 가설 D (BE_STOP @ high threshold) walk-forward.

V32D BE_STOP @ 5/7/10% = winner 일찍 청산으로 큰 손해.
이번: BE_STOP @ 20/25/30% 시도 — 충분히 올라간 종목만 보호.

또: B_stall_10 단독 (HARDSTOP -10% 유지, STALL 만 강화) walk-forward.

Folds: V31/V32C/V32F/V32G 동일
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, UNIVERSE_CSV, INIT_CAPITAL, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v32d_exit_improve import simulate_v32d, make_screen_vol19_ma140
import KOSDAQ_rocket_v9_ensemble as v9


def run_period(data, data_ind, investor_data, check, sim_s, sim_e, hyp):
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
    be_count = (sells['reason']=='BE_STOP').sum() if len(sells)>0 else 0
    if len(sells) > 0:
        loss_with_max = ((sells['max_gain_pct'] > 5) & (sells['pnl_pct'] <= 0)).sum()
    else:
        loss_with_max = 0
    return {'cagr': cagr, 'mdd': mdd, 'n': ts['n'] if ts else 0,
            'win': ts['win'] if ts else 0,
            'gt100': ts['gt100'] if ts else 0,
            'u100': u100,
            'loss_with_max': loss_with_max, 'be_count': be_count,
            'eq': eq, 'tr': tr}


def main():
    print("="*78)
    print("V32H — B_stall_10 단독 + 가설 D (BE_STOP @ 20/25/30%) walk-forward")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators]...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)

    configs = [
        ('baseline',    {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 30}),
        ('B_stall_10',  {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 10}),
        ('D_BE_20',     {'hardstop_pct': 0.10, 'be_thresh': 20,   'stall_threshold': 30}),
        ('D_BE_25',     {'hardstop_pct': 0.10, 'be_thresh': 25,   'stall_threshold': 30}),
        ('D_BE_30',     {'hardstop_pct': 0.10, 'be_thresh': 30,   'stall_threshold': 30}),
    ]

    # Full 5-year first
    print(f"\n{'='*78}")
    print(f"[Full 5y] {ALL_START.date()} ~ {ALL_END.date()}")
    print('='*78)
    full_results = {}
    for cname, hyp in configs:
        r = run_period(data, data_ind, investor_data, check, ALL_START, ALL_END, hyp)
        full_results[cname] = r
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        print(f"  [{cname}] CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% C/M {cm:.2f} "
              f"n={r['n']} win={r['win']:.0f}% +100%:{r['gt100']} "
              f"BE:{r['be_count']} loss>5%:{r['loss_with_max']}")

    # Walk-forward
    folds = [
        ('Fold1', pd.Timestamp('2023-01-01'), pd.Timestamp('2024-06-30')),
        ('Fold2', pd.Timestamp('2024-01-01'), pd.Timestamp('2024-12-31')),
        ('Fold3', pd.Timestamp('2025-01-01'), pd.Timestamp('2026-05-31')),
    ]
    wf_results = {}
    for fname, te_s, te_e in folds:
        print(f"\n{'='*78}")
        print(f"[{fname}] {te_s.date()} ~ {te_e.date()}")
        print('='*78)
        wf_results[fname] = {}
        for cname, hyp in configs:
            r = run_period(data, data_ind, investor_data, check, te_s, te_e, hyp)
            wf_results[fname][cname] = r
            cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
            print(f"  [{cname}] CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% C/M {cm:.2f} "
                  f"n={r['n']} loss>5%:{r['loss_with_max']} BE:{r['be_count']}")

    # Summary
    print(f"\n{'='*78}\n[Walk-forward Summary — ΔCAGR vs baseline per fold]\n{'='*78}")
    print(f"\n  {'Config':>12s} {'Fold1':>8s} {'Fold2':>8s} {'Fold3':>8s} {'Avg':>7s} {'Full5y':>8s}")
    base_full = full_results['baseline']['cagr']
    for cname, _ in configs:
        deltas = [wf_results[f][cname]['cagr'] - wf_results[f]['baseline']['cagr']
                  for f, _, _ in folds]
        avg = sum(deltas)/3
        full_delta = full_results[cname]['cagr'] - base_full
        print(f"  {cname:>12s} {deltas[0]:>+7.1f}pp {deltas[1]:>+7.1f}pp "
              f"{deltas[2]:>+7.1f}pp {avg:>+6.1f}pp {full_delta:>+7.1f}pp")

    print(f"\n  Walk-forward CAGR avg:")
    for cname, _ in configs:
        avgs = [wf_results[f][cname]['cagr'] for f, _, _ in folds]
        mdds = [wf_results[f][cname]['mdd'] for f, _, _ in folds]
        print(f"    {cname}: avg CAGR {sum(avgs)/3:+.1f}%, avg MDD {sum(mdds)/3:+.1f}%")

    print(f"\n  흑자→적자 전환 (loss_with_max>5%) avg:")
    for cname, _ in configs:
        avg_loss = sum(wf_results[f][cname]['loss_with_max'] for f, _, _ in folds) / 3
        print(f"    {cname}: {avg_loss:.1f}건 평균/fold")


if __name__ == '__main__':
    main()
