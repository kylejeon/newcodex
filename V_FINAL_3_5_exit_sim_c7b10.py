# -*- coding: utf-8 -*-
"""3-5월 entry 종목에 C7_B10 exit 룰 적용 시뮬레이션."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, compute_indicators, UNIVERSE_CSV, MAX_HOLD_DAYS,
)


# Entries from V_FINAL_3_5_exit_sim.py
ENTRIES = [
    ('192410', '오늘이엔엠',     '2026-03-23', 3925),
    ('054920', '한컴위드',       '2026-03-30', 5130),
    ('192250', '케이사인',       '2026-04-13', 11180),
    ('273060', '와이즈버즈',     '2026-04-20', 1200),
    ('083310', '엘오티베큠',     '2026-04-20', 16000),
    ('307870', '비투엔',         '2026-04-20', 1425),
    ('025900', '동화기업',       '2026-04-20', 12010),
    ('146320', '비씨엔씨',       '2026-04-20', 16690),
    ('064820', '케이프',         '2026-04-20', 13010),
    ('102940', '코오롱생명과학',  '2026-05-11', 65600),
]


def exit_check_c7b10(df, df_ind, target_idx, h, target_date):
    """V_FINAL_exit_monitor exit_check + C7 (HARDSTOP -7%) + B10 (STALL @ max_gain>=10%)."""
    entry_px = h['entry_px']
    entry_date = pd.Timestamp(h['entry_date'])
    days_held = (target_date - entry_date).days

    yc = float(df['Close'].iloc[target_idx])
    if pd.isna(yc): return None, None
    max_close = h.get('max_close', entry_px)
    if yc > max_close:
        max_close = yc
        h['max_close'] = yc
        h['max_close_date'] = target_date.isoformat()
    max_close_date = pd.Timestamp(h.get('max_close_date', h['entry_date']))
    days_since_peak = (target_date - max_close_date).days

    # C7: HARDSTOP -7% (was -10%)
    if days_held < 30 and yc < entry_px * 0.93:
        return 'HARDSTOP', f"close {yc:,.0f} < entry-7% ({entry_px*0.93:,.0f})"

    max_gain = (max_close / entry_px - 1) * 100

    # B10: Peak-stall escalation activates at max_gain >= 10% (was 30%)
    if max_gain >= 10:
        if days_since_peak >= 20:
            if yc < max_close * 0.90:
                return 'STALL20_T10', f"20일+ 정체, 10% trail break ({max_close*0.9:,.0f})"
            ma20 = df_ind['MA20'].iloc[target_idx]
            if pd.notna(ma20) and yc < ma20:
                return 'STALL20_MA20', f"20일+ 정체, MA20 ({ma20:,.0f}) break"
        elif days_since_peak >= 10:
            if yc < max_close * 0.85:
                return 'STALL10_T15', f"10-20일 정체, 15% trail break ({max_close*0.85:,.0f})"
        elif days_since_peak >= 5:
            if yc < max_close * 0.75:
                return 'STALL5_T25', f"5-10일 정체, 25% trail break ({max_close*0.75:,.0f})"

    # FAST_MA (unchanged thresholds)
    if max_gain >= 100:
        ma10 = df_ind['MA10'].iloc[target_idx]
        if pd.notna(ma10) and yc < ma10:
            return 'FAST_MA10', f"100%+ winner, MA10 ({ma10:,.0f}) break"
    elif max_gain >= 50:
        ma20 = df_ind['MA20'].iloc[target_idx]
        if pd.notna(ma20) and yc < ma20:
            return 'FAST_MA20', f"50%+ winner, MA20 ({ma20:,.0f}) break"

    # Parabolic (unchanged 30% threshold)
    if max_gain >= 30:
        ret_5d = df_ind['Ret_5d'].iloc[target_idx]
        if pd.notna(ret_5d) and ret_5d > 0.12:
            o = float(df['Open'].iloc[target_idx])
            if pd.notna(o) and yc < o:
                return 'PARABOLIC', f"5일 +{ret_5d*100:.0f}% + 음봉 (close {yc:,.0f} < open {o:,.0f})"

    # v4 ratchet trail (unchanged thresholds)
    if max_gain >= 100:
        if yc < max_close * 0.65:
            return 'TRAIL35', f"100%+ → 35% trail break"
        ma50 = df_ind['MA50'].iloc[target_idx]
        if pd.notna(ma50) and yc < ma50:
            return 'MA50', f"100%+ → MA50 break"
    elif max_gain >= 50:
        if yc < max_close * 0.70:
            return 'TRAIL30', f"50%+ → 30% trail break"
        ma50 = df_ind['MA50'].iloc[target_idx]
        if pd.notna(ma50) and yc < ma50:
            return 'MA50', f"50%+ → MA50 break"
    elif max_gain >= 30:
        if yc < max_close * 0.75:
            return 'TRAIL25', f"30%+ → 25% trail break"

    # MA200 backstop
    ma200 = df_ind['MA200'].iloc[target_idx]
    if pd.notna(ma200) and yc < ma200:
        return 'MA200', f"MA200 ({ma200:,.0f}) break"

    # TIME exit
    if days_held >= MAX_HOLD_DAYS:
        return 'TIME', f"252일 hold 도달"

    return None, None


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
        reason, detail = exit_check_c7b10(df, df_ind, i, h, date)
        if reason:
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
    print("3-5월 V_FINAL entry 종목 — C7_B10 exit 룰 시뮬레이션")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    print(f"[data] {len(data)} OHLCV loaded")
    print("[indicators]...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}
    end_date = pd.Timestamp('2026-06-03')

    results = []
    print(f"\n  {'ticker':>7s}  {'name':<14s}  {'entry':>11s}  {'entry_px':>8s}  "
          f"{'exit':>11s}  {'exit_px':>8s}  {'P&L':>7s}  {'maxG':>6s}  "
          f"{'days':>4s}  reason")
    print('-'*130)
    for ticker, name, entry_date, entry_px in ENTRIES:
        r = simulate_exit(ticker, name, entry_date, entry_px, data, data_ind, end_date)
        if r is None:
            continue
        results.append({'ticker': ticker, 'name': name, **r,
                        'entry_date': entry_date, 'entry_px': entry_px})
        print(f"  {ticker:>7s}  {name[:14]:<14s}  {entry_date:>11s}  "
              f"{entry_px:>8,.0f}  {r['exit_date'].strftime('%Y-%m-%d'):>11s}  "
              f"{r['exit_px']:>8,.0f}  {r['pnl_pct']:>+6.1f}%  "
              f"{r['max_gain_pct']:>+5.1f}%  {r['days_held']:>4d}  "
              f"{r['reason']}: {r['detail']}")

    print(f"\n{'='*78}")
    print(f"[Summary C7_B10] {len(results)} positions")
    closed = [r for r in results if r['reason'] != 'HOLD']
    held = [r for r in results if r['reason'] == 'HOLD']
    print(f"  Exit: {len(closed)}, Hold: {len(held)}")
    if closed:
        avg_pnl = sum(r['pnl_pct'] for r in closed) / len(closed)
        win_count = sum(1 for r in closed if r['pnl_pct'] > 0)
        print(f"  Closed avg P&L: {avg_pnl:+.1f}%, win rate: {win_count}/{len(closed)}")
    # 흑자→적자 전환 카운트
    loss_with_max = sum(1 for r in results if r['max_gain_pct'] > 5 and r['pnl_pct'] <= 0)
    print(f"  흑자(+5%) → 적자 전환: {loss_with_max}건")

    # Per-position 1/6 contribution
    print(f"\n[Per-position 1/6 weight contribution]")
    total = 0
    for r in results:
        contrib = r['pnl_pct'] / 6
        total += contrib
        status = "✅" if r['reason'] == 'HOLD' else ("💰" if r['pnl_pct'] > 0 else "🚨")
        print(f"  {status} {r['ticker']} {r['name'][:12]:<12s}: P&L {r['pnl_pct']:+6.1f}% "
              f"× 1/6 = {contrib:+5.2f}%  [{r['reason']}]")
    print(f"\n  Total: {total:+.2f}%")


if __name__ == '__main__':
    main()
