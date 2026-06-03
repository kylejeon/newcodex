# -*- coding: utf-8 -*-
"""
RocketHunter v23 — Entry quality 강화 (HARDSTOP 9건/MA200 8건 = 모든 손실).

V22 발견:
  - PARABOLIC/FAST_MA/STALL exit = 100% win
  - HARDSTOP + MA200 = 17 trades 모두 손실 (entry quality 문제)

V23 시도:
  1. Hardstop 후 빠른 컷: 진입 후 7일 내 break-even -5% 컷 (HARDSTOP 줄임)
  2. Entry 후 5일 내 close < entry 5% 면 즉시 exit (BE_EXIT)
  3. Entry 시 stricter MA200 distance (close/MA200 < 1.50)
  4. Entry 시 RSI < 75 만 (overbought 거부)
  5. 최근 5일 동안 외인 매수 day 비율 ≥ 60%
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
    UNIVERSE_CSV, OUT_DIR, INIT_CAPITAL, FEE_RATE, MAX_HOLD_DAYS, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index, make_kosdaq_filter
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
import KOSDAQ_rocket_v9_ensemble as v9


class V23Cfg(NamedTuple):
    name: str
    early_be_days: int        # 진입 후 N일 내 close < entry → BE_EXIT
    early_be_thresh: float    # close < entry * (1 - thresh) 시 트리거
    ma200_max_dist: float     # close / MA200 ≤ this (entry filter)
    foreign_5d_min_days: int  # 최근 5일 중 외인 매수 day 최소 (0=ignore)


CONFIGS = [
    V23Cfg('V23_base',         0,   0.0,  999, 0),  # = V19_lowvol baseline
    V23Cfg('V23_be5',          5,   0.05, 999, 0),  # 5일 내 -5% 컷
    V23Cfg('V23_be7_03',       7,   0.03, 999, 0),  # 7일 내 -3% 컷
    V23Cfg('V23_be10_05',     10,   0.05, 999, 0),  # 10일 내 -5% 컷
    V23Cfg('V23_ma150',        0,   0.0,  1.50, 0), # MA200 거리 50% 이내
    V23Cfg('V23_ma130',        0,   0.0,  1.30, 0),
    V23Cfg('V23_for3',         0,   0.0,  999, 3),  # 5일 중 3일+ 외인 매수
    V23Cfg('V23_for4',         0,   0.0,  999, 4),
    V23Cfg('V23_combo',        7,   0.03, 1.30, 3),
    V23Cfg('V23_combo2',       5,   0.05, 1.50, 3),
]


def signal_A_v23(df, df_ind, date, vc, investor_data, ticker):
    """V19 A + entry quality strict filter."""
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
    # H6 idea: MA200 max distance
    if (row['Close'] / row['MA200']) > vc.ma200_max_dist:
        return False
    # foreign 20d
    if not has_foreign_buy(investor_data, ticker, date, 20):
        return False
    # foreign 5d minimum days
    if vc.foreign_5d_min_days > 0:
        inv = investor_data.get(ticker)
        if inv is None: return False
        pre = inv[inv.index <= date]
        if len(pre) < 5: return False
        last5 = pre['Foreign_Net'].tail(5)
        buy_days = (last5 > 0).sum()
        if buy_days < vc.foreign_5d_min_days: return False
    return True


def make_screen_v23(vc, investor_data):
    def screen(date, data_ind, data, _, dummy_cfg):
        cands = []
        for ticker, df in data.items():
            df_ind = data_ind[ticker]
            if date not in df_ind.index: continue
            row = df_ind.loc[date]
            if pd.isna(row['Close']): continue
            if signal_A_v23(df, df_ind, date, vc, investor_data, ticker):
                cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


def exit_check_v23(df, df_ind, idx, h, days_since_peak, days_held, exit_cfg, ec, vc):
    """V11 exit + early_be cut."""
    from KOSDAQ_rocket_v11_exit import exit_check_v11
    yc = float(df['Close'].iloc[idx - 1])
    if pd.isna(yc): return None
    entry_px = h['entry_px']

    # V23 early BE cut
    if vc.early_be_days > 0 and days_held >= 2 and days_held < vc.early_be_days:
        if yc < entry_px * (1 - vc.early_be_thresh):
            return 'BE_EXIT'

    return exit_check_v11(df, df_ind, idx, h, days_since_peak, days_held, exit_cfg, ec)


def simulate_v23(data, data_ind, scan_dates, investor_data, cfg, sim_s, sim_e,
                 exit_cfg, ec, max_pos, market_check, vc):
    cash = INIT_CAPITAL
    holdings = {}
    eq_rows = []
    trade_rows = []
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    sim_dates = all_dates[(all_dates >= sim_s) & (all_dates <= sim_e)]
    scan_set = set(scan_dates)

    for date in sim_dates:
        for t, h in holdings.items():
            if date in data[t].index:
                cl = float(data[t]['Close'].loc[date])
                if pd.notna(cl) and cl > h['max_close']:
                    h['max_close'] = cl
                    h['max_close_date'] = date

        to_exit = []
        for t, h in holdings.items():
            df = data[t]
            if date not in df.index: continue
            try:
                idx = df.index.get_loc(date)
            except KeyError: continue
            if idx == 0: continue
            days_held = (date - h['entry_date']).days
            days_since_peak = (date - h['max_close_date']).days
            reason = exit_check_v23(df, data_ind[t], idx, h, days_since_peak, days_held,
                                     exit_cfg, ec, vc)
            if reason:
                to_exit.append((t, reason))

        for t, reason in to_exit:
            df = data[t]
            px = float(df['Open'].loc[date])
            if pd.isna(px) or px <= 0: continue
            qty = holdings[t]['qty']
            proceeds = qty * px * (1 - FEE_RATE)
            cash += proceeds
            pnl_pct = (px / holdings[t]['entry_px'] - 1) * 100
            max_gain = (holdings[t]['max_close'] / holdings[t]['entry_px'] - 1) * 100
            trade_rows.append({
                'date': date, 'ticker': t, 'side': 'SELL', 'reason': reason,
                'pnl_pct': pnl_pct, 'entry_date': holdings[t]['entry_date'],
                'hold_days': (date - holdings[t]['entry_date']).days,
                'entry_px': holdings[t]['entry_px'], 'exit_px': px,
                'max_gain_pct': max_gain, 'frac': 1.0,
                'signal': holdings[t].get('signal', ''),
            })
            del holdings[t]

        prev_idx = list(all_dates).index(date) - 1 if date in all_dates else None
        if prev_idx is not None and prev_idx >= 0:
            prev_date = all_dates[prev_idx]
            if prev_date in scan_set and market_check(prev_date):
                cands = v9.screen_v9(prev_date, data_ind, data, investor_data, None)
                cands = [c for c in cands if c['ticker'] not in holdings]
                slots = max_pos - len(holdings)
                if slots > 0 and cands:
                    cands = cands[:slots]
                    n = len(cands)
                    per_pos = cash / n if n > 0 else 0
                    for c in cands:
                        t = c['ticker']
                        df = data[t]
                        if date not in df.index: continue
                        px = float(df['Open'].loc[date])
                        if pd.isna(px) or px <= 0: continue
                        qty = int(per_pos / (px * (1 + FEE_RATE)))
                        if qty <= 0: continue
                        cost = qty * px * (1 + FEE_RATE)
                        if cost > cash:
                            qty = int(cash / (px * (1 + FEE_RATE)))
                            cost = qty * px * (1 + FEE_RATE)
                        if qty <= 0: continue
                        cash -= cost
                        holdings[t] = {'qty': qty, 'entry_px': px,
                                       'entry_date': date, 'max_close': px,
                                       'max_close_date': date,
                                       'initial_cost': cost,
                                       'pyramid_done': False,
                                       'signal': c['signals']}

        hv = 0.0
        for t, h in holdings.items():
            if date in data[t].index:
                cl = float(data[t]['Close'].loc[date])
                hv += h['qty'] * (cl if pd.notna(cl) else h['entry_px'])
            else:
                hv += h['qty'] * h['entry_px']
        eq_rows.append({'Date': date, 'Total_Money': cash + hv, 'NumHold': len(holdings)})

    return pd.DataFrame(eq_rows).set_index('Date'), pd.DataFrame(trade_rows)


def main():
    print("="*78)
    print("RocketHunter v23 — Entry quality 강화")
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
    check = make_lowvol_filter(kqd, 0.07)
    class D:
        sig_A = True; sig_B = False; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)

    print("="*78)
    print("[Sweep] 10 entry-quality variants")
    print("="*78)
    results = []
    for vc in CONFIGS:
        v9.screen_v9 = make_screen_v23(vc, investor_data)
        eq, tr = simulate_v23(data, data_ind, all_scan, investor_data, cfg,
                              ALL_START, ALL_END, exit_cfg, ec, 5, check, vc)
        cagr, mdd, _ = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        u100 = unique_100pct_count(tr)
        n = ts['n'] if ts else 0
        gt100 = ts['gt100'] if ts else 0
        win = ts['win'] if ts else 0
        mean = ts['mean'] if ts else 0
        # HARDSTOP/MA200 count
        hs = (tr['reason']=='HARDSTOP').sum() if len(tr)>0 else 0
        ma = (tr['reason']=='MA200').sum() if len(tr)>0 else 0
        be = (tr['reason']=='BE_EXIT').sum() if len(tr)>0 else 0
        print(f"\n  [{vc.name}] be={vc.early_be_days}d/{vc.early_be_thresh} "
              f"ma200max={vc.ma200_max_dist} for5d={vc.foreign_5d_min_days}")
        print(f"    CAGR {cagr:+.1f}% MDD {mdd:+.1f}% C/M {cagr/abs(mdd):.2f} "
              f"n={n} win {win:.0f}% mean {mean:+.1f}%")
        print(f"    +100%:{gt100} u100:{u100} HS:{hs} MA200:{ma} BE:{be}")
        results.append({'name': vc.name, 'eq': eq, 'tr': tr, 'cagr': cagr, 'mdd': mdd,
                        'gt100': gt100, 'u100': u100, 'n': n, 'win': win, 'mean': mean,
                        'hs': hs, 'ma': ma, 'be': be})

    print("\n" + "="*78)
    print("[Summary]")
    print("="*78)
    print(f"  {'name':12s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} {'+100%':>5s} "
          f"{'HS':>3s} {'MA':>3s} {'BE':>3s} {'win':>4s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        print(f"  {r['name']:12s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt100']:>5d} {r['hs']:>3d} {r['ma']:>3d} {r['be']:>3d} "
              f"{r['win']:>3.0f}% {r['n']:>3d}")

    qualified = [r for r in results if r['cagr'] >= 100 and r['gt100'] >= 1]
    if qualified:
        best = max(qualified, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → 자율 선택: {best['name']}")
        best['eq'].to_csv(OUT_DIR / 'rocket_v23_best_equity.csv')
        best['tr'].to_csv(OUT_DIR / 'rocket_v23_best_trades.csv', index=False)
    else:
        print("\n  → no qualified variant (no improvement)")


if __name__ == '__main__':
    main()
