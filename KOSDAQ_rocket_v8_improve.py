# -*- coding: utf-8 -*-
"""
RocketHunter v8 — CAGR↑ MDD↓ 개선 (V7D base + 6 가설 ablation)

V7D_all baseline: CAGR +55.6%, MDD -38.5%, give-back 20.9pp

6 가설:
  H1: Time-based early exit — 진입 후 10일 내 max_close < entry+5% 면 컷
       (138 -27% 같이 한번도 못 올라간 trades 차단)
  H2: Tighter HARDSTOP — -10% → -7%
  H3: Concentration — max positions 5 → 3 (winner 집중)
  H4: Volume confirmation — 1.5x → 2.0x VolAvg50 (강한 신호만)
  H5: Pyramid entry — +20% 도달 시 동일 사이즈 50% 추가매수 (winning add)
  H6: MA200 distance gate — 진입 시 close/MA200 ≤ 1.30 (overextended 거부)

Ablation: V7D_base + 각 H 개별/조합
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pandas as pd

CACHE_DIR = Path('/Users/yonghyuk/newcodex/kosdaq_cache')
INVESTOR_DIR = Path('/Users/yonghyuk/newcodex/kosdaq_investor_cache')
OUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
UNIVERSE_CSV = CACHE_DIR / 'universe.csv'

ALL_START = pd.Timestamp('2021-01-04')
ALL_END   = pd.Timestamp('2025-12-31')

INIT_CAPITAL = 100_000_000
FEE_RATE = 0.0015
MAX_HOLD_DAYS = 252


class Cfg(NamedTuple):
    name: str
    # v7 base features (모두 True = V7D_all)
    use_peak_stall: bool
    use_fast_ma: bool
    use_parabolic: bool
    # v8 new hypotheses
    use_time_exit: bool       # H1
    hardstop_pct: float       # H2 (0.10 or 0.07)
    max_positions: int        # H3 (5 or 3)
    vol_mult: float           # H4 (1.5 or 2.0)
    use_pyramid: bool         # H5
    ma200_gate: float         # H6 (None or 1.30)


# All configs share V7D base (stall + fast_ma + parabolic)
def cfg(name, time_exit=False, hardstop=0.10, max_pos=5, vol=1.5,
        pyramid=False, ma200_gate=999.0):
    return Cfg(name, True, True, True,
               time_exit, hardstop, max_pos, vol, pyramid, ma200_gate)


CONFIGS = [
    cfg('V7D_base'),                                    # baseline
    cfg('V8H1_time',  time_exit=True),                  # H1 only
    cfg('V8H2_stop7', hardstop=0.07),                   # H2 only
    cfg('V8H3_conc3', max_pos=3),                       # H3 only
    cfg('V8H4_vol2',  vol=2.0),                         # H4 only
    cfg('V8H5_pyr',   pyramid=True),                    # H5 only
    cfg('V8H6_gate',  ma200_gate=1.30),                 # H6 only
    cfg('V8_MDD',     time_exit=True, hardstop=0.07,
                      vol=2.0, ma200_gate=1.30),        # H1+H2+H4+H6
    cfg('V8_CAGR',    max_pos=3, pyramid=True),         # H3+H5
    cfg('V8_all',     time_exit=True, hardstop=0.07, max_pos=3,
                      vol=2.0, pyramid=True, ma200_gate=1.30),  # all
]


def load_universe_data(udf):
    data = {}
    for _, row in udf.iterrows():
        cache = CACHE_DIR / f'{row.ticker}.csv'
        if cache.exists():
            try:
                df = pd.read_csv(cache, index_col=0, parse_dates=[0])
                if len(df) >= 250:
                    data[row.ticker] = df
            except Exception:
                continue
    return data


def load_investor_data():
    data = {}
    for cache in INVESTOR_DIR.glob('*.csv'):
        try:
            df = pd.read_csv(cache, index_col=0, parse_dates=[0])
            if len(df) >= 30:
                data[cache.stem] = df.sort_index()
        except Exception:
            continue
    return data


def compute_indicators(df):
    out = df.copy()
    out['MA5'] = df['Close'].rolling(5).mean()
    out['MA10'] = df['Close'].rolling(10).mean()
    out['MA20'] = df['Close'].rolling(20).mean()
    out['MA50'] = df['Close'].rolling(50).mean()
    out['MA60'] = df['Close'].rolling(60).mean()
    out['MA60_slope'] = out['MA60'] - out['MA60'].shift(20)
    out['MA200'] = df['Close'].rolling(200).mean()
    out['High52w'] = df['High'].rolling(252).max()
    out['High5'] = df['High'].rolling(5).max()
    out['VolAvg50'] = df['Volume'].rolling(50).mean()
    out['VolAvg10'] = df['Volume'].rolling(10).mean()
    out['Ret_252d'] = df['Close'].pct_change(252)
    out['Ret_5d'] = df['Close'].pct_change(5)
    prev = df['Close'].shift(1)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - prev).abs(),
        (df['Low']  - prev).abs(),
    ], axis=1).max(axis=1)
    out['ATR10'] = tr.ewm(alpha=1/10, adjust=False).mean()
    out['ATR50'] = tr.ewm(alpha=1/50, adjust=False).mean()
    return out


def screen_at(date, data_ind, investor_data, cfg):
    cands = []
    for ticker, df in data_ind.items():
        if date not in df.index: continue
        row = df.loc[date]
        if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                          'VolAvg10','ATR10','ATR50','Ret_252d','MA200']):
            continue
        if row['MA60'] <= 0 or row['High52w'] <= 0 or row['ATR50'] <= 0: continue
        if row['VolAvg50'] <= 0 or row['MA200'] <= 0: continue
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
        # H4: volume threshold
        if not (row['Volume'] > cfg.vol_mult * row['VolAvg50']): continue
        # H6: MA200 distance gate
        if (row['Close'] / row['MA200']) > cfg.ma200_gate: continue
        inv = investor_data.get(ticker)
        if inv is None: continue
        pre = inv[inv.index <= date]
        if len(pre) < 20: continue
        if pre['Foreign_Net'].tail(20).sum() <= 0: continue
        cands.append({'ticker': ticker, 'close': row['Close']})
    return cands


def exit_check_v8(df, df_ind, idx, h, days_since_peak, days_held, cfg):
    yc = float(df['Close'].iloc[idx - 1])
    if pd.isna(yc): return None
    entry_px = h['entry_px']
    max_close = h['max_close']

    # H2: tighter hardstop (early)
    if days_held < 30 and yc < entry_px * (1 - cfg.hardstop_pct):
        return 'HARDSTOP'

    # H1: time-based early exit — 10일 내 +5% 못 가면 컷
    if cfg.use_time_exit and days_held >= 10:
        if max_close < entry_px * 1.05:
            return 'TIME_NO_PROG'

    max_gain = (max_close / entry_px - 1) * 100

    # Peak-stall escalation
    if cfg.use_peak_stall and max_gain >= 30:
        if days_since_peak >= 20:
            if yc < max_close * 0.90:
                return 'STALL20_T10'
            ma20_y = df_ind['MA20'].iloc[idx-1]
            if pd.notna(ma20_y) and yc < ma20_y:
                return 'STALL20_MA20'
        elif days_since_peak >= 10:
            if yc < max_close * 0.85:
                return 'STALL10_T15'
        elif days_since_peak >= 5:
            if yc < max_close * 0.75:
                return 'STALL5_T25'

    # Fast MA
    if cfg.use_fast_ma:
        if max_gain >= 100:
            ma10_y = df_ind['MA10'].iloc[idx-1]
            if pd.notna(ma10_y) and yc < ma10_y: return 'FAST_MA10'
        elif max_gain >= 50:
            ma20_y = df_ind['MA20'].iloc[idx-1]
            if pd.notna(ma20_y) and yc < ma20_y: return 'FAST_MA20'

    # Parabolic
    if cfg.use_parabolic and max_gain >= 30:
        ret_5d_y = df_ind['Ret_5d'].iloc[idx-1]
        if pd.notna(ret_5d_y) and ret_5d_y > 0.30:
            y_open = float(df['Open'].iloc[idx-1])
            if pd.notna(y_open) and yc < y_open:
                return 'PARABOLIC'

    # v4 trail
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


def portfolio_simulate(data, data_ind, scan_dates, investor_data, cfg, sim_s, sim_e):
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

        # H5: pyramid entry — open trigger 처리 (잔여 cash 가 충분할 때)
        if cfg.use_pyramid:
            for t, h in list(holdings.items()):
                if h.get('pyramid_done'): continue
                if date not in data[t].index: continue
                try:
                    idx = data[t].index.get_loc(date)
                except KeyError:
                    continue
                if idx == 0: continue
                yc = float(data[t]['Close'].iloc[idx-1])
                if pd.isna(yc): continue
                if yc >= h['entry_px'] * 1.20:
                    # 추가 사이즈: 진입 비용의 50% (cash 부족 시 가능한 만큼)
                    target_add = h['initial_cost'] * 0.50
                    if cash < target_add * 0.30: continue
                    add = min(target_add, cash * 0.5)
                    px = float(data[t]['Open'].loc[date])
                    if pd.isna(px) or px <= 0: continue
                    qty_add = int(add / (px * (1 + FEE_RATE)))
                    if qty_add <= 0: continue
                    cost = qty_add * px * (1 + FEE_RATE)
                    if cost > cash: continue
                    cash -= cost
                    # blended entry_px
                    total_qty = h['qty'] + qty_add
                    h['entry_px'] = (h['entry_px'] * h['qty'] + px * qty_add) / total_qty
                    h['qty'] = total_qty
                    h['pyramid_done'] = True

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
                                    days_since_peak, days_held, cfg)
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
            })
            del holdings[t]

        # Entry on Monday after Friday scan
        prev_idx = list(all_dates).index(date) - 1 if date in all_dates else None
        if prev_idx is not None and prev_idx >= 0:
            prev_date = all_dates[prev_idx]
            if prev_date in scan_set:
                cands = screen_at(prev_date, data_ind, investor_data, cfg)
                cands = [c for c in cands if c['ticker'] not in holdings]
                slots = cfg.max_positions - len(holdings)
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
                                       'pyramid_done': False}

        hv = 0.0
        for t, h in holdings.items():
            if date in data[t].index:
                cl = float(data[t]['Close'].loc[date])
                hv += h['qty'] * (cl if pd.notna(cl) else h['entry_px'])
            else:
                hv += h['qty'] * h['entry_px']
        eq_rows.append({'Date': date, 'Total_Money': cash + hv, 'NumHold': len(holdings)})

    return pd.DataFrame(eq_rows).set_index('Date'), pd.DataFrame(trade_rows)


def stats(eq, init_cap):
    final = float(eq['Total_Money'].iloc[-1])
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = ((final/init_cap)**(1/years) - 1) * 100 if years > 0 else 0
    cm = eq['Total_Money'].cummax()
    mdd = float(((eq['Total_Money']/cm) - 1).min() * 100)
    return cagr, mdd, final


def trade_stats(tr):
    sells = tr[tr['side']=='SELL']
    if len(sells) == 0: return None
    pnl = sells['pnl_pct']
    sells_pos = sells[sells['max_gain_pct'] > 0].copy()
    if len(sells_pos) > 0:
        sells_pos['giveback'] = sells_pos['max_gain_pct'] - sells_pos['pnl_pct']
        avg_giveback_pp = sells_pos['giveback'].mean()
    else:
        avg_giveback_pp = 0
    return {
        'n': len(sells), 'mean': pnl.mean(), 'win': (pnl>0).mean()*100,
        'gt50': int((pnl>50).sum()), 'gt100': int((pnl>100).sum()),
        'gt200': int((pnl>200).sum()),
        'best': pnl.max(), 'worst': pnl.min(),
        'avg_hold': sells['hold_days'].mean(),
        'avg_giveback_pp': avg_giveback_pp,
    }


def main():
    print("="*78)
    print("RocketHunter v8 — CAGR↑ MDD↓ 개선 ablation")
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

    print("="*78)
    print("[Sweep] 10 configs — V7D base + 6 hypotheses (single + combo)")
    print("="*78)
    results = []
    for c in CONFIGS:
        eq, tr = portfolio_simulate(data, data_ind, all_scan, investor_data,
                                    c, ALL_START, ALL_END)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        flags = []
        if c.use_time_exit: flags.append('time')
        if c.hardstop_pct < 0.10: flags.append(f'stop{int(c.hardstop_pct*100)}')
        if c.max_positions != 5: flags.append(f'pos{c.max_positions}')
        if c.vol_mult != 1.5: flags.append(f'vol{c.vol_mult:.1f}')
        if c.use_pyramid: flags.append('pyr')
        if c.ma200_gate < 999: flags.append(f'gate{c.ma200_gate:.2f}')
        print(f"\n  [{c.name}] {','.join(flags) or 'base'}")
        print(f"    CAGR {cagr:+.2f}%  MDD {mdd:+.2f}%  Final {final/1e6:.0f}M  "
              f"C/M {cagr/abs(mdd) if mdd != 0 else 0:.2f}")
        if ts:
            print(f"    Trades {ts['n']}, win {ts['win']:.0f}%, mean {ts['mean']:+.2f}%, "
                  f"avg_hold {ts['avg_hold']:.0f}d")
            print(f"    +50%:{ts['gt50']}  +100%:{ts['gt100']}  +200%:{ts['gt200']}  "
                  f"best {ts['best']:+.0f}%  worst {ts['worst']:+.0f}%")
            print(f"    Give-back: {ts['avg_giveback_pp']:.1f}pp")
        results.append({'cfg': c, 'eq': eq, 'tr': tr,
                        'cagr': cagr, 'mdd': mdd,
                        'gt100': ts['gt100'] if ts else 0,
                        'best': ts['best'] if ts else 0,
                        'worst': ts['worst'] if ts else 0,
                        'giveback_pp': ts['avg_giveback_pp'] if ts else 0,
                        'mean': ts['mean'] if ts else 0,
                        'win': ts['win'] if ts else 0,
                        'n': ts['n'] if ts else 0})

    # Summary table
    print("\n" + "="*78)
    print("[Summary] V7D base 대비 효과")
    print("="*78)
    print(f"  {'config':14s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} "
          f"{'+100%':>5s} {'mean':>7s} {'worst':>7s} {'gv':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"  {r['cfg'].name:14s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt100']:>5d} {r['mean']:>+6.1f}% "
              f"{r['worst']:>+6.1f}% {r['giveback_pp']:>5.1f}pp {r['n']:>3d}")

    # Selection: CAGR ≥ 50% + +100% ≥ 1, best C/M
    qualified = [r for r in results if r['cagr'] >= 50 and r['gt100'] >= 1]
    if qualified:
        best = max(qualified, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → 자율 선택: {best['cfg'].name} (best C/M among qualified)")
    else:
        best = max(results, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → fallback: {best['cfg'].name} (best C/M)")

    print(f"\n  [Top 15 trades by max gain] — {best['cfg'].name}")
    sells = best['tr'][best['tr']['side']=='SELL']
    if len(sells) > 0:
        top = sells.sort_values('max_gain_pct', ascending=False).head(15).copy()
        top['name'] = top['ticker'].astype(str).map(name_map)
        for _, t in top.iterrows():
            d = pd.Timestamp(t['date']).date()
            print(f"    {str(d):>11s} {str(t['ticker']):>7s} {str(t['name'] or '')[:18]:<18s} "
                  f"{int(t['hold_days']):>3d}d {str(t['reason']):>14s} "
                  f"max {t['max_gain_pct']:>+6.0f}% → exit {t['pnl_pct']:>+6.0f}%")

    best['eq'].to_csv(OUT_DIR / 'rocket_v8_best_equity.csv')
    best['tr'].to_csv(OUT_DIR / 'rocket_v8_best_trades.csv', index=False)
    print(f"\n[save] rocket_v8_best_*.csv")


if __name__ == '__main__':
    main()
