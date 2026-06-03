# -*- coding: utf-8 -*-
"""V_FINAL Backfill — 과거 금요일들의 entry signal 재현.

Usage:
  python3 V_FINAL_backfill_signals.py --start 2026-05-01 --end 2026-06-03
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    UNIVERSE_CSV,
)
from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from V_FINAL_signal_bot import signal_A_final, V_FINAL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2026-05-01')
    parser.add_argument('--end', default='2026-06-03')
    args = parser.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    print("="*78)
    print(f"V_FINAL Backfill — {start.date()} ~ {end.date()}")
    print("="*78)

    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
    print("\n[1] Loading data...")
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"  {len(data)} OHLCV, {len(investor_data)} investor cache")

    print("[2] Indicators...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    scan_range = all_dates[(all_dates >= start) & (all_dates <= end)]
    friday_dates = scan_range[scan_range.weekday == 4]
    print(f"\n[3] Friday scan dates: {[d.strftime('%Y-%m-%d') for d in friday_dates]}")

    print("[4] Market filter loading...")
    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, V_FINAL.lowvol_th)

    print("\n" + "="*78)
    print("[Per-Friday signals]")
    print("="*78)

    for fri in friday_dates:
        # Next Monday (entry day)
        next_idx = list(all_dates).index(fri) + 1 if fri in all_dates else None
        next_day = all_dates[next_idx] if next_idx is not None and next_idx < len(all_dates) else None

        print(f"\n📅 Scan: {fri.strftime('%Y-%m-%d')} (Fri) → Entry: "
              f"{next_day.strftime('%Y-%m-%d') if next_day is not None else 'TBD'}")

        market_ok = check(fri)
        if not market_ok:
            print(f"  🔴 KOSDAQ 14d abs return ≥ {V_FINAL.lowvol_th*100:.0f}% → SKIP")
            continue
        print(f"  🟢 Market filter PASS")

        cands = []
        for ticker, df in data.items():
            if fri not in df.index: continue
            df_ind = data_ind[ticker]
            sig = signal_A_final(df, df_ind, fri, V_FINAL, investor_data, ticker)
            if sig:
                sig['name'] = name_map.get(ticker, '?')
                sig['quality_score'] = (
                    sig['ma200_dist']
                    + sig['dist_52w']
                    - sig['vol_surge'] * 0.05
                    + sig['atr_ratio'] * 0.5
                )
                cands.append(sig)

        cands.sort(key=lambda c: c['quality_score'])
        selected = cands[:V_FINAL.max_pos]

        if not selected:
            print(f"  → 진입 신호 없음 (총 후보 0)")
            continue

        # Show all candidates (not just top 6) for visibility
        print(f"  Total signals: {len(cands)}, Top {min(len(cands), V_FINAL.max_pos)} selected:")
        print(f"  {'rank':>4s}  {'ticker':>7s}  {'name':<16s}  {'close':>7s}  "
              f"{'252d':>6s}  {'52w':>5s}  {'MA200':>5s}  {'vol×':>5s}  {'qual':>6s}")
        for i, s in enumerate(selected, 1):
            print(f"  {i:>4d}  {s['ticker']:>7s}  {str(s['name'])[:16]:<16s}  "
                  f"{s['close']:>7,.0f}  {s['ret_252d']*100:>+5.0f}%  "
                  f"{s['dist_52w']*100:>+4.0f}%  {s['ma200_dist']:>5.2f}  "
                  f"{s['vol_surge']:>5.2f}  {s['quality_score']:>6.3f}")

        # Show next-Monday actual entry price if available
        if next_day is not None:
            print(f"\n  💰 {next_day.strftime('%Y-%m-%d')} (Mon) 실제 OPEN 가격 — 백테스트 확인용:")
            for i, s in enumerate(selected, 1):
                df = data[s['ticker']]
                if next_day in df.index:
                    open_px = float(df['Open'].loc[next_day])
                    diff = (open_px / s['close'] - 1) * 100
                    print(f"    {s['ticker']} {s['name']}: signal close {s['close']:,.0f} → "
                          f"Mon OPEN {open_px:,.0f} ({diff:+.1f}%)")

    print("\n" + "="*78)
    print("[Done]")
    print("="*78)


if __name__ == '__main__':
    main()
