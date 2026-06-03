# -*- coding: utf-8 -*-
"""
RocketHunter v9b — Signal B (newhigh pivot) quality 강화.

V9_AB 발견: B 가 +100% rocket 3건 capture (V8H4 의 3배) 했으나 win rate ↓.
v9b: B 의 quality filter 강화 → false positive 줄이면서 rocket 유지.

V9_AB base (Signal A + B):
  - A: V8H4_vol2 (그대로)
  - B (strict 변형 4가지):
    * B0_loose: V9 baseline (vol 1.5x, 외인 5d)
    * B1_vol2:  vol 2.0x (V8H4 일관성)
    * B2_for20: 외인 20d > 0
    * B3_atr:   ATR contraction (10/50 < 1.20)
    * B4_full:  vol 2.0x + 외인 20d + ATR (all strict)
    * B5_tight: 52w high 2% 이내 (5% → 2%, 더 strict)
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
from KOSDAQ_rocket_v9_ensemble import (
    signal_A_v8h4, has_foreign_buy, portfolio_simulate_v9,
)


class BCfg(NamedTuple):
    name: str
    vol_mult: float        # default 1.5
    foreign_days: int      # default 5
    use_atr: bool          # default False
    dist_thresh: float     # default 0.05


B_CONFIGS = [
    BCfg('B0_loose',   1.5,  5, False, 0.05),
    BCfg('B1_vol2',    2.0,  5, False, 0.05),
    BCfg('B2_for20',   1.5, 20, False, 0.05),
    BCfg('B3_atr',     1.5,  5, True,  0.05),
    BCfg('B4_full',    2.0, 20, True,  0.05),
    BCfg('B5_tight',   2.0, 20, True,  0.02),
]


def make_signal_B(bcfg):
    def signal_B(df, df_ind, date):
        row = df_ind.loc[date]
        if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                          'MA200','Ret_252d','ATR10','ATR50']):
            return False
        if not (row['Close'] > row['MA60']): return False
        if not (row['Close'] > row['MA200']): return False
        if not (row['MA60_slope'] > 0): return False
        if row['Ret_252d'] < 0.30: return False
        if row['Ret_252d'] > 5.00: return False
        dist = (row['High52w'] - row['Close']) / row['High52w']
        if dist > bcfg.dist_thresh: return False
        if not (row['Volume'] > bcfg.vol_mult * row['VolAvg50']): return False
        if bcfg.use_atr:
            if (row['ATR10'] / row['ATR50']) > 1.20: return False
        return True
    return signal_B


# Custom screener with parameterized B
def make_screen_v9b(bcfg):
    sig_B_fn = make_signal_B(bcfg)
    def screen(date, data_ind, data, investor_data, dummy_cfg):
        cands = []
        for ticker, df in data.items():
            df_ind = data_ind[ticker]
            if date not in df_ind.index: continue
            row = df_ind.loc[date]
            if pd.isna(row['Close']): continue

            signals = []
            # Signal A (V8H4)
            if signal_A_v8h4(df, df_ind, date):
                if has_foreign_buy(investor_data, ticker, date, 20):
                    signals.append('A')
            # Signal B (parameterized)
            if sig_B_fn(df, df_ind, date):
                if has_foreign_buy(investor_data, ticker, date, bcfg.foreign_days):
                    signals.append('B')

            if signals:
                cands.append({'ticker': ticker, 'close': row['Close'],
                              'signals': ','.join(signals)})
        return cands
    return screen


def run_with_B(bcfg, data, data_ind, all_scan, investor_data, exit_cfg):
    # Monkey-patch screen_v9 in portfolio_simulate_v9
    import KOSDAQ_rocket_v9_ensemble as v9
    original = v9.screen_v9
    v9.screen_v9 = make_screen_v9b(bcfg)
    class DummyCfg:
        sig_A = True; sig_B = True; sig_C = False; sig_D = False
    eq, tr = portfolio_simulate_v9(data, data_ind, all_scan, investor_data,
                                    DummyCfg(), ALL_START, ALL_END, exit_cfg)
    v9.screen_v9 = original
    return eq, tr


def main():
    print("="*78)
    print("RocketHunter v9b — Signal B quality 강화 ablation")
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

    exit_cfg = v8_cfg('exit', vol=2.0)

    print("="*78)
    print("[Sweep] B variants — A 는 동일 V8H4, B 만 변형")
    print("="*78)
    results = []
    for bcfg in B_CONFIGS:
        eq, tr = run_with_B(bcfg, data, data_ind, all_scan, investor_data, exit_cfg)
        cagr, mdd, final = stats(eq, INIT_CAPITAL)
        ts = trade_stats(tr)
        print(f"\n  [{bcfg.name}] vol={bcfg.vol_mult} for{bcfg.foreign_days}d "
              f"atr={bcfg.use_atr} dist={bcfg.dist_thresh}")
        print(f"    CAGR {cagr:+.2f}%  MDD {mdd:+.2f}%  Final {final/1e6:.0f}M  "
              f"C/M {cagr/abs(mdd) if mdd != 0 else 0:.2f}")
        if ts:
            print(f"    Trades {ts['n']}, win {ts['win']:.0f}%, mean {ts['mean']:+.2f}%, "
                  f"avg_hold {ts['avg_hold']:.0f}d")
            print(f"    +50%:{ts['gt50']}  +100%:{ts['gt100']}  +200%:{ts['gt200']}  "
                  f"best {ts['best']:+.0f}%")
        if len(tr) > 0 and 'signal' in tr.columns:
            sigs = tr['signal'].value_counts()
            print(f"    Signal split: {dict(sigs.head(6))}")
        results.append({'cfg': bcfg, 'eq': eq, 'tr': tr,
                        'cagr': cagr, 'mdd': mdd,
                        'gt100': ts['gt100'] if ts else 0,
                        'gt50':  ts['gt50']  if ts else 0,
                        'best':  ts['best']  if ts else 0,
                        'mean':  ts['mean']  if ts else 0,
                        'n':     ts['n']     if ts else 0,
                        'win':   ts['win']   if ts else 0})

    print("\n" + "="*78)
    print("[Summary] B quality 강화 효과")
    print("="*78)
    print(f"  {'config':12s} {'CAGR':>7s} {'MDD':>7s} {'C/M':>5s} "
          f"{'+50%':>4s} {'+100%':>5s} {'win':>4s} {'mean':>6s} {'n':>3s}")
    for r in results:
        cm = r['cagr']/abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"  {r['cfg'].name:12s} {r['cagr']:>+6.1f}% {r['mdd']:>+6.1f}% "
              f"{cm:>5.2f} {r['gt50']:>4d} {r['gt100']:>5d} "
              f"{r['win']:>3.0f}% {r['mean']:>+5.1f}% {r['n']:>3d}")

    # 자율 선택: +100% ≥ 2 + CAGR ≥ 30 + best C/M
    qualified = [r for r in results if r['gt100'] >= 2 and r['cagr'] >= 30]
    if qualified:
        best = max(qualified, key=lambda r: r['cagr']/abs(r['mdd']))
        print(f"\n  → 자율 선택: {best['cfg'].name} (+100% ≥ 2, best C/M)")
    else:
        best = max(results, key=lambda r: r['gt100'] * 1000 + r['cagr'])
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
                  f"{int(t['hold_days']):>3d}d [{sig:>3s}] {str(t['reason']):>14s} "
                  f"max {t['max_gain_pct']:>+6.0f}% → exit {t['pnl_pct']:>+6.0f}%")

    best['eq'].to_csv(OUT_DIR / 'rocket_v9b_best_equity.csv')
    best['tr'].to_csv(OUT_DIR / 'rocket_v9b_best_trades.csv', index=False)
    print(f"\n[save] rocket_v9b_best_*.csv")


if __name__ == '__main__':
    main()
