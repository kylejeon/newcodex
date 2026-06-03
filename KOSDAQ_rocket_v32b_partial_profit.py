# -*- coding: utf-8 -*-
"""V32B — Partial Profit Taking 실험.

V_FINAL 의 mega-rocket 의존성 확인됨 (2024 +711% 가 +200% 종목 1-2개에 의존).
가설: partial profit taking 으로 일부 수익 lock-in + 잔여로 rocket 추적.

Variants:
  - V32B_PT50  : pnl ≥ 50% 도달 시 50% 매도, 잔여 50% 는 기존 exit 룰
  - V32B_PT100 : pnl ≥ 100% 도달 시 50% 매도, 잔여 50% 는 기존 exit 룰
  - V32B_PT_split: pnl 50% 1/3, pnl 100% 1/3, 잔여 1/3
  - V32B_PT50_trail: 50% 매도 후 잔여는 25% trailing stop (tight)
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
    UNIVERSE_CSV, INIT_CAPITAL, FEE_RATE, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v23_entry_quality import exit_check_v23
from KOSDAQ_rocket_v25_extra import V25Cfg, V23CfgWrap
import KOSDAQ_rocket_v9_ensemble as v9


class PTCfg(NamedTuple):
    name: str
    pt_levels: tuple  # ((pnl_threshold, frac_to_sell), ...) e.g. ((0.50, 0.5),)
    post_pt_trail: float  # 0=no trail, 0.25=25% trail from max after partial


def make_screen_vfinal(investor_data):
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
            if not (row['Volume'] > 2.0 * row['VolAvg50']): continue
            if (row['Close'] / row['MA200']) > 1.45: continue
            if not has_foreign_buy(investor_data, ticker, date, 20): continue
            cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


def check_partial_profit(h, current_close, pt_cfg):
    """잔여 holding 중 partial profit 매도 수량 계산."""
    if not pt_cfg.pt_levels:
        return 0, None  # no partial
    current_pnl = (current_close / h['entry_px'] - 1)
    for i, (threshold, frac) in enumerate(pt_cfg.pt_levels):
        flag_key = f'pt_done_{i}'
        if h.get(flag_key, False):
            continue
        if current_pnl >= threshold:
            # Sell `frac` of CURRENT qty
            sell_qty = int(h['qty'] * frac)
            if sell_qty <= 0:
                continue
            return sell_qty, flag_key
    return 0, None


def check_trail_after_pt(h, current_close, pt_cfg):
    """Partial profit 후 trail stop 체크."""
    if pt_cfg.post_pt_trail <= 0:
        return False
    # Only activate trail after any pt done
    if not any(h.get(f'pt_done_{i}', False) for i in range(len(pt_cfg.pt_levels))):
        return False
    max_close = h.get('max_close', current_close)
    if max_close <= 0:
        return False
    drawdown = (max_close - current_close) / max_close
    return drawdown >= pt_cfg.post_pt_trail


def simulate_v32b(data, data_ind, scan_dates, investor_data, sim_s, sim_e,
                   exit_cfg, ec, max_pos, market_check, vc, pt_cfg):
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

        # Partial profit check (BEFORE full exit check)
        partial_sells = []
        for t, h in holdings.items():
            df = data[t]
            if date not in df.index: continue
            cl = float(df['Close'].loc[date])
            if pd.isna(cl) or cl <= 0: continue
            sell_qty, flag_key = check_partial_profit(h, cl, pt_cfg)
            if sell_qty > 0 and sell_qty < h['qty']:
                partial_sells.append((t, sell_qty, flag_key))

        for t, sell_qty, flag_key in partial_sells:
            df = data[t]
            # Sell at next day open (same as full exit, for consistency)
            # But check_partial_profit uses current close — sell at open of next day
            # For simplicity, sell at today's close (partial sell is intra-day decision)
            px = float(df['Close'].loc[date])
            if pd.isna(px) or px <= 0: continue
            proceeds = sell_qty * px * (1 - FEE_RATE)
            cash += proceeds
            pnl_pct = (px / holdings[t]['entry_px'] - 1) * 100
            trade_rows.append({
                'date': date, 'ticker': t, 'side': 'SELL', 'reason': flag_key.upper(),
                'pnl_pct': pnl_pct, 'entry_date': holdings[t]['entry_date'],
                'hold_days': (date - holdings[t]['entry_date']).days,
                'entry_px': holdings[t]['entry_px'], 'exit_px': px,
                'max_gain_pct': (holdings[t]['max_close'] / holdings[t]['entry_px'] - 1) * 100,
                'frac': sell_qty / holdings[t]['qty'],
                'signal': holdings[t].get('signal', ''),
            })
            holdings[t]['qty'] -= sell_qty
            holdings[t][flag_key] = True

        # Full exit check
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
            # Trail stop after partial
            yc = float(df['Close'].iloc[idx - 1]) if idx > 0 else None
            if yc is not None and not pd.isna(yc):
                if check_trail_after_pt(h, yc, pt_cfg):
                    to_exit.append((t, 'PT_TRAIL'))
                    continue
            reason = exit_check_v23(df, data_ind[t], idx, h, days_since_peak, days_held,
                                     exit_cfg, ec, vc)
            if reason:
                to_exit.append((t, reason))

        for t, reason in to_exit:
            df = data[t]
            px = float(df['Open'].loc[date])
            if pd.isna(px) or px <= 0: continue
            qty = holdings[t]['qty']
            if qty <= 0:
                del holdings[t]
                continue
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
                'frac': qty / (qty + sum(1 for k in holdings[t] if k.startswith('pt_done_') and holdings[t][k])),
                'signal': holdings[t].get('signal', ''),
            })
            del holdings[t]

        # Entry
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

        # Equity
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
    print("V32B — Partial Profit Taking 실험")
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

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)
    exit_cfg = v8_cfg('exit', vol=2.0)
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)
    vc = V23CfgWrap(V25Cfg(name='V_FINAL', ma200_max_dist=1.45, early_be_days=0,
                            early_be_thresh=0.0, foreign_5d_min_days=0,
                            atr_close_max=0.0, turn_min=0.0,
                            par=0.12, lowvol_th=0.07, max_pos=6))
    v9.screen_v9 = make_screen_vfinal(investor_data)

    variants = [
        PTCfg('V_FINAL_base', (), 0.0),
        PTCfg('PT50_at50', ((0.50, 0.5),), 0.0),
        PTCfg('PT50_at100', ((1.00, 0.5),), 0.0),
        PTCfg('PT_split', ((0.50, 0.33), (1.00, 0.50)), 0.0),  # 33%@+50%, 50% of remaining @+100%
        PTCfg('PT50_at50_trail25', ((0.50, 0.5),), 0.25),
        PTCfg('PT50_at100_trail25', ((1.00, 0.5),), 0.25),
        PTCfg('PT33_at50_then_at100', ((0.50, 0.33), (1.00, 0.33)), 0.0),
    ]

    results = []
    for pt in variants:
        eq, tr = simulate_v32b(data, data_ind, all_scan, investor_data,
                                 ALL_START, ALL_END, exit_cfg, ec, 6, check, vc, pt)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        # Sells only
        sells = tr[tr['side']=='SELL'] if len(tr)>0 else pd.DataFrame()
        n_sells = len(sells)
        n_pt = (sells['reason'].str.startswith('PT_DONE')).sum() if n_sells>0 else 0
        n_trail = (sells['reason']=='PT_TRAIL').sum() if n_sells>0 else 0
        u100 = unique_100pct_count(tr)
        gt100 = ts['gt100'] if ts else 0
        win = ts['win'] if ts else 0
        mean = ts['mean'] if ts else 0
        print(f"\n  [{pt.name}] pt_levels={pt.pt_levels} trail={pt.post_pt_trail}")
        print(f"    CAGR {cagr:+.1f}% MDD {mdd:+.1f}% C/M {cagr/abs(mdd):.2f} Final {final/1e6:.0f}M")
        print(f"    Sells n={n_sells} (PT partial={n_pt}, PT_TRAIL={n_trail})")
        print(f"    win {win:.0f}% mean {mean:+.1f}% +100%:{gt100} u100:{u100}")
        results.append({'name': pt.name, 'cagr': cagr, 'mdd': mdd, 'final': final,
                        'n': n_sells, 'pt_partial': n_pt, 'pt_trail': n_trail,
                        'gt100': gt100, 'win': win, 'mean': mean, 'u100': u100,
                        'eq': eq, 'tr': tr})

    # Summary
    print(f"\n{'='*78}\n[Summary]\n{'='*78}")
    print(f"  {'name':22s} {'CAGR':>8s} {'MDD':>7s} {'C/M':>5s} {'+100%':>5s} "
          f"{'PT':>3s} {'TR':>3s} {'win':>4s} {'n':>4s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0
        print(f"  {r['name']:22s} {r['cagr']:>+7.1f}% {r['mdd']:>+6.1f}% {cm:>5.2f} "
              f"{r['gt100']:>5d} {r['pt_partial']:>3d} {r['pt_trail']:>3d} "
              f"{r['win']:>3.0f}% {r['n']:>4d}")

    # Best
    base = next((r for r in results if r['name']=='V_FINAL_base'), None)
    if base:
        print(f"\n  V_FINAL baseline: CAGR {base['cagr']:+.1f}% MDD {base['mdd']:+.1f}%")
        for r in results:
            if r['name'] == 'V_FINAL_base': continue
            d = r['cagr'] - base['cagr']
            md = r['mdd'] - base['mdd']
            print(f"  {r['name']:22s}: ΔCAGR {d:+.1f}pp ΔMDD {md:+.1f}pp")

    # Save best
    qualified = [r for r in results if r['cagr'] > base['cagr']] if base else []
    if qualified:
        best = max(qualified, key=lambda r: r['cagr']/abs(r['mdd']) if r['mdd']!=0 else 0)
        print(f"\n  → 자율 winner: {best['name']} CAGR {best['cagr']:+.1f}%")
        out = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
        best['eq'].to_csv(out / f'rocket_v32b_{best["name"]}_equity.csv')
        best['tr'].to_csv(out / f'rocket_v32b_{best["name"]}_trades.csv', index=False)
    else:
        print(f"\n  → no variant improves on V_FINAL baseline (partial profit hurts)")


if __name__ == '__main__':
    main()
