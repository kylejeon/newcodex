# -*- coding: utf-8 -*-
"""
V_FINAL Signal Bot — 매주 금요일 entry signal scan.

운영:
  - 매주 금요일 장 마감 후 (15:30+) 실행
  - 1208 KOSDAQ universe 에 V_FINAL config 적용
  - signal 종목 list + entry quality 출력
  - 보유 종목 (holdings.json) 자동 제외
  - 결과: signals_YYYYMMDD.txt + 콘솔 출력

수동 매매: CEO 가 월요일 OPEN 에 신호 종목 부계좌에서 매수

Usage:
  python3 V_FINAL_signal_bot.py [--date YYYY-MM-DD]

  --date: scan 기준일 (default: 오늘)
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
    load_universe_data, load_investor_data, compute_indicators,
    UNIVERSE_CSV,
)
from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
import telegram_alert

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / 'v_final_holdings.json'
SIGNAL_LOG_DIR = ROOT / 'v_final_signals'
SIGNAL_LOG_DIR.mkdir(exist_ok=True)


# V_FINAL config (불변)
class V_FINAL:
    ma200_max_dist = 1.45
    vol_mult       = 2.0
    lowvol_th      = 0.07
    max_pos        = 6
    par            = 0.12


def signal_A_final(df, df_ind, date, vc, investor_data, ticker):
    """V_FINAL entry signal A."""
    row = df_ind.loc[date]
    if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                      'VolAvg10','ATR10','ATR50','Ret_252d','MA200']):
        return None
    if row['MA60'] <= 0 or row['High52w'] <= 0: return None
    if not (row['Close'] > row['MA60']): return None
    if not (row['MA60_slope'] > 0): return None
    if row['Ret_252d'] < 0.20 or row['Ret_252d'] > 3.00: return None
    dist52w = (row['High52w'] - row['Close']) / row['High52w']
    if dist52w > 0.60: return None
    atr_ratio = row['ATR10'] / row['ATR50']
    if atr_ratio > 1.20: return None
    vol_dryup = row['VolAvg10'] / row['VolAvg50']
    if vol_dryup > 1.50: return None
    high_b_prev = df['Close'].rolling(20).max().shift(1).loc[date]
    if pd.isna(high_b_prev): return None
    if not (row['Close'] > high_b_prev): return None
    vol_surge = row['Volume'] / row['VolAvg50']
    if vol_surge < vc.vol_mult: return None
    ma200_dist = row['Close'] / row['MA200']
    if ma200_dist > vc.ma200_max_dist: return None
    if not has_foreign_buy(investor_data, ticker, date, 20): return None

    return {
        'ticker': ticker,
        'close': float(row['Close']),
        'ret_252d': float(row['Ret_252d']),
        'dist_52w': float(dist52w),
        'atr_ratio': float(atr_ratio),
        'vol_dryup': float(vol_dryup),
        'vol_surge': float(vol_surge),
        'ma200_dist': float(ma200_dist),
        'breakout_high20': float(high_b_prev),
    }


def load_holdings():
    if not HOLDINGS_FILE.exists():
        return set()
    try:
        with open(HOLDINGS_FILE) as f:
            data = json.load(f)
        return {h['ticker'] for h in data}
    except Exception:
        return set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='scan 기준일 YYYY-MM-DD (default: latest)')
    args = parser.parse_args()

    print("="*78)
    print(f"V_FINAL Signal Bot — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*78)

    # Load data
    print("\n[1] Loading universe + OHLCV + investor cache...")
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"  {len(data)} OHLCV, {len(investor_data)} investor cache")

    # Compute indicators
    print("[2] Computing indicators...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    # Determine scan date
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    if args.date:
        target = pd.Timestamp(args.date)
        if target not in all_dates:
            valid = all_dates[all_dates <= target]
            target = valid[-1] if len(valid) > 0 else all_dates[-1]
    else:
        target = all_dates[-1]
    print(f"  scan date: {target.strftime('%Y-%m-%d')} ({target.day_name()})")

    # Market filter
    print("[3] Market filter (KOSDAQ lowvol)...")
    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, V_FINAL.lowvol_th)
    market_ok = check(target)
    if not market_ok:
        print(f"  🔴 KOSDAQ 14d abs return ≥ {V_FINAL.lowvol_th*100:.0f}% — SKIP entry")
        out_path = SIGNAL_LOG_DIR / f'signals_{target.strftime("%Y%m%d")}.txt'
        with open(out_path, 'w') as f:
            f.write(f"Date: {target.strftime('%Y-%m-%d')}\n")
            f.write(f"Status: MARKET_FILTER_BLOCK\n")
            f.write(f"Reason: KOSDAQ 14d abs return ≥ {V_FINAL.lowvol_th*100}%\n")
        print(f"  → save: {out_path}")
        telegram_alert.SendMessage(
            f"📅 V_FINAL Signal {target.strftime('%Y-%m-%d')} (금)\n"
            f"🔴 KOSDAQ 14d 변동성 ≥ {V_FINAL.lowvol_th*100:.0f}% → SKIP\n"
            f"다음 스캔: 1주 후"
        )
        return
    print(f"  🟢 Market filter PASS (14d abs < {V_FINAL.lowvol_th*100:.0f}%)")

    # Holdings exclusion
    holdings = load_holdings()
    print(f"[4] Current holdings: {len(holdings)} ({sorted(holdings)})")

    # Scan
    print(f"[5] Scanning {len(data)} tickers for V_FINAL signal A...")
    cands = []
    for ticker, df in data.items():
        if ticker in holdings:
            continue
        if target not in df.index:
            continue
        df_ind = data_ind[ticker]
        sig = signal_A_final(df, df_ind, target, V_FINAL, investor_data, ticker)
        if sig:
            sig['name'] = name_map.get(ticker, '?')
            # quality score (낮을수록 좋음)
            # ma200_dist 낮을수록, vol_surge 클수록, dist_52w 낮을수록 good
            sig['quality_score'] = (
                sig['ma200_dist']
                + sig['dist_52w']
                - sig['vol_surge'] * 0.05
                + sig['atr_ratio'] * 0.5
            )
            cands.append(sig)

    # Sort by quality (lower is better)
    cands.sort(key=lambda c: c['quality_score'])

    # Limit to max_pos - holdings
    available_slots = V_FINAL.max_pos - len(holdings)
    selected = cands[:available_slots] if available_slots > 0 else []

    # Output
    print(f"\n[6] Results")
    print(f"  Total signals: {len(cands)}, available slots: {available_slots}")
    print(f"  Selected: {len(selected)}")

    if not selected:
        print("\n  → 진입 신호 없음")
        telegram_alert.SendMessage(
            f"📅 V_FINAL Signal {target.strftime('%Y-%m-%d')} (금)\n"
            f"신호 없음 (보유 {len(holdings)}/{V_FINAL.max_pos})\n"
            f"다음 스캔: 1주 후"
        )
    else:
        print("\n  📊 진입 신호 (월요일 OPEN 매수)")
        print(f"  {'rank':>4s}  {'ticker':>7s}  {'name':<18s}  {'close':>8s}  "
              f"{'252d':>7s}  {'52w':>6s}  {'MA200':>6s}  {'vol×':>5s}  {'quality':>7s}")
        for i, s in enumerate(selected, 1):
            print(f"  {i:>4d}  {s['ticker']:>7s}  {str(s['name'])[:18]:<18s}  "
                  f"{s['close']:>8,.0f}  {s['ret_252d']*100:>+6.0f}%  "
                  f"{s['dist_52w']*100:>+5.0f}%  {s['ma200_dist']:>6.2f}  "
                  f"{s['vol_surge']:>5.2f}  {s['quality_score']:>7.3f}")

        # Telegram alert (selected signals) with inline keyboard
        msg_lines = [
            f"🎯 V_FINAL Signal {target.strftime('%Y-%m-%d')} (금)",
            f"🟢 Market PASS, 신호 {len(selected)}건 (보유 {len(holdings)}/{V_FINAL.max_pos})",
            f"→ 월요일 OPEN 매수",
            "",
        ]
        for i, s in enumerate(selected, 1):
            msg_lines.append(
                f"{i}. {s['ticker']} {s['name']}\n"
                f"   Close {s['close']:,.0f}원 | 252d {s['ret_252d']*100:+.0f}% | "
                f"MA200 {s['ma200_dist']:.2f}x | vol× {s['vol_surge']:.2f}"
            )
        msg_lines.append("")
        msg_lines.append("매수 후 아래 버튼 클릭 → 체결가/수량 답신")

        # Save signals to pending state file (for callback handler)
        pending_dir = ROOT / 'v_final_pending'
        pending_dir.mkdir(exist_ok=True)
        pending_file = pending_dir / f'pending_signals_{target.strftime("%Y%m%d")}.json'
        import json as _json
        pending_data = {
            'scan_date': target.strftime('%Y-%m-%d'),
            'signals': [
                {'ticker': s['ticker'], 'name': s['name'], 'close': s['close']}
                for s in selected
            ],
        }
        with open(pending_file, 'w') as f:
            _json.dump(pending_data, f, indent=2, ensure_ascii=False)

        # Inline keyboard: 1 row per signal
        buttons = [
            [(f"✅ {i+1}. {s['ticker']} 매수완료",
              f"buy:{target.strftime('%Y%m%d')}:{s['ticker']}")]
            for i, s in enumerate(selected)
        ]
        keyboard = telegram_alert.InlineKeyboard(buttons)
        telegram_alert.SendMessage('\n'.join(msg_lines), reply_markup=keyboard)

    # Save log
    out_path = SIGNAL_LOG_DIR / f'signals_{target.strftime("%Y%m%d")}.txt'
    with open(out_path, 'w') as f:
        f.write(f"V_FINAL Signal Scan\n")
        f.write(f"Date: {target.strftime('%Y-%m-%d')} ({target.day_name()})\n")
        f.write(f"Market filter: PASS\n")
        f.write(f"Holdings: {sorted(holdings)} ({len(holdings)}/{V_FINAL.max_pos})\n")
        f.write(f"Available slots: {available_slots}\n")
        f.write(f"Total signals: {len(cands)}\n")
        f.write(f"Selected: {len(selected)}\n\n")
        if selected:
            f.write("진입 신호 (월요일 OPEN 매수):\n")
            for i, s in enumerate(selected, 1):
                f.write(f"  {i}. {s['ticker']} {s['name']} @ {s['close']:,.0f}\n")
                f.write(f"     252일 수익률: {s['ret_252d']*100:+.0f}%\n")
                f.write(f"     52주 고가 거리: {s['dist_52w']*100:+.0f}%\n")
                f.write(f"     MA200 거리: {s['ma200_dist']:.2f}x\n")
                f.write(f"     거래량 surge: {s['vol_surge']:.2f}x\n")
                f.write(f"     ATR ratio: {s['atr_ratio']:.2f}\n")
                f.write(f"     Quality score: {s['quality_score']:.3f}\n\n")
        else:
            f.write("진입 신호 없음\n")
    print(f"\n  💾 saved: {out_path}")
    print("="*78)


if __name__ == '__main__':
    main()
