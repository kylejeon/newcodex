# -*- coding: utf-8 -*-
"""V30B — vol_mult + ma200 dist 2D grid (V30A 손실 분석 기반)."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, INIT_CAPITAL, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter, make_screen_A_only_vol
from KOSDAQ_rocket_v23_entry_quality import simulate_v23
from KOSDAQ_rocket_v25_extra import V25Cfg, V23CfgWrap
import KOSDAQ_rocket_v9_ensemble as v9


def main():
    print("="*78)
    print("V30B — vol_mult × ma200 dist 2D grid")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
    udf_lookup = udf.set_index('ticker').to_dict('index')
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators] computing...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    all_scan = all_dates[(all_dates >= ALL_START) & (all_dates <= ALL_END)]
    all_scan = all_scan[all_scan.weekday == 4]

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)
    class D:
        sig_A = True; sig_B = False; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)

    vol_grid = [2.0, 2.1, 2.2, 2.25, 2.3, 2.5]
    ma_grid = [1.40, 1.45, 1.50, 1.55, 1.60]

    print("\n[Grid] vol × ma200_dist")
    grid_results = {}
    for vm in vol_grid:
        for md in ma_grid:
            vc = V25Cfg(name=f'vol{vm}_ma{md}', ma200_max_dist=md,
                        early_be_days=0, early_be_thresh=0.0,
                        foreign_5d_min_days=0, atr_close_max=0.0,
                        turn_min=0.0, par=0.12, lowvol_th=0.07, max_pos=6)
            vc_wrap = V23CfgWrap(vc)

            # Build screen using V20 make_screen_A_only_vol + ma200 override
            def make_screen_with_ma(vm_local, md_local):
                from KOSDAQ_rocket_v9_ensemble import has_foreign_buy, signal_A_v8h4
                def screen(date, data_ind, data, _, dummy_cfg):
                    cands = []
                    for ticker, df in data.items():
                        df_ind = data_ind[ticker]
                        if date not in df_ind.index: continue
                        row = df_ind.loc[date]
                        if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                                          'VolAvg10','ATR10','ATR50','Ret_252d','MA200']):
                            continue
                        if row['MA60'] <= 0 or row['High52w'] <= 0: continue
                        if not (row['Close'] > row['MA60']): continue
                        if not (row['MA60_slope'] > 0): continue
                        if row['Ret_252d'] < 0.20 or row['Ret_252d'] > 3.00: continue
                        dist = (row['High52w'] - row['Close']) / row['High52w']
                        if dist > 0.60: continue
                        if (row['ATR10'] / row['ATR50']) > 1.20: continue
                        if (row['VolAvg10'] / row['VolAvg50']) > 1.50: continue
                        high_b_prev = df['Close'].rolling(20).max().shift(1).loc[date]
                        if pd.isna(high_b_prev): continue
                        if not (row['Close'] > high_b_prev): continue
                        if not (row['Volume'] > vm_local * row['VolAvg50']): continue
                        if (row['Close'] / row['MA200']) > md_local: continue
                        if not has_foreign_buy(investor_data, ticker, date, 20): continue
                        cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
                    return cands
                return screen

            v9.screen_v9 = make_screen_with_ma(vm, md)
            eq, tr = simulate_v23(data, data_ind, all_scan, investor_data, cfg,
                                    ALL_START, ALL_END, exit_cfg, ec, 6, check, vc_wrap)
            cagr, mdd, _ = stats(eq, INIT_CAPITAL)
            ts = trade_stats(tr)
            u100 = unique_100pct_count(tr)
            n = ts['n'] if ts else 0
            gt100 = ts['gt100'] if ts else 0
            win = ts['win'] if ts else 0
            grid_results[(vm, md)] = {'cagr': cagr, 'mdd': mdd, 'gt100': gt100,
                                       'win': win, 'n': n, 'u100': u100,
                                       'eq': eq, 'tr': tr}
            print(f"  vol={vm:.2f} ma={md:.2f}: CAGR {cagr:+.1f}% MDD {mdd:+.1f}% "
                  f"+100%:{gt100} u100:{u100} n={n} win={win:.0f}%")

    print("\n" + "="*78)
    print("[CAGR heatmap] rows=vol, cols=ma200_dist")
    print("="*78)
    header = "       " + "".join(f"  ma{md:.2f}" for md in ma_grid)
    print(header)
    for vm in vol_grid:
        row_str = f"vol{vm:.2f}"
        for md in ma_grid:
            r = grid_results[(vm, md)]
            row_str += f"  {r['cagr']:>+6.0f}%"
        print(row_str)

    print("\n[MDD heatmap]")
    print(header)
    for vm in vol_grid:
        row_str = f"vol{vm:.2f}"
        for md in ma_grid:
            r = grid_results[(vm, md)]
            row_str += f"  {r['mdd']:>+6.0f}%"
        print(row_str)

    print("\n[+100% rocket heatmap]")
    print(header)
    for vm in vol_grid:
        row_str = f"vol{vm:.2f}"
        for md in ma_grid:
            r = grid_results[(vm, md)]
            row_str += f"  {r['gt100']:>6d} "
        print(row_str)

    # Find best (qualified)
    qualified = [(k, r) for k, r in grid_results.items()
                 if r['cagr'] >= 100 and r['gt100'] >= 1]
    if qualified:
        best_k, best_r = max(qualified, key=lambda x: x[1]['cagr']/abs(x[1]['mdd']))
        print(f"\n  → 자율 winner: vol={best_k[0]} ma={best_k[1]} "
              f"CAGR {best_r['cagr']:+.1f}% MDD {best_r['mdd']:+.1f}% "
              f"+100%:{best_r['gt100']} u100:{best_r['u100']}")

        # vs V_FINAL baseline (2.0, 1.45)
        baseline = grid_results.get((2.0, 1.45))
        if baseline:
            print(f"  vs V_FINAL (vol=2.0, ma=1.45): CAGR {baseline['cagr']:+.1f}% "
                  f"→ {best_r['cagr']:+.1f}% (Δ {best_r['cagr']-baseline['cagr']:+.1f}pp)")


if __name__ == '__main__':
    main()
