# -*- coding: utf-8 -*-
"""V32A — vol 1.9 vs V_FINAL full-period 검증.

V31 walk-forward 에서 모든 fold 에서 vol 1.9 가 winner.
Fold 3 OOS test: vol 1.9 = +97.8% vs V_FINAL +66.7% (Δ +31pp).

이번 검증:
1. Full period 비교
2. 연도별 stability
3. Trade quality distribution (max_gain, hold_days)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, INIT_CAPITAL, ALL_START, ALL_END,
)
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v23_entry_quality import simulate_v23
from KOSDAQ_rocket_v25_extra import V25Cfg, V23CfgWrap
import KOSDAQ_rocket_v9_ensemble as v9


def make_screen_with_ma(vm_local, md_local, investor_data):
    from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
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
            if not (row['Volume'] > vm_local * row['VolAvg50']): continue
            if (row['Close'] / row['MA200']) > md_local: continue
            if not has_foreign_buy(investor_data, ticker, date, 20): continue
            cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


def run_one(data, data_ind, investor_data, check_market, sim_s, sim_e, vm, md):
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    all_scan = all_dates[(all_dates >= sim_s) & (all_dates <= sim_e)]
    all_scan = all_scan[all_scan.weekday == 4]
    vc = V25Cfg(name=f'vol{vm}_ma{md}', ma200_max_dist=md,
                early_be_days=0, early_be_thresh=0.0,
                foreign_5d_min_days=0, atr_close_max=0.0,
                turn_min=0.0, par=0.12, lowvol_th=0.07, max_pos=6)
    vc_wrap = V23CfgWrap(vc)
    class D:
        sig_A = True; sig_B = False; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)
    v9.screen_v9 = make_screen_with_ma(vm, md, investor_data)
    eq, tr = simulate_v23(data, data_ind, all_scan, investor_data, cfg,
                            sim_s, sim_e, exit_cfg, ec, 6, check_market, vc_wrap)
    cagr, mdd, final = stats(eq, INIT_CAPITAL)
    ts = trade_stats(tr)
    return {'cagr': cagr, 'mdd': mdd, 'final': final,
            'n': ts['n'] if ts else 0, 'win': ts['win'] if ts else 0,
            'gt100': ts['gt100'] if ts else 0, 'gt200': ts['gt200'] if ts else 0,
            'mean': ts['mean'] if ts else 0,
            'u100': unique_100pct_count(tr), 'eq': eq, 'tr': tr}


def year_breakdown(eq, init_cap=INIT_CAPITAL):
    """연도별 return / MDD."""
    # eq is a Series with date index
    if hasattr(eq, 'columns'):
        eq = eq.iloc[:, 0]
    eq = eq.copy()
    eq.index = pd.to_datetime(eq.index)
    yearly = {}
    for y in sorted(eq.index.year.unique()):
        g = eq[eq.index.year == y]
        if len(g) < 2: continue
        v_start = float(g.iloc[0])
        v_end = float(g.iloc[-1])
        ret = (v_end / v_start - 1) * 100
        peak = g.cummax()
        dd = (g - peak) / peak * 100
        mdd = float(dd.min())
        yearly[int(y)] = {'ret': ret, 'mdd': mdd}
    return yearly


def main():
    print("="*78)
    print("V32A — vol 1.9 vs V_FINAL 검증")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators] computing...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)

    configs = [
        ('V_FINAL', 2.0, 1.45),
        ('vol1.9_ma1.40', 1.9, 1.40),
        ('vol1.9_ma1.45', 1.9, 1.45),
        ('vol1.9_ma1.50', 1.9, 1.50),
    ]

    print(f"\n[Full period {ALL_START.date()} ~ {ALL_END.date()}]")
    results = {}
    for name, vm, md in configs:
        r = run_one(data, data_ind, investor_data, check, ALL_START, ALL_END, vm, md)
        results[name] = r
        cm = r['cagr'] / abs(r['mdd']) if r['mdd'] != 0 else 0
        print(f"\n  [{name}] vol={vm} ma={md}")
        print(f"    CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% C/M {cm:.2f} Final {r['final']/1e6:.0f}M")
        print(f"    Trades n={r['n']} win={r['win']:.0f}% mean={r['mean']:+.1f}%")
        print(f"    +100%:{r['gt100']} +200%:{r['gt200']} unique100:{r['u100']}")

    # Year breakdown
    print(f"\n{'='*78}")
    print("[Year-by-year breakdown]")
    print('='*78)
    print(f"\n{'config':<18s} {'2021':>10s} {'2022':>10s} {'2023':>10s} {'2024':>10s} {'2025':>10s} {'2026YTD':>10s}")
    for name in [c[0] for c in configs]:
        yb = year_breakdown(results[name]['eq'])
        row = f"{name:<18s}"
        for y in [2021, 2022, 2023, 2024, 2025, 2026]:
            if y in yb:
                row += f"  {yb[y]['ret']:>+8.1f}%"
            else:
                row += f"  {'-':>9s}"
        print(row)

    # Year-by-year MDD
    print(f"\n{'config':<18s} 연도별 MDD")
    for name in [c[0] for c in configs]:
        yb = year_breakdown(results[name]['eq'])
        row = f"{name:<18s}"
        for y in [2021, 2022, 2023, 2024, 2025, 2026]:
            if y in yb:
                row += f"  {yb[y]['mdd']:>+8.1f}%"
            else:
                row += f"  {'-':>9s}"
        print(row)

    # Worst quarter / month for V_FINAL vs vol 1.9
    print(f"\n{'='*78}")
    print("[Worst months — V_FINAL vs vol 1.9 ma 1.45]")
    print('='*78)
    for name in ['V_FINAL', 'vol1.9_ma1.45']:
        eq = results[name]['eq'].copy()
        eq.index = pd.to_datetime(eq.index)
        monthly = eq.resample('ME').last().pct_change() * 100
        worst = monthly.nsmallest(5)
        best = monthly.nlargest(5)
        print(f"\n  [{name}] worst 5 months:")
        for d, v in worst.items():
            print(f"    {d.strftime('%Y-%m')}: {v:+.1f}%")
        print(f"  [{name}] best 5 months:")
        for d, v in best.items():
            print(f"    {d.strftime('%Y-%m')}: {v:+.1f}%")

    # Trade quality
    print(f"\n{'='*78}")
    print("[Trade quality distribution]")
    print('='*78)
    for name in [c[0] for c in configs]:
        tr = results[name]['tr']
        sells = tr[tr['side'] == 'SELL']
        if len(sells) == 0: continue
        print(f"\n  [{name}] n={len(sells)}")
        print(f"    max_gain median: {sells['max_gain_pct'].median():+.1f}%")
        print(f"    max_gain mean:   {sells['max_gain_pct'].mean():+.1f}%")
        print(f"    pnl median:      {sells['pnl_pct'].median():+.1f}%")
        print(f"    pnl mean:        {sells['pnl_pct'].mean():+.1f}%")
        print(f"    hold_days median:{sells['hold_days'].median():.0f}d")
        print(f"    win rate:        {(sells['pnl_pct']>0).sum()/len(sells)*100:.0f}%")
        print(f"    +50% trades:     {(sells['pnl_pct']>=50).sum()}")
        print(f"    +100% trades:    {(sells['pnl_pct']>=100).sum()}")
        print(f"    +200% trades:    {(sells['pnl_pct']>=200).sum()}")

    # Final verdict
    print(f"\n{'='*78}")
    print("[Verdict]")
    print('='*78)
    v_final = results['V_FINAL']
    vol19 = results['vol1.9_ma1.45']
    delta = vol19['cagr'] - v_final['cagr']
    print(f"  vol 1.9 ma 1.45 vs V_FINAL: CAGR Δ {delta:+.1f}pp")
    print(f"  vol 1.9 MDD: {vol19['mdd']:+.1f}% vs V_FINAL: {v_final['mdd']:+.1f}%")
    print(f"  vol 1.9 trades: {vol19['n']} vs V_FINAL: {v_final['n']}")

    # Save trades
    out = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
    vol19['tr'].to_csv(out / 'rocket_v32a_vol19_trades.csv', index=False)
    vol19['eq'].to_csv(out / 'rocket_v32a_vol19_equity.csv')
    print(f"\n[save] rocket_v32a_vol19_*.csv")


if __name__ == '__main__':
    main()
