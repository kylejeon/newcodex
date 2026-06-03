# -*- coding: utf-8 -*-
"""
RocketHunter v11 — Exit 최적화 (partial profit lock + PARABOLIC tuning).

V9b_B5_tight base (CAGR +57%, MDD -38.6%) 의 exit 변형:
  Idea 1: Partial profit lock — +50%/+100%/+200% 도달 시 1/3 매도 (잔여 winner runner)
  Idea 2: PARABOLIC threshold tuning — 5d +30% (현재) vs 5d +20%/+40%
  Idea 3: 적극적 stall — 3일 정체 시 trail 20% (현재 5일)
  Idea 4: ATR-based trail — peak 에서 ATR×3 trail
  Idea 5: chandelier exit — High × N - ATR × K
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
import KOSDAQ_rocket_v9_ensemble as v9

B5_TIGHT = BCfg('B5_tight', 2.0, 20, True, 0.02)


class ExitCfg(NamedTuple):
    name: str
    use_partial: bool       # +50/100/200 partial profit lock (1/3씩)
    parabolic_5d: float     # 5d threshold (0.30 default)
    stall_5d_thresh: int    # stall trigger days (5 default)
    use_atr_trail: bool     # ATR×N trail from peak
    atr_mult: float


EXIT_CONFIGS = [
    ExitCfg('E0_baseline',  False, 0.30, 5, False, 3.0),
    ExitCfg('E1_partial',   True,  0.30, 5, False, 3.0),
    ExitCfg('E2_par20',     False, 0.20, 5, False, 3.0),
    ExitCfg('E3_par40',     False, 0.40, 5, False, 3.0),
    ExitCfg('E4_stall3',    False, 0.30, 3, False, 3.0),
    ExitCfg('E5_atr3',      False, 0.30, 5, True,  3.0),
    ExitCfg('E6_atr5',      False, 0.30, 5, True,  5.0),
    ExitCfg('E7_combo',     True,  0.20, 3, False, 3.0),
]


def exit_check_v11(df, df_ind, idx, h, days_since_peak, days_held, cfg, ec):
    """v8 base + partial profit + variations."""
    yc = float(df['Close'].iloc[idx - 1])
    if pd.isna(yc): return None
    entry_px = h['entry_px']
    max_close = h['max_close']

    if days_held < 30 and yc < entry_px * 0.90:
        return 'HARDSTOP'

    max_gain = (max_close / entry_px - 1) * 100
    cur_gain = (yc / entry_px - 1) * 100

    # E1/E7: Partial profit lock (한 번씩만)
    if ec.use_partial:
        # +50% trigger: 1/3 매도
        if cur_gain >= 50 and not h.get('p50'):
            h['p50'] = True
            return 'PARTIAL50'
        if cur_gain >= 100 and not h.get('p100'):
            h['p100'] = True
            return 'PARTIAL100'
        if cur_gain >= 200 and not h.get('p200'):
            h['p200'] = True
            return 'PARTIAL200'

    # Peak-stall escalation (5/10/20 day or custom)
    if max_gain >= 30:
        if days_since_peak >= 20:
            if yc < max_close * 0.90: return 'STALL20_T10'
            ma20_y = df_ind['MA20'].iloc[idx-1]
            if pd.notna(ma20_y) and yc < ma20_y: return 'STALL20_MA20'
        elif days_since_peak >= 10:
            if yc < max_close * 0.85: return 'STALL10_T15'
        elif days_since_peak >= ec.stall_5d_thresh:
            if yc < max_close * 0.75: return 'STALL5_T25'

    # Fast MA
    if max_gain >= 100:
        ma10_y = df_ind['MA10'].iloc[idx-1]
        if pd.notna(ma10_y) and yc < ma10_y: return 'FAST_MA10'
    elif max_gain >= 50:
        ma20_y = df_ind['MA20'].iloc[idx-1]
        if pd.notna(ma20_y) and yc < ma20_y: return 'FAST_MA20'

    # Parabolic (tunable threshold)
    if max_gain >= 30:
        ret_5d_y = df_ind['Ret_5d'].iloc[idx-1]
        if pd.notna(ret_5d_y) and ret_5d_y > ec.parabolic_5d:
            y_open = float(df['Open'].iloc[idx-1])
            if pd.notna(y_open) and yc < y_open:
                return 'PARABOLIC'

    # ATR trail
    if ec.use_atr_trail and max_gain >= 30:
        atr10 = df_ind['ATR10'].iloc[idx-1]
        if pd.notna(atr10):
            trail_price = max_close - ec.atr_mult * atr10
            if yc < trail_price:
                return f'ATR_TRAIL{int(ec.atr_mult)}'

    # v4 max gain bracket trail
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


def portfolio_simulate_v11(data, data_ind, scan_dates, investor_data,
                            cfg, sim_s, sim_e, exit_cfg, ec):
    """v8 simulate 변형 — partial profit 시 1/3 매도 (전체 X)."""
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

        to_exit = []  # (ticker, reason, partial_frac)
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
                slots = 5 - len(holdings)
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
    print("RocketHunter v11 — Exit 최적화 ablation")
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

    # Screen 은 V9b_B5_tight 고정
    v9.screen_v9 = make_screen_v9b(B5_TIGHT)
    class DummyCfg:
        sig_A = True; sig_B = True; sig_C = False; sig_D = False
    cfg_dummy = DummyCfg()
    exit_cfg = v8_cfg('exit', vol=2.0)

    print("="*78)
    print("[Sweep] 8 exit variants (B5_tight screener 고정)")
    print("="*78)
    results = []
    for ec in EXIT_CONFIGS:
        eq, tr = portfolio_simulate_v11(data, data_ind, all_scan, investor_data,
                                         cfg_dummy, ALL_START, ALL_END, exit_cfg, ec)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"\n  [{ec.name}] partial={ec.use_partial} par={ec.parabolic_5d} "
              f"stall={ec.stall_5d_thresh} atr={ec.use_atr_trail}×{ec.atr_mult}")
        print(f"    CAGR {cagr:+.2f}%  MDD {mdd:+.2f}%  Final {final/1e6:.0f}M  "
              f"C/M {cagr/abs(mdd) if mdd != 0 else 0:.2f}")
        if ts:
            print(f"    Trades {ts['n']}, win {ts['win']:.0f}%, mean {ts['mean']:+.2f}%")
            print(f"    +50%:{ts['gt50']}  +100%:{ts['gt100']}  +200%:{ts['gt200']}  "
                  f"best {ts['best']:+.0f}%")
            print(f"    Give-back: {ts['avg_giveback_pp']:.1f}pp")
        results.append({'cfg': ec, 'eq': eq, 'tr': tr,
                        'cagr': cagr, 'mdd': mdd,
                        'gt100': ts['gt100'] if ts else 0,
                        'gt200': ts['gt200'] if ts else 0,
                        'gt50':  ts['gt50']  if ts else 0,
                        'best':  ts['best']  if ts else 0,
                        'mean':  ts['mean']  if ts else 0,
                        'n':     ts['n']     if ts else 0,
                        'giveback': ts['avg_giveback_pp'] if ts else 0})

    print("\n" + "="*78)
    print("[Summary]")
    print("="*78)
    print(f"  {'config':14s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} "
          f"{'+100%':>5s} {'+200%':>5s} {'mean':>6s} {'gv':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"  {r['cfg'].name:14s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt100']:>5d} {r['gt200']:>5d} "
              f"{r['mean']:>+5.1f}% {r['giveback']:>5.1f}pp {r['n']:>3d}")

    qualified = [r for r in results if r['cagr'] >= 50 and r['gt100'] >= 2]
    if qualified:
        best = max(qualified, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → 자율 선택: {best['cfg'].name}")
    else:
        best = max(results, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → fallback: {best['cfg'].name}")

    best['eq'].to_csv(OUT_DIR / 'rocket_v11_best_equity.csv')
    best['tr'].to_csv(OUT_DIR / 'rocket_v11_best_trades.csv', index=False)
    print(f"\n[save] rocket_v11_best_*.csv")


if __name__ == '__main__':
    main()
