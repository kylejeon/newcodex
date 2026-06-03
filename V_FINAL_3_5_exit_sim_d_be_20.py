# -*- coding: utf-8 -*-
"""3-5월 entry 종목에 D_BE_20 (BE_STOP at max_gain>=20%) exit 룰 적용."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, compute_indicators, UNIVERSE_CSV, MAX_HOLD_DAYS,
)

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


def exit_check_d_be_20(df, df_ind, target_idx, h, target_date):
    """V_FINAL baseline + D_BE_20 룰 추가."""
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
    max_gain = (max_close / entry_px - 1) * 100

    # HARDSTOP -10% (baseline)
    if days_held < 30 and yc < entry_px * 0.90:
        return 'HARDSTOP', f"close {yc:,.0f} < entry-10%"

    # D_BE_20: max_gain >= 20% 도달 후 close < entry → 매도
    if max_gain >= 20 and yc < entry_px:
        return 'BE_STOP', f"max +{max_gain:.0f}% 도달 후 entry break (close {yc:,.0f} < entry {entry_px:,.0f})"

    # Peak-stall escalation (30% threshold - baseline)
    if max_gain >= 30:
        if days_since_peak >= 20:
            if yc < max_close * 0.90: return 'STALL20_T10', f"20+d, 10% trail"
            ma20 = df_ind['MA20'].iloc[target_idx]
            if pd.notna(ma20) and yc < ma20: return 'STALL20_MA20', f"MA20 break"
        elif days_since_peak >= 10:
            if yc < max_close * 0.85: return 'STALL10_T15', f"15% trail"
        elif days_since_peak >= 5:
            if yc < max_close * 0.75: return 'STALL5_T25', f"25% trail"
    if max_gain >= 100:
        ma10 = df_ind['MA10'].iloc[target_idx]
        if pd.notna(ma10) and yc < ma10: return 'FAST_MA10', f"MA10 break"
    elif max_gain >= 50:
        ma20 = df_ind['MA20'].iloc[target_idx]
        if pd.notna(ma20) and yc < ma20: return 'FAST_MA20', f"MA20 break"
    if max_gain >= 30:
        ret_5d = df_ind['Ret_5d'].iloc[target_idx]
        if pd.notna(ret_5d) and ret_5d > 0.12:
            o = float(df['Open'].iloc[target_idx])
            if pd.notna(o) and yc < o: return 'PARABOLIC', f"5d+{ret_5d*100:.0f}% +음봉"
    if max_gain >= 100:
        if yc < max_close * 0.65: return 'TRAIL35', f"35% trail"
        ma50 = df_ind['MA50'].iloc[target_idx]
        if pd.notna(ma50) and yc < ma50: return 'MA50', f"MA50 break"
    elif max_gain >= 50:
        if yc < max_close * 0.70: return 'TRAIL30', f"30% trail"
        ma50 = df_ind['MA50'].iloc[target_idx]
        if pd.notna(ma50) and yc < ma50: return 'MA50', f"MA50 break"
    elif max_gain >= 30:
        if yc < max_close * 0.75: return 'TRAIL25', f"25% trail"
    ma200 = df_ind['MA200'].iloc[target_idx]
    if pd.notna(ma200) and yc < ma200: return 'MA200', f"MA200 break"
    if days_held >= MAX_HOLD_DAYS: return 'TIME', f"252d"
    return None, None


def simulate_exit(ticker, name, entry_date_str, entry_px, data, data_ind, end_date):
    df = data[ticker]; df_ind = data_ind[ticker]
    entry_date = pd.Timestamp(entry_date_str)
    if entry_date not in df.index: return None
    entry_idx = df.index.get_loc(entry_date)
    h = {'ticker': ticker, 'name': name, 'entry_date': entry_date_str,
         'entry_px': entry_px, 'qty': 1000, 'max_close': entry_px,
         'max_close_date': entry_date_str}
    for i in range(entry_idx + 1, len(df)):
        date = df.index[i]
        if date > end_date: break
        reason, detail = exit_check_d_be_20(df, df_ind, i, h, date)
        if reason:
            next_idx = i + 1
            if next_idx < len(df):
                exit_date = df.index[next_idx]
                exit_px = float(df.iloc[next_idx]['Open'])
            else:
                exit_date = date; exit_px = float(df.iloc[i]['Close'])
            pnl_pct = (exit_px / entry_px - 1) * 100
            return {'reason': reason, 'detail': detail, 'exit_date': exit_date,
                    'exit_px': exit_px, 'pnl_pct': pnl_pct,
                    'days_held': (exit_date - entry_date).days,
                    'max_gain_pct': (h['max_close']/entry_px - 1) * 100}
    last_date = df.index[df.index <= end_date][-1]
    last_px = float(df['Close'].loc[last_date])
    return {'reason': 'HOLD', 'detail': '', 'exit_date': last_date,
            'exit_px': last_px, 'pnl_pct': (last_px/entry_px - 1) * 100,
            'days_held': (last_date - entry_date).days,
            'max_gain_pct': (h['max_close']/entry_px - 1) * 100}


def main():
    print("="*78)
    print("3-5월 V_FINAL — D_BE_20 (BE_STOP @ max+20%) 시뮬레이션")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    print(f"[data] {len(data)} OHLCV")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}
    end_date = pd.Timestamp('2026-06-03')

    print(f"\n  {'ticker':>7s}  {'name':<14s}  {'maxG':>6s}  {'P&L':>7s}  {'days':>4s}  reason")
    print('-'*100)
    total_contrib = 0
    for ticker, name, entry_date, entry_px in ENTRIES:
        r = simulate_exit(ticker, name, entry_date, entry_px, data, data_ind, end_date)
        contrib = r['pnl_pct'] / 6
        total_contrib += contrib
        print(f"  {ticker:>7s}  {name[:14]:<14s}  {r['max_gain_pct']:>+5.1f}%  "
              f"{r['pnl_pct']:>+6.1f}%  {r['days_held']:>4d}  {r['reason']}: {r['detail']}")
    print(f"\n  Total 1/6 weight contribution: {total_contrib:+.2f}%")


if __name__ == '__main__':
    main()
