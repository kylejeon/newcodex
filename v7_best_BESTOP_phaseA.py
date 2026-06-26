#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7_best BE_STOP Phase A — 빠른 사후 시뮬레이션.

기존 v7_best_trades_cache.csv 의 모든 trade 에 대해:
  - BUY ~ SELL 사이 OHLC 가져와서 max_close 계산
  - 각 BE_STOP threshold (5/7/10/15/20) 적용 시 결과 시뮬
  - 새 종가 = entry_price (BE_STOP 트리거 시) vs 기존 종가 (안 트리거 시)

⚠️ 한계:
  - cascading effect 무시 (BE_STOP 일찍 매도 → 다음 매수 신호 변화)
  - 정확한 검증은 Phase B (v7_best.py 전체 수정) 필요

Phase A 결과가 promising 하면 Phase B 진행.
"""
from __future__ import annotations
import sys
import builtins
from pathlib import Path
from collections import defaultdict
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CACHE_CSV = ROOT / 'autobot_data' / 'v7_best_trades_cache.csv'
OUTPUT_FILE = ROOT / 'mnq_backtest_output' / 'v7_best_BESTOP_phaseA_result.txt'

# 백테 분석 대상 threshold
THRESHOLDS = [None, 5, 7, 10, 15, 20]  # None = baseline

# print 를 파일에도 미러링
_original_print = builtins.print
_output_fp = None

def _tee_print(*args, **kwargs):
    _original_print(*args, **kwargs)
    if _output_fp is not None:
        kwargs.pop('file', None)
        kwargs.pop('flush', None)
        _original_print(*args, file=_output_fp, **kwargs)
        _output_fp.flush()

builtins.print = _tee_print


def load_trades_cache() -> pd.DataFrame:
    df = pd.read_csv(CACHE_CSV)
    df['date'] = pd.to_datetime(df['date'])
    df['buy_date'] = pd.to_datetime(df['buy_date'], errors='coerce')
    return df


def pair_buys_sells(df: pd.DataFrame) -> list:
    """BUY-SELL pair 생성 (종목별 시계열)."""
    pairs = []
    for code, code_df in df.groupby('code'):
        code_df = code_df.sort_values('date').reset_index(drop=True)
        open_buy = None
        for _, row in code_df.iterrows():
            if row['action'] == 'BUY':
                open_buy = row
            elif row['action'] == 'SELL' and open_buy is not None:
                pairs.append({
                    'code': code,
                    'buy_date': open_buy['date'],
                    'buy_price': open_buy['buy_price'],
                    'sell_date': row['date'],
                    'sell_price': row['sell_price'],
                    'ret_pct': row['ret'],
                })
                open_buy = None
    return pairs


def fetch_ohlc_full(code):
    """KIS_Common.GetOhlcv 로 종목별 전체 OHLC fetch. 슬라이스는 호출자가."""
    import KIS_Common as Common
    df = Common.GetOhlcv("KR", code, 2200)
    if df is None or len(df) == 0:
        return None
    # index 가 str/Timestamp 둘 다 처리
    df.index = pd.to_datetime(df.index, errors='coerce')
    return df


def simulate_bestop(pairs: list, threshold: float | None) -> dict:
    """각 BUY-SELL pair 에 BE_STOP 적용 시뮬."""
    if threshold is None:
        # baseline: 원래 sell 그대로
        rets = [p['ret_pct'] for p in pairs if pd.notna(p.get('ret_pct'))]
        return {
            'threshold': None,
            'n_trades': len(rets),
            'be_triggered': 0,
            'be_triggered_winners_lost': 0,
            'be_triggered_losers_saved': 0,
            'cum_pnl_pct': sum(rets),
            'avg_ret_pct': sum(rets) / len(rets) if rets else 0,
            'win_rate': sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0,
        }

    new_rets = []
    be_triggered = 0
    winners_lost = 0   # max_gain >= threshold 였지만 결국 양봉 매도 — BE_STOP 시 일찍 청산
    losers_saved = 0   # max_gain >= threshold 였지만 음봉 매도 — BE_STOP 으로 손실 절감
    debug_first_n = 5
    debug_count = 0

    # OHLC fetch 캐싱
    ohlc_cache = {}

    for pair in pairs:
        if pd.isna(pair.get('buy_date')) or pd.isna(pair.get('sell_date')):
            continue
        if pair['buy_price'] <= 0 or pair['sell_price'] <= 0:
            continue

        code = pair['code']
        if code not in ohlc_cache:
            try:
                df = fetch_ohlc_full(code)
                ohlc_cache[code] = df
            except Exception as e:
                print(f"  ! {code} OHLC fail: {e}")
                ohlc_cache[code] = None

        df = ohlc_cache[code]
        if df is None:
            new_rets.append(pair['ret_pct'])
            continue

        # buy_date ~ sell_date 사이 OHLC (pair 별로 정확히 슬라이스)
        holding_df = df[(df.index >= pair['buy_date']) & (df.index <= pair['sell_date'])]
        if len(holding_df) == 0:
            new_rets.append(pair['ret_pct'])
            continue

        max_close = holding_df['close'].max()
        if pd.isna(max_close) or max_close <= 0:
            new_rets.append(pair['ret_pct'])
            continue
        max_gain_pct = (max_close - pair['buy_price']) / pair['buy_price'] * 100.0

        # 디버그: 첫 5개 trade 의 max_gain 값 확인
        if debug_count < debug_first_n:
            print(f"  [debug] {pair['code']} {pair['buy_date'].date()}~{pair['sell_date'].date()}: "
                  f"buy={pair['buy_price']:.0f} sell={pair['sell_price']:.0f} "
                  f"max_close={max_close:.0f} max_gain={max_gain_pct:+.2f}% ret={pair['ret_pct']:+.2f}%")
            debug_count += 1

        # BE_STOP trigger 조건: max_gain >= threshold 이고 sell_price 가 entry 아래
        if max_gain_pct >= threshold and pair['sell_price'] < pair['buy_price']:
            # BE_STOP 발동: entry 가격으로 청산 가정 (실제 봇은 시장가 → 약간 슬리피지)
            new_ret = 0.0  # entry break = approximately break-even (수수료 무시)
            new_rets.append(new_ret)
            be_triggered += 1
            losers_saved += 1
        elif max_gain_pct >= threshold and pair['sell_price'] >= pair['buy_price']:
            # max_gain ≥ threshold 였지만 양봉 매도 → BE_STOP 영향 없음 (이미 양봉)
            new_rets.append(pair['ret_pct'])
        else:
            # max_gain < threshold → BE_STOP 미발동, 원래 그대로
            new_rets.append(pair['ret_pct'])

    return {
        'threshold': threshold,
        'n_trades': len(new_rets),
        'be_triggered': be_triggered,
        'be_triggered_winners_lost': winners_lost,
        'be_triggered_losers_saved': losers_saved,
        'cum_pnl_pct': sum(new_rets),
        'avg_ret_pct': sum(new_rets) / len(new_rets) if new_rets else 0,
        'win_rate': sum(1 for r in new_rets if r > 0) / len(new_rets) * 100 if new_rets else 0,
    }


def main():
    global _output_fp
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _output_fp = open(OUTPUT_FILE, 'w', encoding='utf-8')
    print(f"[Phase A] BE_STOP 사후 시뮬레이션")
    print(f"  cache: {CACHE_CSV}")
    print(f"  output: {OUTPUT_FILE}")

    df = load_trades_cache()
    print(f"  total rows: {len(df)}")

    pairs = pair_buys_sells(df)
    print(f"  BUY-SELL pairs: {len(pairs)}")

    # 종목별 + 기간별 brief
    code_counts = defaultdict(int)
    for p in pairs:
        code_counts[p['code']] += 1
    print(f"  종목별 trade 수: {dict(code_counts)}")
    print(f"  기간: {min(p['buy_date'] for p in pairs)} ~ {max(p['sell_date'] for p in pairs)}")
    print()

    # 5년 / 최근 1년 / 6월 후반 시뮬
    periods = {
        'Full': (pd.Timestamp('2017-01-01'), pd.Timestamp('2026-12-31')),
        'Last1y': (pd.Timestamp('2025-06-27'), pd.Timestamp('2026-12-31')),
        '6월후반': (pd.Timestamp('2026-06-15'), pd.Timestamp('2026-06-30')),
    }

    for period_name, (start, end) in periods.items():
        period_pairs = [p for p in pairs
                        if start <= p['buy_date'] <= end and start <= p['sell_date'] <= end]
        print(f"{'='*70}")
        print(f"[{period_name}] {start.date()} ~ {end.date()}  ({len(period_pairs)} trades)")
        print(f"{'='*70}")

        results = []
        for th in THRESHOLDS:
            r = simulate_bestop(period_pairs, th)
            results.append(r)

        # baseline
        baseline = results[0]
        print(f"  {'th':>4s} {'trades':>6s} {'BE_trig':>7s} {'losers_saved':>12s} "
              f"{'win%':>6s} {'cum_PnL%':>10s} {'avg_ret%':>9s} {'vs base':>10s}")
        for r in results:
            th_str = 'base' if r['threshold'] is None else f"{r['threshold']:.0f}%"
            delta = r['cum_pnl_pct'] - baseline['cum_pnl_pct']
            print(f"  {th_str:>4s} {r['n_trades']:>6d} {r['be_triggered']:>7d} "
                  f"{r['be_triggered_losers_saved']:>12d} {r['win_rate']:>5.1f} "
                  f"{r['cum_pnl_pct']:>+9.2f} {r['avg_ret_pct']:>+8.2f} {delta:>+8.2f}pp")

        print()


if __name__ == '__main__':
    try:
        main()
    finally:
        if _output_fp is not None:
            _output_fp.close()
            _original_print(f"\n=== 결과 파일 저장 완료: {OUTPUT_FILE}")
