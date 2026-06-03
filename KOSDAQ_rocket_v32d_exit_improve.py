# -*- coding: utf-8 -*-
"""V32D — 흑자→적자 전환 방지 exit 룰 개선 검증.

배경: 2026-04 6 entries 중 4건이 흑자→적자 전환 (max +5~30% → -10~-16%).
원인: 현재 STALL/TRAIL 룰이 max_gain >= 30% 부터만 작동.

3가지 가설 백테스트:
  A. BE_STOP: max_gain >= N% 도달 후 close < entry → BE_STOP (N = 5/7/10)
  B. Early Trail: STALL/TRAIL threshold 30% → 10%/15%
  C. Tighter HARDSTOP: -10% → -7% / -8%

기준 config: vol 1.9 ma 1.40 (V32C 채택)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, INIT_CAPITAL, FEE_RATE, MAX_HOLD_DAYS, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
import KOSDAQ_rocket_v9_ensemble as v9


def make_screen_vol19_ma140(investor_data):
    """V_FINAL new config entry screen."""
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
            if not (row['Volume'] > 1.9 * row['VolAvg50']): continue
            if (row['Close'] / row['MA200']) > 1.40: continue
            if not has_foreign_buy(investor_data, ticker, date, 20): continue
            cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


def exit_check_v32d(df, df_ind, idx, h, days_since_peak, days_held, hyp):
    """V11 base + 3 hypotheses."""
    yc = float(df['Close'].iloc[idx - 1])
    if pd.isna(yc): return None
    entry_px = h['entry_px']
    max_close = h['max_close']
    max_gain = (max_close / entry_px - 1) * 100

    # Hypothesis C: tighter HARDSTOP
    hs_pct = hyp.get('hardstop_pct', 0.10)
    if days_held < 30 and yc < entry_px * (1 - hs_pct):
        return 'HARDSTOP'

    # Hypothesis A: BE_STOP — once max_gain >= be_thresh, exit if close < entry
    be_thresh = hyp.get('be_thresh', None)
    if be_thresh is not None and max_gain >= be_thresh and yc < entry_px:
        return 'BE_STOP'

    # Hypothesis B: STALL/TRAIL activate at lower threshold
    stall_threshold = hyp.get('stall_threshold', 30)

    if max_gain >= stall_threshold:
        if days_since_peak >= 20:
            if yc < max_close * 0.90: return 'STALL20_T10'
            ma20_y = df_ind['MA20'].iloc[idx-1]
            if pd.notna(ma20_y) and yc < ma20_y: return 'STALL20_MA20'
        elif days_since_peak >= 10:
            if yc < max_close * 0.85: return 'STALL10_T15'
        elif days_since_peak >= 5:
            if yc < max_close * 0.75: return 'STALL5_T25'

    if max_gain >= 100:
        ma10_y = df_ind['MA10'].iloc[idx-1]
        if pd.notna(ma10_y) and yc < ma10_y: return 'FAST_MA10'
    elif max_gain >= 50:
        ma20_y = df_ind['MA20'].iloc[idx-1]
        if pd.notna(ma20_y) and yc < ma20_y: return 'FAST_MA20'

    if max_gain >= 30:
        ret_5d_y = df_ind['Ret_5d'].iloc[idx-1]
        if pd.notna(ret_5d_y) and ret_5d_y > 0.12:
            y_open = float(df['Open'].iloc[idx-1])
            if pd.notna(y_open) and yc < y_open:
                return 'PARABOLIC'

    if max_gain >= 100:
        if yc < max_close * 0.65: return 'TRAIL35'
        ma50_y = df_ind['MA50'].iloc[idx-1]
        if pd.notna(ma50_y) and yc < ma50_y: return 'MA50'
    elif max_gain >= 50:
        if yc < max_close * 0.70: return 'TRAIL30'
        ma50_y = df_ind['MA50'].iloc[idx-1]
        if pd.notna(ma50_y) and yc < ma50_y: return 'MA50'
    elif max_gain >= 30:
        if yc < max_close * 0.75: return 'TRAIL25'

    ma200_y = df_ind['MA200'].iloc[idx-1]
    if pd.notna(ma200_y) and yc < ma200_y:
        return 'MA200'

    if days_held >= MAX_HOLD_DAYS:
        return 'TIME'
    return None


def simulate_v32d(data, data_ind, scan_dates, investor_data, sim_s, sim_e,
                   max_pos, market_check, hyp):
    cash = INIT_CAPITAL
    holdings = {}
    eq_rows = []
    trade_rows = []
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    sim_dates = all_dates[(all_dates >= sim_s) & (all_dates <= sim_e)]
    scan_set = set(scan_dates)

    for date in sim_dates:
        # update max_close
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
            reason = exit_check_v32d(df, data_ind[t], idx, h,
                                       days_since_peak, days_held, hyp)
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
                                       'initial_cost': cost}

        hv = 0.0
        for t, h in holdings.items():
            if date in data[t].index:
                cl = float(data[t]['Close'].loc[date])
                hv += h['qty'] * (cl if pd.notna(cl) else h['entry_px'])
            else:
                hv += h['qty'] * h['entry_px']
        eq_rows.append({'Date': date, 'Total_Money': cash + hv, 'NumHold': len(holdings)})

    return pd.DataFrame(eq_rows).set_index('Date'), pd.DataFrame(trade_rows)


def run_variant(data, data_ind, all_scan, investor_data, check, hyp):
    v9.screen_v9 = make_screen_vol19_ma140(investor_data)
    eq, tr = simulate_v32d(data, data_ind, all_scan, investor_data,
                            ALL_START, ALL_END, 6, check, hyp)
    cagr, mdd, final = stats(eq, INIT_CAPITAL)
    ts = trade_stats(tr)
    u100 = unique_100pct_count(tr)
    sells = tr[tr['side']=='SELL'] if len(tr)>0 else pd.DataFrame()
    be_count = (sells['reason']=='BE_STOP').sum() if len(sells)>0 else 0
    # 흑자→적자 전환 비율: max_gain > 0% & pnl_pct <= 0%
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
            'be_count': be_count,
            'loss_with_max': loss_with_max,
            'eq': eq, 'tr': tr}


def main():
    print("="*78)
    print("V32D — Exit 룰 개선 (A: BE_STOP, B: Early Trail, C: Tighter HARDSTOP)")
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
        # (name, hyp_dict)
        ('baseline',     {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 30}),
        # Hypothesis A: BE_STOP
        ('A_BE_5',       {'hardstop_pct': 0.10, 'be_thresh': 5,    'stall_threshold': 30}),
        ('A_BE_7',       {'hardstop_pct': 0.10, 'be_thresh': 7,    'stall_threshold': 30}),
        ('A_BE_10',      {'hardstop_pct': 0.10, 'be_thresh': 10,   'stall_threshold': 30}),
        # Hypothesis B: Early STALL/TRAIL
        ('B_stall_15',   {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 15}),
        ('B_stall_10',   {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 10}),
        ('B_stall_20',   {'hardstop_pct': 0.10, 'be_thresh': None, 'stall_threshold': 20}),
        # Hypothesis C: Tighter HARDSTOP
        ('C_HS_7',       {'hardstop_pct': 0.07, 'be_thresh': None, 'stall_threshold': 30}),
        ('C_HS_8',       {'hardstop_pct': 0.08, 'be_thresh': None, 'stall_threshold': 30}),
        # Combos
        ('A5_C7',        {'hardstop_pct': 0.07, 'be_thresh': 5,    'stall_threshold': 30}),
        ('A10_B15',      {'hardstop_pct': 0.10, 'be_thresh': 10,   'stall_threshold': 15}),
        ('A10_B15_C8',   {'hardstop_pct': 0.08, 'be_thresh': 10,   'stall_threshold': 15}),
    ]

    results = []
    for name, hyp in variants:
        r = run_variant(data, data_ind, all_scan, investor_data, check, hyp)
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        print(f"\n  [{name}] HS={hyp['hardstop_pct']*100:.0f}% "
              f"BE={hyp['be_thresh']} STALL={hyp['stall_threshold']}%")
        print(f"    CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% C/M {cm:.2f} "
              f"n={r['n']} win={r['win']:.0f}% mean={r['mean']:+.1f}%")
        print(f"    +100%:{r['gt100']} u100:{r['u100']} BE_STOP:{r['be_count']} "
              f"loss_with_max>5%: {r['loss_with_max']}")
        results.append({'name': name, **r, 'hyp': hyp})

    # Summary
    print(f"\n{'='*78}\n[Summary] vs baseline\n{'='*78}")
    baseline = next(r for r in results if r['name'] == 'baseline')
    print(f"  baseline: CAGR {baseline['cagr']:+.1f}%, MDD {baseline['mdd']:+.1f}%, "
          f"C/M {baseline['cagr']/abs(baseline['mdd']):.2f}\n")
    print(f"  {'name':14s} {'CAGR':>8s} {'MDD':>8s} {'C/M':>5s} {'n':>3s} "
          f"{'win':>4s} {'+100%':>5s} {'BE':>3s} {'loss>5%':>7s} {'ΔCAGR':>7s} {'ΔMDD':>7s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        dcagr = r['cagr'] - baseline['cagr']
        dmdd = r['mdd'] - baseline['mdd']
        print(f"  {r['name']:14s} {r['cagr']:>+7.1f}% {r['mdd']:>+7.1f}% {cm:>5.2f} "
              f"{r['n']:>3d} {r['win']:>3.0f}% {r['gt100']:>5d} "
              f"{r['be_count']:>3d} {r['loss_with_max']:>7d} "
              f"{dcagr:>+6.1f}pp {dmdd:>+6.1f}pp")

    # Best
    print(f"\n  CAGR improvement winners:")
    improved = [r for r in results if r['name'] != 'baseline' and r['cagr'] > baseline['cagr']]
    if improved:
        for r in sorted(improved, key=lambda x: x['cagr'] - baseline['cagr'], reverse=True)[:3]:
            print(f"    {r['name']}: +{r['cagr']-baseline['cagr']:.1f}pp CAGR, "
                  f"{r['mdd']-baseline['mdd']:+.1f}pp MDD")
    else:
        print("    none improved baseline")

    print(f"\n  C/M improvement winners:")
    base_cm = baseline['cagr']/abs(baseline['mdd'])
    cm_improved = [r for r in results if r['name'] != 'baseline'
                    and (r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0) > base_cm]
    if cm_improved:
        for r in sorted(cm_improved, key=lambda x: x['cagr']/abs(x['mdd']), reverse=True)[:3]:
            cm = r['cagr']/abs(r['mdd'])
            print(f"    {r['name']}: C/M {cm:.2f} (baseline {base_cm:.2f})")


if __name__ == '__main__':
    main()
