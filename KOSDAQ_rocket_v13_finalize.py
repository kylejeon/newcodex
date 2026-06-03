# -*- coding: utf-8 -*-
"""
RocketHunter v13 — Final candidate 검증 + 추가 par threshold/position tuning.

V11 발견:
  - E2_par20 (PARABOLIC 5d→0.20): CAGR +104%, +200% 2건 ⭐ best CAGR
  - E7_combo (partial + par20 + stall3): rocket 6/3건 ⭐ best rocket count

V13 진행:
  1. E2_par20 그대로 walk-forward
  2. par threshold 추가 sweep (0.15, 0.25)
  3. Position size sweep (3, 5, 7)
  4. E7 의 +100% rocket unique ticker 검증
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
from KOSDAQ_rocket_v9b_strict import make_screen_v9b, BCfg
from KOSDAQ_rocket_v11_exit import ExitCfg, portfolio_simulate_v11
import KOSDAQ_rocket_v9_ensemble as v9

B5_TIGHT = BCfg('B5_tight', 2.0, 20, True, 0.02)


# Patch portfolio_simulate_v11 to support variable max_positions
def portfolio_simulate_v13(data, data_ind, scan_dates, investor_data,
                            cfg, sim_s, sim_e, exit_cfg, ec, max_positions=5):
    """v11 simulate + max_positions parameter."""
    from KOSDAQ_rocket_v11_exit import exit_check_v11
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
            except KeyError:
                continue
            if idx == 0: continue
            days_held = (date - h['entry_date']).days
            days_since_peak = (date - h['max_close_date']).days
            reason = exit_check_v11(df, data_ind[t], idx, h,
                                     days_since_peak, days_held, exit_cfg, ec)
            if reason:
                if reason.startswith('PARTIAL'):
                    to_exit.append((t, reason, 1/3))
                else:
                    to_exit.append((t, reason, 1.0))

        for t, reason, frac in to_exit:
            df = data[t]
            px = float(df['Open'].loc[date])
            if pd.isna(px) or px <= 0: continue
            qty_sell = int(holdings[t]['qty'] * frac) if frac < 1.0 else holdings[t]['qty']
            if qty_sell <= 0: continue
            proceeds = qty_sell * px * (1 - FEE_RATE)
            cash += proceeds
            pnl_pct = (px / holdings[t]['entry_px'] - 1) * 100
            max_gain = (holdings[t]['max_close'] / holdings[t]['entry_px'] - 1) * 100
            trade_rows.append({
                'date': date, 'ticker': t, 'side': 'SELL', 'reason': reason,
                'pnl_pct': pnl_pct, 'entry_date': holdings[t]['entry_date'],
                'hold_days': (date - holdings[t]['entry_date']).days,
                'entry_px': holdings[t]['entry_px'], 'exit_px': px,
                'max_gain_pct': max_gain,
                'frac': frac,
                'signal': holdings[t].get('signal', ''),
            })
            holdings[t]['qty'] -= qty_sell
            if holdings[t]['qty'] <= 0:
                del holdings[t]

        prev_idx = list(all_dates).index(date) - 1 if date in all_dates else None
        if prev_idx is not None and prev_idx >= 0:
            prev_date = all_dates[prev_idx]
            if prev_date in scan_set:
                cands = v9.screen_v9(prev_date, data_ind, data, investor_data, None)
                cands = [c for c in cands if c['ticker'] not in holdings]
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


def unique_100pct_count(tr):
    """+100% 도달 unique ticker 카운트 (partial 중복 제거)."""
    sells = tr[tr['side']=='SELL']
    pos = sells[sells['pnl_pct'] >= 100]
    return pos['ticker'].nunique()


def main():
    print("="*78)
    print("RocketHunter v13 — Final candidate verification + tuning")
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

    # Screen: V9b_B5_tight
    v9.screen_v9 = make_screen_v9b(B5_TIGHT)
    class D:
        sig_A = True; sig_B = True; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)

    # Variations:
    # par threshold sweep (0.15, 0.20, 0.25)
    # position sweep (3, 5, 7)
    # partial on/off
    variants = [
        # (name, ExitCfg, max_pos)
        ('E2_par20_pos5',      ExitCfg('e', False, 0.20, 5, False, 3.0), 5),
        ('E2_par15_pos5',      ExitCfg('e', False, 0.15, 5, False, 3.0), 5),
        ('E2_par25_pos5',      ExitCfg('e', False, 0.25, 5, False, 3.0), 5),
        ('E2_par20_pos3',      ExitCfg('e', False, 0.20, 5, False, 3.0), 3),
        ('E2_par20_pos7',      ExitCfg('e', False, 0.20, 5, False, 3.0), 7),
        ('E7_combo_pos5',      ExitCfg('e', True,  0.20, 3, False, 3.0), 5),
        ('E7_combo_pos7',      ExitCfg('e', True,  0.20, 3, False, 3.0), 7),
        ('E8_par20_partial',   ExitCfg('e', True,  0.20, 5, False, 3.0), 5),
        ('E9_par15_partial',   ExitCfg('e', True,  0.15, 5, False, 3.0), 5),
    ]

    print("="*78)
    print("[Sweep] 9 variants — par threshold + position + partial")
    print("="*78)
    results = []
    for name, ec, max_pos in variants:
        eq, tr = portfolio_simulate_v13(data, data_ind, all_scan, investor_data,
                                         cfg, ALL_START, ALL_END, exit_cfg, ec, max_pos)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        uniq100 = unique_100pct_count(tr)
        print(f"\n  [{name}] partial={ec.use_partial} par={ec.parabolic_5d} pos={max_pos}")
        print(f"    CAGR {cagr:+.2f}%  MDD {mdd:+.2f}%  Final {final/1e6:.0f}M  "
              f"C/M {cagr/abs(mdd) if mdd != 0 else 0:.2f}")
        if ts:
            print(f"    Trades {ts['n']}, win {ts['win']:.0f}%, mean {ts['mean']:+.2f}%")
            print(f"    +50%:{ts['gt50']}  +100%:{ts['gt100']}  +200%:{ts['gt200']}  "
                  f"best {ts['best']:+.0f}%, unique +100% tickers: {uniq100}")
        results.append({'name': name, 'eq': eq, 'tr': tr,
                        'cagr': cagr, 'mdd': mdd, 'max_pos': max_pos,
                        'gt100': ts['gt100'] if ts else 0,
                        'gt200': ts['gt200'] if ts else 0,
                        'uniq100': uniq100,
                        'mean': ts['mean'] if ts else 0,
                        'n':    ts['n']    if ts else 0,
                        'win':  ts['win']  if ts else 0})

    print("\n" + "="*78)
    print("[Summary]")
    print("="*78)
    print(f"  {'name':22s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} "
          f"{'+100%':>5s} {'+200%':>5s} {'uniq100':>7s} {'mean':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"  {r['name']:22s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt100']:>5d} {r['gt200']:>5d} {r['uniq100']:>7d} "
              f"{r['mean']:>+5.1f}% {r['n']:>3d}")

    # Top trades for the best CAGR config
    best = max(results, key=lambda r: r['cagr'])
    print(f"\n  → 자율 best CAGR: {best['name']}")
    print(f"  [Top 15 trades by pnl] — {best['name']}")
    sells = best['tr'][best['tr']['side']=='SELL']
    if len(sells) > 0:
        top = sells.sort_values('pnl_pct', ascending=False).head(15).copy()
        top['name'] = top['ticker'].astype(str).map(name_map)
        for _, t in top.iterrows():
            d = pd.Timestamp(t['date']).date()
            sig = t.get('signal', '?')
            print(f"    {str(d):>11s} {str(t['ticker']):>7s} {str(t['name'] or '')[:18]:<18s} "
                  f"{int(t['hold_days']):>3d}d [{sig:>3s}] {str(t['reason']):>14s} "
                  f"exit {t['pnl_pct']:>+6.0f}%  max {t['max_gain_pct']:>+6.0f}%")

    best['eq'].to_csv(OUT_DIR / 'rocket_v13_best_equity.csv')
    best['tr'].to_csv(OUT_DIR / 'rocket_v13_best_trades.csv', index=False)
    print(f"\n[save] rocket_v13_best_*.csv")


if __name__ == '__main__':
    main()
