# -*- coding: utf-8 -*-
"""
RocketHunter v20 — V19_lowvol robustness sensitivity.

Tests:
  1. Top trade contribution (실리콘투, 하이드로리튬 1건씩 제거 시 CAGR)
  2. lowvol threshold sensitivity (0.05/0.07/0.10/0.15)
  3. Position size sensitivity (3/5/7/10)
  4. PARABOLIC threshold sensitivity (0.08-0.20)
  5. vol_mult sensitivity (1.5/2.0/2.5/3.0)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, OUT_DIR, INIT_CAPITAL, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import (
    fetch_kosdaq_index, make_kosdaq_filter, portfolio_simulate_v17,
)
import KOSDAQ_rocket_v9_ensemble as v9


def make_screen_A_only_vol(vol_mult=2.0):
    """A_only screener with variable vol_mult."""
    def screen(date, data_ind, data, investor_data, dummy_cfg):
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
            if not (row['Volume'] > vol_mult * row['VolAvg50']): continue
            if not has_foreign_buy(investor_data, ticker, date, 20): continue
            cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


def make_lowvol_filter(idx_df, threshold):
    """Custom lowvol filter with variable threshold."""
    idx_df = idx_df.copy()
    idx_df['Ret14d_abs'] = idx_df['Close'].pct_change(14).abs()
    def check(date):
        if date not in idx_df.index:
            d_match = idx_df.index[idx_df.index <= date]
            if len(d_match) == 0: return True
            date = d_match[-1]
        row = idx_df.loc[date]
        return pd.notna(row['Ret14d_abs']) and row['Ret14d_abs'] < threshold
    return check


def run_one(data, data_ind, all_scan, investor_data, cfg, ec, kqd,
            lowvol_thresh=0.07, max_pos=5, exclude_tickers=None):
    if exclude_tickers:
        # 임시로 ticker 제외하는 screener
        original = v9.screen_v9
        def filt_screen(date, data_ind, data, investor_data, dummy_cfg):
            cands = original(date, data_ind, data, investor_data, dummy_cfg)
            return [c for c in cands if c['ticker'] not in exclude_tickers]
        v9.screen_v9 = filt_screen
    check = make_lowvol_filter(kqd, lowvol_thresh)
    exit_cfg = v8_cfg('exit', vol=2.0)
    eq, tr = portfolio_simulate_v17(data, data_ind, all_scan, investor_data,
                                     cfg, ALL_START, ALL_END, exit_cfg, ec, max_pos,
                                     check, 0)
    return eq, tr


def main():
    print("="*78)
    print("RocketHunter v20 — V19_lowvol robustness sensitivity")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators] computing...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    all_scan = all_dates[(all_dates >= ALL_START) & (all_dates <= ALL_END)]
    all_scan = all_scan[all_scan.weekday == 4]
    print(f"[scan] {len(all_scan)} weeks\n")

    kqd = fetch_kosdaq_index()
    class D:
        sig_A = True; sig_B = False; sig_C = False; sig_D = False
    cfg = D()
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)
    v9.screen_v9 = make_screen_A_only_vol(2.0)

    # Baseline V19_lowvol
    print("="*78)
    print("[Baseline] V19_lowvol")
    print("="*78)
    eq_b, tr_b = run_one(data, data_ind, all_scan, investor_data, cfg, ec, kqd)
    cagr_b, mdd_b, _ = stats(eq_b, INIT_CAPITAL)
    ts_b = trade_stats(tr_b)
    print(f"  baseline: CAGR {cagr_b:+.1f}% MDD {mdd_b:+.1f}% n={ts_b['n']}")

    # Test 1: Top trade contribution
    print("\n" + "="*78)
    print("[1] Top rocket contribution (1건 제외 시 CAGR)")
    print("="*78)
    rocket_tickers = ['101670', '257720']  # 하이드로리튬, 실리콘투
    for t in rocket_tickers:
        v9.screen_v9 = make_screen_A_only_vol(2.0)
        eq, tr = run_one(data, data_ind, all_scan, investor_data, cfg, ec, kqd,
                         exclude_tickers={t})
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"  exclude {t} ({name_map.get(t,'?')}): CAGR {cagr:+.1f}% "
              f"MDD {mdd:+.1f}% n={ts['n']} (drop {cagr_b-cagr:+.1f}pp)")

    # Test 2: lowvol threshold sensitivity
    print("\n" + "="*78)
    print("[2] lowvol threshold sensitivity")
    print("="*78)
    for th in [0.05, 0.07, 0.08, 0.10, 0.15]:
        v9.screen_v9 = make_screen_A_only_vol(2.0)
        eq, tr = run_one(data, data_ind, all_scan, investor_data, cfg, ec, kqd,
                         lowvol_thresh=th)
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"  lowvol<{th}: CAGR {cagr:+.1f}% MDD {mdd:+.1f}% "
              f"+100%:{ts['gt100']} n={ts['n']}")

    # Test 3: Position size
    print("\n" + "="*78)
    print("[3] Position size sensitivity")
    print("="*78)
    for pos in [3, 4, 5, 6, 7, 10]:
        v9.screen_v9 = make_screen_A_only_vol(2.0)
        eq, tr = run_one(data, data_ind, all_scan, investor_data, cfg, ec, kqd,
                         max_pos=pos)
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"  pos={pos}: CAGR {cagr:+.1f}% MDD {mdd:+.1f}% "
              f"+100%:{ts['gt100']} n={ts['n']}")

    # Test 4: PARABOLIC sensitivity (already in V14, but re-check)
    print("\n" + "="*78)
    print("[4] PARABOLIC threshold sensitivity")
    print("="*78)
    for par in [0.10, 0.11, 0.12, 0.13, 0.15, 0.18]:
        ec_p = ExitCfg('e', False, par, 5, False, 3.0)
        v9.screen_v9 = make_screen_A_only_vol(2.0)
        eq, tr = run_one(data, data_ind, all_scan, investor_data, cfg, ec_p, kqd)
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"  par={par}: CAGR {cagr:+.1f}% MDD {mdd:+.1f}% "
              f"+100%:{ts['gt100']} n={ts['n']}")

    # Test 5: vol_mult sensitivity
    print("\n" + "="*78)
    print("[5] vol_mult sensitivity")
    print("="*78)
    for vm in [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]:
        v9.screen_v9 = make_screen_A_only_vol(vm)
        eq, tr = run_one(data, data_ind, all_scan, investor_data, cfg, ec, kqd)
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"  vol×{vm}: CAGR {cagr:+.1f}% MDD {mdd:+.1f}% "
              f"+100%:{ts['gt100']} n={ts['n']}")


if __name__ == '__main__':
    main()
