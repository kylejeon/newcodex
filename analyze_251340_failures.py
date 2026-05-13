# -*- coding: utf-8 -*-
'''
251340 (코스닥 숏 ETF) 실패 패턴 분석.
baseline 매도 로그 + 일봉 지표(OHLCV + 이동평균/RSI/Disparity)를 매수일 기준으로 조인.
승/패 그룹의 지표 차이를 찾아 필터 후보 도출.
'''
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import KIS_Common as Common  # noqa: E402

TARGET = '251340'
TRADES_CSV = Path('/Users/yonghyuk/newcodex/mnq_backtest_output/v7_cfg_baseline_trades.csv')
OUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')

Common.SetChangeMode("REAL")


def load_daily(stock_code: str, periods: int = 2200) -> pd.DataFrame:
    df = Common.GetOhlcv("KR", stock_code, periods)
    # 주요 지표 재계산 (v7_best와 동일)
    period = 14
    delta = df['close'].diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    gain = up.ewm(com=(period - 1), min_periods=period).mean()
    loss = down.abs().ewm(com=(period - 1), min_periods=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['prevRSI'] = df['RSI'].shift(1)

    df['prevClose'] = df['close'].shift(1)
    df['prevHigh'] = df['high'].shift(1)
    df['prevLow'] = df['low'].shift(1)
    df['prevVolume'] = df['volume'].shift(1)
    df['Disparity20'] = df['prevClose'] / df['prevClose'].rolling(20).mean() * 100.0
    df['Disparity11'] = df['prevClose'] / df['prevClose'].rolling(11).mean() * 100.0
    df['ma5_before'] = df['close'].rolling(5).mean().shift(1)
    df['ma10_before'] = df['close'].rolling(10).mean().shift(1)
    df['ma20_before'] = df['close'].rolling(20).mean().shift(1)
    df['ma60_before'] = df['close'].rolling(60).mean().shift(1)
    df['ma120_before'] = df['close'].rolling(120).mean().shift(1)
    df['prevChangeMa'] = df['change'].shift(1).rolling(20).mean() if 'change' in df.columns \
        else df['close'].pct_change().shift(1).rolling(20).mean()

    # 7일 고저
    df['high_7_max'] = df['high'].rolling(7).max().shift(1)
    df['low_7_min'] = df['low'].rolling(7).min().shift(1)

    # range / gap
    df['prev_range_pct'] = (df['prevHigh'] - df['prevLow']) / df['prevClose'] * 100.0
    df['gap_pct'] = (df['open'] - df['prevClose']) / df['prevClose'] * 100.0

    # 추세 정렬
    df['is_jung'] = (
        (df['ma10_before'] > df['ma20_before']) &
        (df['ma20_before'] > df['ma60_before']) &
        (df['ma60_before'] > df['ma120_before'])
    )

    df.dropna(inplace=True)
    df.index = pd.to_datetime(df.index)
    return df


def main():
    tr = pd.read_csv(TRADES_CSV, parse_dates=['date', 'buy_date'])
    tr = tr[tr['code'].astype(str).str.zfill(6) == TARGET].copy()
    if tr.empty:
        print(f"No trades for {TARGET} in {TRADES_CSV}")
        return

    tr['win'] = tr['revenue_rate'] > 0
    print(f"[{TARGET}] total trades: {len(tr)}")
    print(f"[{TARGET}] wins: {int(tr['win'].sum())}, "
          f"losses: {int((~tr['win']).sum())}, "
          f"win_rate: {tr['win'].mean() * 100:.2f}%, "
          f"avg_ret: {tr['revenue_rate'].mean():+.2f}%, "
          f"total_ret_sum: {tr['revenue_rate'].sum():+.2f}%")

    # 일봉 + 지표 로드
    df = load_daily(TARGET)
    # 매수일 기준 상태를 feature로 붙이기
    feat_cols = ['RSI', 'prevRSI', 'Disparity20', 'Disparity11',
                 'prev_range_pct', 'gap_pct',
                 'ma20_before', 'ma60_before', 'ma120_before',
                 'prevChangeMa', 'is_jung']
    feat = df[feat_cols].copy()
    feat.index = pd.to_datetime(feat.index)

    # 매수일에 해당하는 지표값 join
    tr['buy_dt'] = pd.to_datetime(tr['buy_date'])
    joined = tr.merge(feat, left_on='buy_dt', right_index=True, how='left')
    joined.to_csv(OUT_DIR / f'analyze_{TARGET}_trades_joined.csv', index=False)

    # 매수일의 prevClose (= 매수 전날 종가) 직접 join
    pclose = df[['prevClose']].copy()
    pclose.columns = ['prev_close_at_buy']
    joined = joined.merge(pclose, left_on='buy_dt', right_index=True, how='left')
    joined['above_ma60'] = joined['prev_close_at_buy'] > joined['ma60_before']
    joined['above_ma20'] = joined['prev_close_at_buy'] > joined['ma20_before']

    # 승/패 그룹 통계
    print("\n[feature means: wins vs losses]")
    stat_cols = ['revenue_rate', 'RSI', 'prevRSI', 'Disparity20', 'Disparity11',
                 'prev_range_pct', 'gap_pct']
    agg = joined.groupby('win')[stat_cols].mean().T.round(2)
    agg.columns = ['LOSS_mean', 'WIN_mean']
    agg['diff'] = (agg['WIN_mean'] - agg['LOSS_mean']).round(2)
    print(agg.to_string())

    # 불리언 지표 분포
    print("\n[above_ma60 bucket]  (매수 전날 종가가 ma60 위에 있었나)")
    tmp = joined.groupby('above_ma60').agg(
        n=('revenue_rate', 'count'),
        wins=('win', 'sum'),
        avg_ret=('revenue_rate', 'mean'),
    )
    tmp['win_rate'] = tmp['wins'] / tmp['n'] * 100
    print(tmp.round(2).to_string())

    print("\n[is_jung bucket]  (완전 정배열 상태였나)")
    tmp = joined.groupby('is_jung').agg(
        n=('revenue_rate', 'count'),
        wins=('win', 'sum'),
        avg_ret=('revenue_rate', 'mean'),
    )
    tmp['win_rate'] = tmp['wins'] / tmp['n'] * 100
    print(tmp.round(2).to_string())

    # RSI 버킷
    print("\n[RSI bucket at buy day]")
    joined['RSI_bucket'] = pd.cut(
        joined['RSI'],
        bins=[0, 30, 45, 55, 70, 100],
        labels=['<30', '30-45', '45-55', '55-70', '>70'],
    )
    tmp = joined.groupby('RSI_bucket', observed=True).agg(
        n=('revenue_rate', 'count'),
        wins=('win', 'sum'),
        avg_ret=('revenue_rate', 'mean'),
    )
    tmp['win_rate'] = tmp['wins'] / tmp['n'] * 100
    print(tmp.round(2).to_string())

    print("\n[Disparity20 bucket]")
    joined['Disp20_bucket'] = pd.cut(
        joined['Disparity20'],
        bins=[0, 95, 98, 100, 102, 105, 200],
        labels=['<95', '95-98', '98-100', '100-102', '102-105', '>105'],
    )
    tmp = joined.groupby('Disp20_bucket', observed=True).agg(
        n=('revenue_rate', 'count'),
        wins=('win', 'sum'),
        avg_ret=('revenue_rate', 'mean'),
    )
    tmp['win_rate'] = tmp['wins'] / tmp['n'] * 100
    print(tmp.round(2).to_string())

    # 매도 수익률 상/하위 5건
    print("\n[최악 5건]")
    print(joined.nsmallest(5, 'revenue_rate')[
        ['date', 'buy_date', 'revenue_rate', 'RSI', 'Disparity20',
         'prev_range_pct', 'gap_pct', 'is_jung', 'above_ma60']
    ].to_string(index=False))
    print("\n[최고 5건]")
    print(joined.nlargest(5, 'revenue_rate')[
        ['date', 'buy_date', 'revenue_rate', 'RSI', 'Disparity20',
         'prev_range_pct', 'gap_pct', 'is_jung', 'above_ma60']
    ].to_string(index=False))

    # 요약 저장
    joined.to_csv(OUT_DIR / f'analyze_{TARGET}_trades_enriched.csv', index=False)
    print(f"\n[saved] {OUT_DIR / f'analyze_{TARGET}_trades_enriched.csv'}")


if __name__ == "__main__":
    main()
