# -*- coding: utf-8 -*-
"""
V_FINAL Exit Monitor — 매일 보유 종목 exit signal check.

운영:
  - 매일 장 마감 후 (15:30+) 실행
  - holdings.json 의 보유 종목 각각 exit 조건 check
  - exit signal 발생 시 알림 → 다음 거래일 OPEN 매도

Exit 조건 (V11):
  - HARDSTOP -10% (30일 내)
  - Peak-stall escalation (5/10/20일)
  - FAST_MA10/20 (winner peak)
  - PARABOLIC (5d +12% + 음봉)
  - V4 ratchet trail (gain bracket)
  - MA200 backstop
  - 252일 TIME

Usage:
  python3 V_FINAL_exit_monitor.py [--date YYYY-MM-DD]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, compute_indicators, UNIVERSE_CSV, MAX_HOLD_DAYS,
)
from KOSDAQ_rocket_v11_exit import ExitCfg
import telegram_alert

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / 'v_final_holdings.json'
EXIT_LOG_DIR = ROOT / 'v_final_exits'
EXIT_LOG_DIR.mkdir(exist_ok=True)


def load_holdings():
    if not HOLDINGS_FILE.exists():
        return []
    try:
        with open(HOLDINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_holdings(holdings):
    with open(HOLDINGS_FILE, 'w') as f:
        json.dump(holdings, f, indent=2, ensure_ascii=False)


def exit_check(df, df_ind, target_idx, h, target_date):
    """V_FINAL exit logic. Returns (reason, details) or (None, None)."""
    entry_px = h['entry_px']
    entry_date = pd.Timestamp(h['entry_date'])
    days_held = (target_date - entry_date).days

    yc = float(df['Close'].iloc[target_idx])  # 오늘 종가
    if pd.isna(yc): return None, None
    max_close = h.get('max_close', entry_px)
    # update max_close
    if yc > max_close:
        max_close = yc
        h['max_close'] = yc
        h['max_close_date'] = target_date.isoformat()
    max_close_date = pd.Timestamp(h.get('max_close_date', h['entry_date']))
    days_since_peak = (target_date - max_close_date).days

    # HARDSTOP -10% in first 30 days
    if days_held < 30 and yc < entry_px * 0.90:
        return 'HARDSTOP', f"close {yc:,.0f} < entry-10% ({entry_px*0.9:,.0f})"

    max_gain = (max_close / entry_px - 1) * 100

    # D_BE_20: max_gain >= 20% 도달 후 close < entry → 매도 (V32H walk-forward +5.8pp 우위)
    if max_gain >= 20 and yc < entry_px:
        return 'BE_STOP', (f"max +{max_gain:.0f}% 도달 후 entry break "
                           f"(close {yc:,.0f} < entry {entry_px:,.0f})")

    # Peak-stall escalation
    if max_gain >= 30:
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

    # Fast MA
    if max_gain >= 100:
        ma10 = df_ind['MA10'].iloc[target_idx]
        if pd.notna(ma10) and yc < ma10:
            return 'FAST_MA10', f"100%+ winner, MA10 ({ma10:,.0f}) break"
    elif max_gain >= 50:
        ma20 = df_ind['MA20'].iloc[target_idx]
        if pd.notna(ma20) and yc < ma20:
            return 'FAST_MA20', f"50%+ winner, MA20 ({ma20:,.0f}) break"

    # Parabolic
    if max_gain >= 30:
        ret_5d = df_ind['Ret_5d'].iloc[target_idx]
        if pd.notna(ret_5d) and ret_5d > 0.12:
            o = float(df['Open'].iloc[target_idx])
            if pd.notna(o) and yc < o:
                return 'PARABOLIC', f"5일 +{ret_5d*100:.0f}% + 음봉 (close {yc:,.0f} < open {o:,.0f})"

    # v4 ratchet trail
    if max_gain >= 100:
        if yc < max_close * 0.65:
            return 'TRAIL35', f"100%+ → 35% trail break ({max_close*0.65:,.0f})"
        ma50 = df_ind['MA50'].iloc[target_idx]
        if pd.notna(ma50) and yc < ma50:
            return 'MA50', f"100%+ → MA50 ({ma50:,.0f}) break"
    elif max_gain >= 50:
        if yc < max_close * 0.70:
            return 'TRAIL30', f"50%+ → 30% trail break ({max_close*0.7:,.0f})"
        ma50 = df_ind['MA50'].iloc[target_idx]
        if pd.notna(ma50) and yc < ma50:
            return 'MA50', f"50%+ → MA50 ({ma50:,.0f}) break"
    elif max_gain >= 30:
        if yc < max_close * 0.75:
            return 'TRAIL25', f"30%+ → 25% trail break ({max_close*0.75:,.0f})"

    # MA200 backstop
    ma200 = df_ind['MA200'].iloc[target_idx]
    if pd.notna(ma200) and yc < ma200:
        return 'MA200', f"MA200 ({ma200:,.0f}) break"

    # TIME exit
    if days_held >= MAX_HOLD_DAYS:
        return 'TIME', f"252일 hold 도달"

    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='check 기준일 YYYY-MM-DD (default: latest)')
    args = parser.parse_args()

    print("="*78)
    print(f"V_FINAL Exit Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*78)

    holdings = load_holdings()
    if not holdings:
        print("\n  보유 종목 없음 — exit check skip")
        print(f"  (보유 종목 추가하려면 {HOLDINGS_FILE} 편집)")
        return

    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
    data = load_universe_data(udf)
    print(f"[data] {len(data)} OHLCV loaded")
    print("[indicators] computing...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    if args.date:
        target = pd.Timestamp(args.date)
        if target not in all_dates:
            valid = all_dates[all_dates <= target]
            target = valid[-1] if len(valid) > 0 else all_dates[-1]
    else:
        target = all_dates[-1]
    print(f"  check date: {target.strftime('%Y-%m-%d')}")

    print(f"\n[Holdings] {len(holdings)} positions")
    exits = []
    for h in holdings:
        ticker = h['ticker']
        name = name_map.get(ticker, h.get('name', '?'))
        if ticker not in data:
            print(f"  ⚠️ {ticker} {name}: data 없음")
            continue
        df = data[ticker]
        if target not in df.index:
            print(f"  ⚠️ {ticker} {name}: {target} OHLCV 없음")
            continue
        idx = df.index.get_loc(target)
        if idx == 0:
            print(f"  ⚠️ {ticker} {name}: 첫 날 데이터")
            continue
        df_ind = data_ind[ticker]
        reason, detail = exit_check(df, df_ind, idx, h, target)
        cur_price = float(df['Close'].iloc[idx])
        pnl = (cur_price / h['entry_px'] - 1) * 100
        max_close = h.get('max_close', h['entry_px'])
        max_gain = (max_close / h['entry_px'] - 1) * 100
        days_held = (target - pd.Timestamp(h['entry_date'])).days

        status = "🚨 EXIT" if reason else "✅ HOLD"
        print(f"\n  {status} {ticker} {name}")
        print(f"    entry {pd.Timestamp(h['entry_date']).strftime('%Y-%m-%d')} @ {h['entry_px']:,.0f}, "
              f"qty {h.get('qty', 0):,}")
        print(f"    current {cur_price:,.0f}, P&L {pnl:+.1f}%, "
              f"max {max_close:,.0f} ({max_gain:+.1f}%)")
        print(f"    hold {days_held}d")
        if reason:
            print(f"    🚨 REASON: {reason} — {detail}")
            exits.append({
                'ticker': ticker, 'name': name, 'reason': reason, 'detail': detail,
                'entry_date': h['entry_date'], 'entry_px': h['entry_px'],
                'current_px': cur_price, 'pnl_pct': pnl, 'max_gain_pct': max_gain,
                'days_held': days_held, 'qty': h.get('qty', 0),
            })

    # Save updated holdings (max_close tracking)
    save_holdings(holdings)

    # Save log
    out_path = EXIT_LOG_DIR / f'exits_{target.strftime("%Y%m%d")}.txt'
    with open(out_path, 'w') as f:
        f.write(f"V_FINAL Exit Monitor\n")
        f.write(f"Date: {target.strftime('%Y-%m-%d')}\n")
        f.write(f"Holdings: {len(holdings)}\n")
        f.write(f"Exit signals: {len(exits)}\n\n")
        for h in holdings:
            ticker = h['ticker']
            name = name_map.get(ticker, h.get('name', '?'))
            f.write(f"  {ticker} {name}: entry {h['entry_date']} @ {h['entry_px']:,.0f}\n")
        f.write("\n")
        if exits:
            f.write("🚨 EXIT SIGNALS (다음 거래일 OPEN 매도):\n")
            for e in exits:
                f.write(f"\n  {e['ticker']} {e['name']}\n")
                f.write(f"    reason: {e['reason']}\n")
                f.write(f"    detail: {e['detail']}\n")
                f.write(f"    entry: {e['entry_date']} @ {e['entry_px']:,.0f}\n")
                f.write(f"    current: {e['current_px']:,.0f} ({e['pnl_pct']:+.1f}%)\n")
                f.write(f"    max gain: {e['max_gain_pct']:+.1f}%, hold {e['days_held']}d\n")
                f.write(f"    qty: {e['qty']:,}\n")
        else:
            f.write("Exit signal 없음 — 모든 holdings HOLD\n")
    print(f"\n  💾 saved: {out_path}")

    if exits:
        print(f"\n{'='*78}")
        print(f"🚨 {len(exits)} EXIT SIGNAL(S) — 다음 거래일 OPEN 매도")
        for e in exits:
            print(f"  - {e['ticker']} {e['name']}: {e['reason']} (P&L {e['pnl_pct']:+.1f}%)")
        print("="*78)

        # Telegram alert for EXIT signals with inline keyboard
        msg_lines = [
            f"🚨 V_FINAL EXIT {target.strftime('%Y-%m-%d')}",
            f"매도 신호 {len(exits)}건 (다음 거래일 OPEN 매도)",
            "",
        ]
        for e in exits:
            msg_lines.append(
                f"• {e['ticker']} {e['name']}\n"
                f"  reason: {e['reason']}\n"
                f"  entry {pd.Timestamp(e['entry_date']).strftime('%Y-%m-%d')} @ {e['entry_px']:,.0f}\n"
                f"  current {e['current_px']:,.0f} (P&L {e['pnl_pct']:+.1f}%)\n"
                f"  hold {e['days_held']}d, qty {e['qty']:,}"
            )
        msg_lines.append("")
        msg_lines.append("매도 후 아래 버튼 클릭 → 체결가 답신")

        # Inline keyboard: 1 button per exit
        buttons = [
            [(f"✅ {e['ticker']} 매도완료",
              f"sell:{target.strftime('%Y%m%d')}:{e['ticker']}")]
            for e in exits
        ]
        keyboard = telegram_alert.InlineKeyboard(buttons)
        telegram_alert.SendMessage('\n'.join(msg_lines), reply_markup=keyboard)
    else:
        print(f"\n  ✅ All {len(holdings)} holdings HOLD — no exit signal")

        # Telegram heartbeat (HOLD all)
        msg_lines = [
            f"✅ V_FINAL Exit Check {target.strftime('%Y-%m-%d')}",
            f"보유 {len(holdings)}건 — 모두 HOLD",
            "",
        ]
        for h in holdings:
            ticker = h['ticker']
            name = name_map.get(ticker, h.get('name', '?'))
            if ticker in data and target in data[ticker].index:
                cur = float(data[ticker]['Close'].loc[target])
                pnl = (cur / h['entry_px'] - 1) * 100
                msg_lines.append(f"• {ticker} {name}: {cur:,.0f} ({pnl:+.1f}%)")
        telegram_alert.SendMessage('\n'.join(msg_lines))


if __name__ == '__main__':
    main()
