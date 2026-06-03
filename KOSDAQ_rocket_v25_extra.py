# -*- coding: utf-8 -*-
"""
RocketHunter v25 — V24_ma145 + 추가 filters 시도.

V24 발견: V24_ma145 CAGR +185.6%, C/M 4.84

V25 ideas:
  1. ATR/Close 변동성 cap (작전주 회피 다른 방법)
  2. 시총 minimum (small cap 작전주 회피)
  3. 거래대금 minimum
  4. par 0.10/0.13/0.15 with ma145
  5. ma145 + lowvol threshold sweep
  6. ma145 + position 6,7 (slightly larger fleet)
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import NamedTuple
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
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v23_entry_quality import simulate_v23
import KOSDAQ_rocket_v9_ensemble as v9


class V25Cfg(NamedTuple):
    name: str
    ma200_max_dist: float
    early_be_days: int
    early_be_thresh: float
    foreign_5d_min_days: int
    atr_close_max: float       # ATR10 / Close ≤ this (0=ignore)
    turn_min: float            # avg_turn (60d) ≥ this billion (0=ignore)
    par: float                 # PARABOLIC threshold
    lowvol_th: float           # KOSDAQ filter
    max_pos: int


def cfg_default(**kw):
    base = dict(name='', ma200_max_dist=1.45, early_be_days=0, early_be_thresh=0.0,
                foreign_5d_min_days=0, atr_close_max=0.0, turn_min=0.0,
                par=0.12, lowvol_th=0.07, max_pos=5)
    base.update(kw)
    return V25Cfg(**base)


CONFIGS = [
    cfg_default(name='V25_ma145_base'),
    cfg_default(name='V25_atr5',   atr_close_max=0.05),  # ATR ≤ 5% of close
    cfg_default(name='V25_atr6',   atr_close_max=0.06),
    cfg_default(name='V25_atr8',   atr_close_max=0.08),
    cfg_default(name='V25_par10',  par=0.10),
    cfg_default(name='V25_par13',  par=0.13),
    cfg_default(name='V25_par15',  par=0.15),
    cfg_default(name='V25_lv05',   lowvol_th=0.05),
    cfg_default(name='V25_lv08',   lowvol_th=0.08),
    cfg_default(name='V25_pos6',   max_pos=6),
    cfg_default(name='V25_pos7',   max_pos=7),
    cfg_default(name='V25_atr6_par13', atr_close_max=0.06, par=0.13),
]


def signal_A_v25(df, df_ind, date, vc, investor_data, ticker, udf_lookup):
    row = df_ind.loc[date]
    if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                      'VolAvg10','ATR10','ATR50','Ret_252d','MA200']):
        return False
    if row['MA60'] <= 0 or row['High52w'] <= 0: return False
    if not (row['Close'] > row['MA60']): return False
    if not (row['MA60_slope'] > 0): return False
    if row['Ret_252d'] < 0.20 or row['Ret_252d'] > 3.00: return False
    dist = (row['High52w'] - row['Close']) / row['High52w']
    if dist > 0.60: return False
    if (row['ATR10'] / row['ATR50']) > 1.20: return False
    if (row['VolAvg10'] / row['VolAvg50']) > 1.50: return False
    high_b_prev = df['Close'].rolling(20).max().shift(1).loc[date]
    if pd.isna(high_b_prev): return False
    if not (row['Close'] > high_b_prev): return False
    if not (row['Volume'] > 2.0 * row['VolAvg50']): return False
    if (row['Close'] / row['MA200']) > vc.ma200_max_dist:
        return False
    # ATR/Close cap
    if vc.atr_close_max > 0:
        if (row['ATR10'] / row['Close']) > vc.atr_close_max:
            return False
    # turn min
    if vc.turn_min > 0:
        info = udf_lookup.get(ticker)
        if info is None: return False
        if info.get('avg_turn', 0) < vc.turn_min:
            return False
    if not has_foreign_buy(investor_data, ticker, date, 20):
        return False
    if vc.foreign_5d_min_days > 0:
        inv = investor_data.get(ticker)
        if inv is None: return False
        pre = inv[inv.index <= date]
        if len(pre) < 5: return False
        last5 = pre['Foreign_Net'].tail(5)
        if (last5 > 0).sum() < vc.foreign_5d_min_days: return False
    return True


def make_screen_v25(vc, investor_data, udf_lookup):
    def screen(date, data_ind, data, _, dummy_cfg):
        cands = []
        for ticker, df in data.items():
            df_ind = data_ind[ticker]
            if date not in df_ind.index: continue
            row = df_ind.loc[date]
            if pd.isna(row['Close']): continue
            if signal_A_v25(df, df_ind, date, vc, investor_data, ticker, udf_lookup):
                cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


# Use V23 cfg-like wrapper for simulate_v23
class V23CfgWrap:
    def __init__(self, vc):
        self.early_be_days = vc.early_be_days
        self.early_be_thresh = vc.early_be_thresh
        self.ma200_max_dist = vc.ma200_max_dist
        self.foreign_5d_min_days = vc.foreign_5d_min_days


def main():
    print("="*78)
    print("RocketHunter v25 — V24_ma145 + 추가 filters")
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
    print(f"[scan] {len(all_scan)} weeks\n")

    kqd = fetch_kosdaq_index()
    class D:
        sig_A = True; sig_B = False; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)

    print("="*78)
    print(f"[Sweep] {len(CONFIGS)} V25 variants")
    print("="*78)
    results = []
    for vc in CONFIGS:
        ec = ExitCfg('e', False, vc.par, 5, False, 3.0)
        check = make_lowvol_filter(kqd, vc.lowvol_th)
        v9.screen_v9 = make_screen_v25(vc, investor_data, udf_lookup)
        vc_wrap = V23CfgWrap(vc)
        eq, tr = simulate_v23(data, data_ind, all_scan, investor_data, cfg,
                               ALL_START, ALL_END, exit_cfg, ec, vc.max_pos,
                               check, vc_wrap)
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        u100 = unique_100pct_count(tr)
        n = ts['n'] if ts else 0
        gt100 = ts['gt100'] if ts else 0
        win = ts['win'] if ts else 0
        mean = ts['mean'] if ts else 0
        hs = (tr['reason']=='HARDSTOP').sum() if len(tr)>0 else 0
        ma = (tr['reason']=='MA200').sum() if len(tr)>0 else 0
        print(f"\n  [{vc.name}] ma={vc.ma200_max_dist} atr<{vc.atr_close_max} "
              f"par={vc.par} lv<{vc.lowvol_th} pos={vc.max_pos}")
        print(f"    CAGR {cagr:+.1f}% MDD {mdd:+.1f}% C/M {cagr/abs(mdd):.2f} "
              f"n={n} win {win:.0f}% mean {mean:+.1f}%")
        print(f"    +100%:{gt100} u100:{u100} HS:{hs} MA200:{ma}")
        results.append({'name': vc.name, 'eq': eq, 'tr': tr, 'vc': vc,
                        'cagr': cagr, 'mdd': mdd, 'gt100': gt100, 'u100': u100,
                        'n': n, 'win': win, 'mean': mean, 'hs': hs, 'ma': ma})

    print("\n" + "="*78)
    print("[Summary]")
    print("="*78)
    print(f"  {'name':22s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} {'+100%':>5s} "
          f"{'HS':>3s} {'win':>4s} {'mean':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        print(f"  {r['name']:22s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt100']:>5d} {r['hs']:>3d} {r['win']:>3.0f}% "
              f"{r['mean']:>+5.1f}% {r['n']:>3d}")

    qualified = [r for r in results if r['cagr'] >= 100 and r['gt100'] >= 1]
    if qualified:
        best = max(qualified, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → 자율 winner: {best['name']} (CAGR {best['cagr']:+.1f}%, C/M {best['cagr']/abs(best['mdd']):.2f})")
        best['eq'].to_csv(OUT_DIR / 'rocket_v25_best_equity.csv')
        best['tr'].to_csv(OUT_DIR / 'rocket_v25_best_trades.csv', index=False)
        print(f"\n[save] rocket_v25_best_*.csv ({best['name']})")


if __name__ == '__main__':
    main()
