# -*- coding: utf-8 -*-
"""3-5월 entry 종목 exit 시뮬레이션."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, compute_indicators, UNIVERSE_CSV, MAX_HOLD_DAYS,
)
from V_FINAL_exit_monitor import exit_check


ENTRIES = [
    # (ticker, name, entry_date, entry_px)
    ('192410', '오늘이엔엠', '2026-03-23', 3925),
    ('054920', '한컴위드',    '2026-03-30', 5130),
    ('192250', '케이사인',    '2026-04-13', 11180),
    ('273060', '와이즈버즈',   '2026-04-20', 1200),
    ('083310', '엘오티베큠',   '2026-04-20', 16000),
    ('307870', '비투엔',      '2026-04-20', 1425),
    ('025900', '동화기업',     '2026-04-20', 12010),
    ('146320', '비씨엔씨',     '2026-04-20', 16690),
    ('064820', '케이프',      '2026-04-20', 13010),
    ('102940', '코오롱생명과학', '2026-05-11', 65600),
]


def simulate_exit(ticker, name, entry_date_str, entry_px, data, data_ind, end_date):
    df = data[ticker]
    df_ind = data_ind[ticker]
    entry_date = pd.Timestamp(entry_date_str)
    if entry_date not in df.index:
        return None
    entry_idx = df.index.get_loc(entry_date)
    h = {
        'ticker': ticker, 'name': name,
        'entry_date': entry_date_str, 'entry_px': entry_px,
        'qty': 1000, 'max_close': entry_px,
        'max_close_date': entry_date_str,
    }
    for i in range(entry_idx + 1, len(df)):
        date = df.index[i]
        if date > end_date:
            break
        reason, detail = exit_check(df, df_ind, i, h, date)
        if reason:
            # Exit at next day OPEN
            next_idx = i + 1
            if next_idx < len(df):
                exit_date = df.index[next_idx]
                exit_px = float(df.iloc[next_idx]['Open'])
            else:
                exit_date = date
                exit_px = float(df.iloc[i]['Close'])
            pnl_pct = (exit_px / entry_px - 1) * 100
            days_held = (exit_date - entry_date).days
            return {'reason': reason, 'detail': detail,
                    'exit_date': exit_date, 'exit_px': exit_px,
                    'pnl_pct': pnl_pct, 'days_held': days_held,
                    'max_close': h['max_close'],
                    'max_gain_pct': (h['max_close']/entry_px - 1) * 100}
    # No exit signal — still holding
    last_date = df.index[-1] if df.index[-1] <= end_date else df.index[df.index <= end_date][-1]
    last_px = float(df['Close'].loc[last_date])
    return {'reason': 'HOLD', 'detail': 'no exit signal yet',
            'exit_date': last_date, 'exit_px': last_px,
            'pnl_pct': (last_px/entry_px - 1) * 100,
            'days_held': (last_date - entry_date).days,
            'max_close': h['max_close'],
            'max_gain_pct': (h['max_close']/entry_px - 1) * 100}


def main():
    print("="*78)
    print("3-5월 V_FINAL entry 종목 exit 시뮬레이션")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    print(f"[data] {len(data)} OHLCV loaded")
    print("[indicators] computing...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}
    end_date = pd.Timestamp('2026-06-03')

    results = []
    print(f"\n{'='*78}")
    print(f"  {'ticker':>7s}  {'name':<14s}  {'entry':>11s}  {'entry_px':>8s}  "
          f"{'exit':>11s}  {'exit_px':>8s}  {'P&L':>7s}  {'maxG':>6s}  "
          f"{'days':>4s}  reason")
    print('-'*120)
    for ticker, name, entry_date, entry_px in ENTRIES:
        r = simulate_exit(ticker, name, entry_date, entry_px, data, data_ind, end_date)
        if r is None:
            print(f"  {ticker:>7s}  {name:<14s}  ERROR")
            continue
        results.append({'ticker': ticker, 'name': name, **r,
                        'entry_date': entry_date, 'entry_px': entry_px})
        print(f"  {ticker:>7s}  {name[:14]:<14s}  {entry_date:>11s}  "
              f"{entry_px:>8,.0f}  {r['exit_date'].strftime('%Y-%m-%d'):>11s}  "
              f"{r['exit_px']:>8,.0f}  {r['pnl_pct']:>+6.1f}%  "
              f"{r['max_gain_pct']:>+5.1f}%  {r['days_held']:>4d}  "
              f"{r['reason']}: {r['detail']}")

    # Summary
    closed = [r for r in results if r['reason'] != 'HOLD']
    held = [r for r in results if r['reason'] == 'HOLD']
    print(f"\n{'='*78}")
    print(f"[Summary] {len(results)} positions")
    print(f"  Exit triggered: {len(closed)}")
    print(f"  Still holding: {len(held)}")
    if closed:
        avg_pnl = sum(r['pnl_pct'] for r in closed) / len(closed)
        win_count = sum(1 for r in closed if r['pnl_pct'] > 0)
        print(f"  Closed avg P&L: {avg_pnl:+.1f}%, win rate: {win_count}/{len(closed)}")
    if held:
        avg_unrealized = sum(r['pnl_pct'] for r in held) / len(held)
        print(f"  Holding avg unrealized: {avg_unrealized:+.1f}%")

    print(f"\n{'='*78}")
    print("[Per-position equity contribution (1/6 weight)]")
    total = 0
    for r in results:
        contrib = r['pnl_pct'] / 6  # 1/6 weight
        total += contrib
        status = "✅" if r['reason'] == 'HOLD' else ("🚨" if r['pnl_pct'] < 0 else "💰")
        print(f"  {status} {r['ticker']} {r['name'][:12]:<12s}: P&L {r['pnl_pct']:+6.1f}% "
              f"× 1/6 = {contrib:+5.2f}%  [{r['reason']}]")
    print(f"\n  Total contribution: {total:+.2f}%")
    print(f"  (Note: assuming 6-position equal weight, simultaneous holding)")


if __name__ == '__main__':
    main()
