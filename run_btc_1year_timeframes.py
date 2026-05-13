# -*- coding: utf-8 -*-
'''
BTC 1년 백테스트 - 1m/5m/15m/1h 타임프레임 비교.
1분봉이 노이즈로 실패했을 가능성을 검증.
'''
from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np

from run_btc_1year_backtest import (
    CSV_PATH, OUT_DIR, load_csv, add_indicators, run_backtest, summarize,
    START_CAPITAL, NOTIONAL_PER_TRADE, COMMISSION_RATE,
)
import run_btc_1year_backtest as bt


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    out = df.resample(rule).agg(agg).dropna()
    return out


def main():
    print(f"[load] {CSV_PATH}")
    base = load_csv()
    print(f"[load] rows={len(base):,}  span={(base.index[-1]-base.index[0]).total_seconds()/86400:.1f}d")

    timeframes = [
        ('1m',  None),
        ('5m',  '5min'),
        ('15m', '15min'),
        ('1h',  '1h'),
    ]
    configs = [
        ('baseline',      1.4, 0.25, 0.45, 1.8),
        ('wider_0.50',    1.4, 0.50, 0.45, 1.8),
        ('wider_1.00',    1.4, 1.00, 0.45, 1.8),
        ('strict_2.5',    2.5, 0.50, 0.45, 1.8),
        ('strict_3.0',    3.0, 0.50, 0.45, 1.8),
        ('combo_tight',   2.5, 0.50, 0.25, 2.5),
    ]

    rows = []
    for tf_label, rule in timeframes:
        print(f"\n--- {tf_label} ---")
        if rule is None:
            df = base.copy()
        else:
            df = resample(base, rule)
            print(f"  resampled rows={len(df):,}")
        # 각 타임프레임에서 MIN_TARGET_PCT 살짝 조정: 노이즈 적을수록 줄여도 됨
        if tf_label == '1m':
            bt.MIN_TARGET_PCT = 0.004
        elif tf_label == '5m':
            bt.MIN_TARGET_PCT = 0.003
        elif tf_label == '15m':
            bt.MIN_TARGET_PCT = 0.003
        else:
            bt.MIN_TARGET_PCT = 0.002
        print(f"  MIN_TARGET_PCT={bt.MIN_TARGET_PCT}")

        idf = add_indicators(df)
        print(f"  after indicators rows={len(idf):,}")
        for label, s, r, sb, mi in configs:
            tr, eq = run_backtest(idf, stretch_atr=s, retrace=r,
                                  stop_atr_buffer=sb, min_impulse_atr=mi)
            st = summarize(tr, eq)
            rows.append({
                'tf': tf_label,
                'label': label,
                'stretch': s, 'retrace': r, 'stop_buf': sb, 'impulse': mi,
                **st,
            })
    df = pd.DataFrame(rows)
    df = df.sort_values('net_pnl', ascending=False).reset_index(drop=True)

    # 출력
    show = df[['tf','label','trades','win_rate','net_pnl','return_pct',
               'profit_factor','max_drawdown_pct','avg_win','avg_loss']].round(2)
    print("\n================ COMBINED TIMEFRAME × CONFIG ================")
    print(show.to_string(index=False))
    df.to_csv(OUT_DIR / 'btc_1year_timeframe_grid.csv', index=False)

    # 상위 3개
    print("\n[TOP-5 net_pnl]")
    print(show.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
