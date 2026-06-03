# -*- coding: utf-8 -*-
"""V32E — C (HARDSTOP) + B (Early Trail) combo 검증.

V32D 결과:
  C_HS_7: CAGR +128.5% / -28.1% / C/M 4.58 (단독)
  B_stall_10: CAGR +120.4% / -25.5% / C/M 4.73 (단독)
  → 독립 룰이라 combo 효과 합쳐질 가능성

검증 combos:
  C7_B10, C8_B10, C7_B15, C8_B15
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


def run_variant(data, data_ind, all_scan, investor_data, check, hyp):
    v9.screen_v9 = make_screen_vol19_ma140(investor_data)
    eq, tr = simulate_v32d(data, data_ind, all_scan, investor_data,
                            ALL_START, ALL_END, 6, check, hyp)
    cagr, mdd, final = stats(eq, INIT_CAPITAL)
    ts = trade_stats(tr)
    u100 = unique_100pct_count(tr)
    sells = tr[tr['side']=='SELL'] if len(tr)>0 else pd.DataFrame()
    if len(sells) > 0:
        loss_with_max = ((sells['max_gain_pct'] > 5) & (sells['pnl_pct'] <= 0)).sum()
    else:
        loss_with_max = 0
    return {'cagr': cagr, 'mdd': mdd, 'final': final,
            'n': ts['n'] if ts else 0,
            'win': ts['win'] if ts else 0,
            'mean': ts['mean'] if ts else 0,
            'gt100': ts['gt100'] if ts else 0,
            'gt200': ts['gt200'] if ts else 0,
            'u100': u100,
            'loss_with_max': loss_with_max,
            'eq': eq, 'tr': tr}


def main():
    print("="*78)
    print("V32E — C (HARDSTOP) + B (Early Trail) combo")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators]...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    all_scan = all_dates[(all_dates >= ALL_START) & (all_dates <= ALL_END)]
    all_scan = all_scan[all_scan.weekday == 4]

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)

    variants = [
        # Re-runs for comparison
        ('baseline',     {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 30}),
        ('C_HS_7',       {'hardstop_pct': 0.07, 'be_thresh': None, 'stall_threshold': 30}),
        ('B_stall_10',   {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 10}),
        # New combos
        ('C7_B10',       {'hardstop_pct': 0.07, 'be_thresh': None, 'stall_threshold': 10}),
        ('C8_B10',       {'hardstop_pct': 0.08, 'be_thresh': None, 'stall_threshold': 10}),
        ('C7_B15',       {'hardstop_pct': 0.07, 'be_thresh': None, 'stall_threshold': 15}),
        ('C8_B15',       {'hardstop_pct': 0.08, 'be_thresh': None, 'stall_threshold': 15}),
        ('C7_B12',       {'hardstop_pct': 0.07, 'be_thresh': None, 'stall_threshold': 12}),
    ]

    results = []
    for name, hyp in variants:
        r = run_variant(data, data_ind, all_scan, investor_data, check, hyp)
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        print(f"\n  [{name}] HS={hyp['hardstop_pct']*100:.0f}% STALL={hyp['stall_threshold']}%")
        print(f"    CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% C/M {cm:.2f} "
              f"n={r['n']} win={r['win']:.0f}% mean={r['mean']:+.1f}%")
        print(f"    +100%:{r['gt100']} u100:{r['u100']} loss>5%:{r['loss_with_max']}")
        results.append({'name': name, **r, 'hyp': hyp})

    print(f"\n{'='*78}\n[Summary vs baseline]\n{'='*78}")
    base = next(r for r in results if r['name'] == 'baseline')
    print(f"  baseline: CAGR {base['cagr']:+.1f}%, MDD {base['mdd']:+.1f}%, C/M {base['cagr']/abs(base['mdd']):.2f}\n")
    print(f"  {'name':12s} {'CAGR':>9s} {'MDD':>8s} {'C/M':>5s} {'n':>3s} "
          f"{'win':>4s} {'+100%':>5s} {'loss>5%':>7s} {'ΔCAGR':>7s} {'ΔMDD':>7s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        dcagr = r['cagr'] - base['cagr']
        dmdd = r['mdd'] - base['mdd']
        print(f"  {r['name']:12s} {r['cagr']:>+8.1f}% {r['mdd']:>+7.1f}% {cm:>5.2f} "
              f"{r['n']:>3d} {r['win']:>3.0f}% {r['gt100']:>5d} "
              f"{r['loss_with_max']:>7d} {dcagr:>+6.1f}pp {dmdd:>+6.1f}pp")

    # Best by various metrics
    print(f"\n  Best CAGR:")
    for r in sorted(results, key=lambda x: x['cagr'], reverse=True)[:3]:
        print(f"    {r['name']}: CAGR {r['cagr']:+.1f}%")
    print(f"  Best C/M:")
    for r in sorted(results, key=lambda x: x['cagr']/abs(x['mdd']) if x['mdd']!=0 else 0,
                     reverse=True)[:3]:
        cm = r['cagr']/abs(r['mdd'])
        print(f"    {r['name']}: C/M {cm:.2f} (CAGR {r['cagr']:+.1f}%, MDD {r['mdd']:+.1f}%)")
    print(f"  Lowest loss_with_max>5%:")
    for r in sorted(results, key=lambda x: x['loss_with_max'])[:3]:
        print(f"    {r['name']}: {r['loss_with_max']} 흑자→적자 trades")


if __name__ == '__main__':
    main()
