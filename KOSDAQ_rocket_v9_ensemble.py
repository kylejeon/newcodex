# -*- coding: utf-8 -*-
"""
RocketHunter v9 — Multi-signal ensemble for rocket discovery 증대.

V8H4_vol2 base + 3 alternative entry signals (OR 결합):
  Signal A (V8H4): vol 2.0x breakout, 52w 60% 이내
  Signal B (NewHigh): 52w high 5% 이내, vol 1.5x, 외인 5d > 0
  Signal C (Episodic): 갭상승 +5%, vol 3.0x, 외인 5d > 0
  Signal D (LowBase): 26주 base, 4주 high 돌파, vol 2.0x

목표: rocket capture 빈도 ↑ (5년 1건 → 3-5건 시도)
Exit: V8H4_vol2 동일 (peak protection + ratchet trail)
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import NamedTuple
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    exit_check_v8, stats, trade_stats, cfg as v8_cfg,
    CACHE_DIR, INVESTOR_DIR, UNIVERSE_CSV, OUT_DIR, INIT_CAPITAL,
    FEE_RATE, MAX_HOLD_DAYS, ALL_START, ALL_END,
)


class V9Cfg(NamedTuple):
    name: str
    sig_A: bool  # V8H4 baseline
    sig_B: bool  # New-high pivot
    sig_C: bool  # Episodic gap-up
    sig_D: bool  # Low-base breakout


CONFIGS = [
    V9Cfg('V8H4_only',     True,  False, False, False),
    V9Cfg('V9_AB',         True,  True,  False, False),
    V9Cfg('V9_AC',         True,  False, True,  False),
    V9Cfg('V9_AD',         True,  False, False, True),
    V9Cfg('V9_ABCD',       True,  True,  True,  True),
    V9Cfg('V9_BCD_only',   False, True,  True,  True),
]


def signal_A_v8h4(df, df_ind, date):
    """V8H4: vol 2.0x breakout, 52w 60% 이내"""
    row = df_ind.loc[date]
    if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                      'VolAvg10','ATR10','ATR50','Ret_252d','MA200']):
        return False
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
    return True


def signal_B_newhigh(df, df_ind, date):
    """52w high 5% 이내, vol 1.5x, 외인 5d > 0 (Stage 2)"""
    row = df_ind.loc[date]
    if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                      'MA200','Ret_252d']):
        return False
    if not (row['Close'] > row['MA60']): return False
    if not (row['Close'] > row['MA200']): return False
    if not (row['MA60_slope'] > 0): return False
    if row['Ret_252d'] < 0.30: return False
    if row['Ret_252d'] > 5.00: return False  # 작전주 완화
    # 신고가 근처 (5% 이내)
    dist = (row['High52w'] - row['Close']) / row['High52w']
    if dist > 0.05: return False
    if not (row['Volume'] > 1.5 * row['VolAvg50']): return False
    return True


def signal_C_episodic(df, df_ind, date):
    """갭상승 +5%, vol 3.0x, 외인 5d > 0"""
    row = df_ind.loc[date]
    if any(pd.isna(row[c]) for c in ['MA60','VolAvg50','Ret_252d','MA200']):
        return False
    if not (row['Close'] > row['MA60']): return False
    if not (row['Close'] > row['MA200']): return False
    if row['Ret_252d'] < 0.10: return False
    if row['Ret_252d'] > 5.00: return False
    # 갭상승: open 이 전일 close 보다 5%+
    idx = df.index.get_loc(date)
    if idx < 1: return False
    y_close = float(df['Close'].iloc[idx-1])
    o = float(df['Open'].iloc[idx-1] if False else df['Open'].loc[date])
    if pd.isna(y_close) or pd.isna(o) or y_close <= 0: return False
    if (o / y_close - 1) < 0.05: return False
    # 거래량 3.0x
    if not (row['Volume'] > 3.0 * row['VolAvg50']): return False
    # 종가 > 시가 (갭 메우지 않음)
    if not (row['Close'] > o): return False
    return True


def signal_D_lowbase(df, df_ind, date):
    """26주 base, 4주 high 돌파, vol 2.0x"""
    row = df_ind.loc[date]
    if any(pd.isna(row[c]) for c in ['MA60','VolAvg50','ATR10','ATR50','Ret_252d','MA200']):
        return False
    if not (row['Close'] > row['MA60']): return False
    if not (row['Close'] > row['MA200']): return False
    if row['Ret_252d'] < 0.0: return False  # 1년 음수 X
    if row['Ret_252d'] > 5.00: return False
    # 26주 high-low range / mean < 0.30 (base 형성)
    cl_130 = df['Close'].iloc[max(0, df.index.get_loc(date)-130):df.index.get_loc(date)]
    if len(cl_130) < 100: return False
    base_range = (cl_130.max() - cl_130.min()) / cl_130.mean()
    if base_range > 0.50: return False  # base 좁아야
    # 4주 high (20일) 돌파
    high_20 = df['Close'].rolling(20).max().shift(1).loc[date]
    if pd.isna(high_20): return False
    if not (row['Close'] > high_20): return False
    # vol 2.0x
    if not (row['Volume'] > 2.0 * row['VolAvg50']): return False
    return True


def has_foreign_buy(investor_data, ticker, date, days):
    inv = investor_data.get(ticker)
    if inv is None: return False
    pre = inv[inv.index <= date]
    if len(pre) < days: return False
    return pre['Foreign_Net'].tail(days).sum() > 0


def screen_v9(date, data_ind, data, investor_data, cfg):
    cands = []
    for ticker, df in data.items():
        df_ind = data_ind[ticker]
        if date not in df_ind.index: continue
        # OHLCV check
        row = df_ind.loc[date]
        if pd.isna(row['Close']): continue

        signals = []
        if cfg.sig_A and signal_A_v8h4(df, df_ind, date):
            if has_foreign_buy(investor_data, ticker, date, 20):
                signals.append('A')
        if cfg.sig_B and signal_B_newhigh(df, df_ind, date):
            if has_foreign_buy(investor_data, ticker, date, 5):
                signals.append('B')
        if cfg.sig_C and signal_C_episodic(df, df_ind, date):
            if has_foreign_buy(investor_data, ticker, date, 5):
                signals.append('C')
        if cfg.sig_D and signal_D_lowbase(df, df_ind, date):
            if has_foreign_buy(investor_data, ticker, date, 20):
                signals.append('D')

        if signals:
            cands.append({'ticker': ticker, 'close': row['Close'],
                          'signals': ','.join(signals)})
    return cands


def portfolio_simulate_v9(data, data_ind, scan_dates, investor_data, cfg,
                          sim_s, sim_e, exit_cfg):
    cash = INIT_CAPITAL
    holdings = {}
    eq_rows = []
    trade_rows = []

    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    sim_dates = all_dates[(all_dates >= sim_s) & (all_dates <= sim_e)]
    scan_set = set(scan_dates)

    for date in sim_dates:
        # Update max_close
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
            reason = exit_check_v8(df, data_ind[t], idx, h,
                                    days_since_peak, days_held, exit_cfg)
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
                'max_gain_pct': max_gain,
                'signal': holdings[t].get('signal', ''),
            })
            del holdings[t]

        prev_idx = list(all_dates).index(date) - 1 if date in all_dates else None
        if prev_idx is not None and prev_idx >= 0:
            prev_date = all_dates[prev_idx]
            if prev_date in scan_set:
                cands = screen_v9(prev_date, data_ind, data, investor_data, cfg)
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
    print("RocketHunter v9 — Multi-signal ensemble (rocket discovery 증대)")
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

    # Exit config: V8H4_vol2 (vol 2.0 but exit_check_v8 doesn't care)
    exit_cfg = v8_cfg('exit', vol=2.0)

    print("="*78)
    print("[Sweep] V9 configs — base + alt signals OR")
    print("="*78)
    results = []
    for c in CONFIGS:
        eq, tr = portfolio_simulate_v9(data, data_ind, all_scan, investor_data,
                                        c, ALL_START, ALL_END, exit_cfg)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        sigs = []
        if c.sig_A: sigs.append('A')
        if c.sig_B: sigs.append('B')
        if c.sig_C: sigs.append('C')
        if c.sig_D: sigs.append('D')
        print(f"\n  [{c.name}] signals: {'+'.join(sigs)}")
        print(f"    CAGR {cagr:+.2f}%  MDD {mdd:+.2f}%  Final {final/1e6:.0f}M  "
              f"C/M {cagr/abs(mdd) if mdd != 0 else 0:.2f}")
        if ts:
            print(f"    Trades {ts['n']}, win {ts['win']:.0f}%, mean {ts['mean']:+.2f}%, "
                  f"avg_hold {ts['avg_hold']:.0f}d")
            print(f"    +50%:{ts['gt50']}  +100%:{ts['gt100']}  +200%:{ts['gt200']}  "
                  f"best {ts['best']:+.0f}%  worst {ts['worst']:+.0f}%")
        # Signal contribution breakdown
        if len(tr) > 0:
            sigs_used = tr['signal'].value_counts() if 'signal' in tr.columns else None
            if sigs_used is not None:
                print(f"    Signal split: {dict(sigs_used.head(8))}")
        results.append({'cfg': c, 'eq': eq, 'tr': tr,
                        'cagr': cagr, 'mdd': mdd,
                        'gt100': ts['gt100'] if ts else 0,
                        'gt50':  ts['gt50']  if ts else 0,
                        'best':  ts['best']  if ts else 0,
                        'mean':  ts['mean']  if ts else 0,
                        'n':     ts['n']     if ts else 0})

    print("\n" + "="*78)
    print("[Summary] Rocket capture comparison")
    print("="*78)
    print(f"  {'config':14s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} "
          f"{'+50%':>4s} {'+100%':>5s} {'best':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"  {r['cfg'].name:14s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt50']:>4d} {r['gt100']:>5d} {r['best']:>+5.0f}% "
              f"{r['n']:>3d}")

    qualified = [r for r in results if r['cagr'] >= 50]
    if qualified:
        best = max(qualified, key=lambda r: r['gt100'] * 1000 + r['cagr'])
        print(f"\n  → 자율 선택: {best['cfg'].name} (max +100% rocket × CAGR)")
    else:
        best = max(results, key=lambda r: r['cagr'])
        print(f"\n  → fallback: {best['cfg'].name}")

    print(f"\n  [Top 15 trades by max gain] — {best['cfg'].name}")
    sells = best['tr'][best['tr']['side']=='SELL']
    if len(sells) > 0:
        top = sells.sort_values('max_gain_pct', ascending=False).head(15).copy()
        top['name'] = top['ticker'].astype(str).map(name_map)
        for _, t in top.iterrows():
            d = pd.Timestamp(t['date']).date()
            sig = t.get('signal', '?')
            print(f"    {str(d):>11s} {str(t['ticker']):>7s} {str(t['name'] or '')[:18]:<18s} "
                  f"{int(t['hold_days']):>3d}d [{sig:>5s}] {str(t['reason']):>14s} "
                  f"max {t['max_gain_pct']:>+6.0f}% → exit {t['pnl_pct']:>+6.0f}%")

    best['eq'].to_csv(OUT_DIR / 'rocket_v9_best_equity.csv')
    best['tr'].to_csv(OUT_DIR / 'rocket_v9_best_trades.csv', index=False)
    print(f"\n[save] rocket_v9_best_*.csv")


if __name__ == '__main__':
    main()
