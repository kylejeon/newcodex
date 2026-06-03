# -*- coding: utf-8 -*-
"""
RocketHunter v17 — 시장 timing filter + cooldown (2024 같은 평년 보호).

V14 발견: 2024 가 +2.6% (HARDSTOP 4/8 trades, 50% loss rate)
V17 시도:
  1. KOSDAQ index trend filter: KOSDAQ MA50 above → entry OK
  2. KOSDAQ MA200 slope > 0 일 때만 entry
  3. HARDSTOP cooldown 7일 (직후 같은 ticker re-entry 차단)
  4. 시장 변동성 filter: VIX 대용 (KOSDAQ 14-day return abs > 7% bear)

검증된 best: par=0.12 exit
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import NamedTuple
import pandas as pd
import urllib.request, io, json

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, OUT_DIR, INIT_CAPITAL, FEE_RATE, MAX_HOLD_DAYS, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v9b_strict import make_screen_v9b, BCfg
from KOSDAQ_rocket_v11_exit import ExitCfg, exit_check_v11
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
import KOSDAQ_rocket_v9_ensemble as v9

B5_TIGHT = BCfg('B5_tight', 2.0, 20, True, 0.02)

KOSDAQ_CACHE = Path(__file__).resolve().parent / 'kosdaq_index_cache.csv'


def fetch_kosdaq_index():
    if KOSDAQ_CACHE.exists():
        try:
            df = pd.read_csv(KOSDAQ_CACHE, index_col=0, parse_dates=[0])
            if len(df) > 500:
                return df
        except: pass
    # yfinance
    import yfinance as yf
    df = yf.download('^KQ11', start='2020-06-01', end='2026-06-30', progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[['Open','High','Low','Close','Volume']].copy()
    df.to_csv(KOSDAQ_CACHE)
    return df


def make_kosdaq_filter(idx_df, mode):
    """returns function(date) -> bool (entry OK?)."""
    if idx_df is None:
        return lambda d: True
    idx_df = idx_df.copy()
    idx_df['MA50']  = idx_df['Close'].rolling(50).mean()
    idx_df['MA200'] = idx_df['Close'].rolling(200).mean()
    idx_df['MA200_slope'] = idx_df['MA200'] - idx_df['MA200'].shift(20)
    idx_df['Ret14d_abs'] = idx_df['Close'].pct_change(14).abs()

    def check(date):
        if date not in idx_df.index:
            d_match = idx_df.index[idx_df.index <= date]
            if len(d_match) == 0: return True
            date = d_match[-1]
        row = idx_df.loc[date]
        if mode == 'none':
            return True
        if mode == 'ma50':
            return pd.notna(row['MA50']) and row['Close'] > row['MA50']
        if mode == 'ma200':
            return pd.notna(row['MA200']) and row['Close'] > row['MA200']
        if mode == 'ma200_slope':
            return (pd.notna(row['MA200']) and pd.notna(row['MA200_slope'])
                    and row['Close'] > row['MA200'] and row['MA200_slope'] > 0)
        if mode == 'low_vol':
            return pd.notna(row['Ret14d_abs']) and row['Ret14d_abs'] < 0.07
        return True
    return check


def portfolio_simulate_v17(data, data_ind, scan_dates, investor_data,
                            cfg, sim_s, sim_e, exit_cfg, ec,
                            max_positions, market_check, cooldown_days):
    cash = INIT_CAPITAL
    holdings = {}
    eq_rows = []
    trade_rows = []
    last_hardstop = {}  # ticker -> date of last HARDSTOP

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
            except KeyError:
                continue
            if idx == 0: continue
            days_held = (date - h['entry_date']).days
            days_since_peak = (date - h['max_close_date']).days
            reason = exit_check_v11(df, data_ind[t], idx, h,
                                     days_since_peak, days_held, exit_cfg, ec)
            if reason:
                to_exit.append((t, reason, 1.0))

        for t, reason, frac in to_exit:
            df = data[t]
            px = float(df['Open'].loc[date])
            if pd.isna(px) or px <= 0: continue
            qty_sell = holdings[t]['qty']
            proceeds = qty_sell * px * (1 - FEE_RATE)
            cash += proceeds
            pnl_pct = (px / holdings[t]['entry_px'] - 1) * 100
            max_gain = (holdings[t]['max_close'] / holdings[t]['entry_px'] - 1) * 100
            trade_rows.append({
                'date': date, 'ticker': t, 'side': 'SELL', 'reason': reason,
                'pnl_pct': pnl_pct, 'entry_date': holdings[t]['entry_date'],
                'hold_days': (date - holdings[t]['entry_date']).days,
                'entry_px': holdings[t]['entry_px'], 'exit_px': px,
                'max_gain_pct': max_gain, 'frac': frac,
                'signal': holdings[t].get('signal', ''),
            })
            if reason == 'HARDSTOP':
                last_hardstop[t] = date
            del holdings[t]

        prev_idx = list(all_dates).index(date) - 1 if date in all_dates else None
        if prev_idx is not None and prev_idx >= 0:
            prev_date = all_dates[prev_idx]
            if prev_date in scan_set:
                # Market filter check
                if not market_check(prev_date):
                    pass  # skip entry
                else:
                    cands = v9.screen_v9(prev_date, data_ind, data, investor_data, None)
                    cands = [c for c in cands if c['ticker'] not in holdings]
                    # cooldown filter
                    if cooldown_days > 0:
                        cands = [c for c in cands
                                 if c['ticker'] not in last_hardstop or
                                 (date - last_hardstop[c['ticker']]).days > cooldown_days]
                    slots = max_positions - len(holdings)
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
    print("RocketHunter v17 — Market filter + cooldown")
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

    print("[kosdaq index] fetching...")
    try:
        kqd = fetch_kosdaq_index()
        print(f"  kosdaq index: {len(kqd)} rows")
    except Exception as e:
        print(f"  ERROR: {e}, skipping market filter")
        kqd = None

    v9.screen_v9 = make_screen_v9b(B5_TIGHT)
    class D:
        sig_A = True; sig_B = True; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)

    variants = [
        ('V17_baseline',   'none',         0),
        ('V17_cooldown7',  'none',         7),
        ('V17_cooldown14', 'none',         14),
        ('V17_ma50',       'ma50',         0),
        ('V17_ma200',      'ma200',        0),
        ('V17_ma200_sl',   'ma200_slope',  0),
        ('V17_lowvol',     'low_vol',      0),
        ('V17_ma200_cd7',  'ma200',        7),
        ('V17_sl_cd14',    'ma200_slope',  14),
    ]

    print("\n" + "="*78)
    print("[Sweep] market filter + cooldown")
    print("="*78)
    results = []
    for name, mode, cd in variants:
        check = make_kosdaq_filter(kqd, mode)
        eq, tr = portfolio_simulate_v17(data, data_ind, all_scan, investor_data,
                                         cfg, ALL_START, ALL_END, exit_cfg, ec, 5,
                                         check, cd)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        uniq = unique_100pct_count(tr)
        gt100 = ts['gt100'] if ts else 0
        gt200 = ts['gt200'] if ts else 0
        n = ts['n'] if ts else 0
        win = ts['win'] if ts else 0
        mean = ts['mean'] if ts else 0
        print(f"\n  [{name}] filter={mode} cooldown={cd}d")
        print(f"    CAGR {cagr:+.2f}%  MDD {mdd:+.2f}%  Final {final/1e6:.0f}M  "
              f"C/M {cagr/abs(mdd) if mdd != 0 else 0:.2f}")
        print(f"    n={n} win {win:.0f}% mean {mean:+.2f}% "
              f"+100%:{gt100} +200%:{gt200} u100:{uniq}")
        results.append({'name': name, 'eq': eq, 'tr': tr, 'cagr': cagr, 'mdd': mdd,
                        'gt100': gt100, 'gt200': gt200, 'uniq': uniq, 'n': n,
                        'win': win, 'mean': mean})

    print("\n" + "="*78)
    print("[Summary]")
    print("="*78)
    print(f"  {'name':18s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} "
          f"{'+100%':>5s} {'+200%':>5s} {'uniq':>5s} {'mean':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"  {r['name']:18s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt100']:>5d} {r['gt200']:>5d} {r['uniq']:>5d} "
              f"{r['mean']:>+5.1f}% {r['n']:>3d}")

    best = max(results, key=lambda r: r['cagr']/abs(r['mdd']) if r['cagr']>0 else -999)
    print(f"\n  → best C/M: {best['name']}")
    best['eq'].to_csv(OUT_DIR / 'rocket_v17_best_equity.csv')
    best['tr'].to_csv(OUT_DIR / 'rocket_v17_best_trades.csv', index=False)
    print(f"\n[save] rocket_v17_best_*.csv")


if __name__ == '__main__':
    main()
