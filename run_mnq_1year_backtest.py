# -*- coding: utf-8 -*-
'''
1년치 Databento MNQ 1분봉으로 기존 25% 되돌림 전략을 종합 백테스트.

- 기존 yfinance 30일 대비 ~12배 긴 기간
- 시간필터(off/regular/opening) × 틱필터(4/6/8) 매트릭스
- 개장 후 분 버킷(0-30, 30-60, 60-90, 90-120, 120-180)별 성과
- 요일별 성과
- 월별 / 연환산 수익 추정
'''
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path("/Users/yonghyuk/newcodex/MNQ_1m_25pct_backtest.py")
CSV_PATH = Path("/Users/yonghyuk/newcodex/mnq_backtest_output/mnq_1m_databento.csv")
OUT_DIR = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")


def load_module():
    spec = importlib.util.spec_from_file_location("mnq_bt", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_csv() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    df.dropna(inplace=True)
    df.sort_index(inplace=True)
    return df


def _rolling_mean_np(arr: np.ndarray, window: int) -> np.ndarray:
    # pandas 2.3 rolling은 대용량 float64에서 누적 오차로 NaN이 나옴.
    # cumsum 기반 수동 구현으로 우회.
    out = np.full(len(arr), np.nan, dtype=np.float64)
    cs = np.concatenate(([0.0], np.cumsum(arr, dtype=np.float64)))
    out[window - 1:] = (cs[window:] - cs[:-window]) / window
    return out


def _rolling_max_np(arr: np.ndarray, window: int) -> np.ndarray:
    # pandas strided window로 최대값 (큰 데이터 안전)
    out = np.full(len(arr), np.nan, dtype=np.float64)
    for i in range(window - 1, len(arr)):
        out[i] = arr[i - window + 1:i + 1].max()
    return out


def _rolling_min_np(arr: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(arr), np.nan, dtype=np.float64)
    for i in range(window - 1, len(arr)):
        out[i] = arr[i - window + 1:i + 1].min()
    return out


def add_indicators_np(df: pd.DataFrame, mod) -> pd.DataFrame:
    out = df.copy()
    out['ema22'] = out['close'].ewm(span=mod.EMA_LEN, adjust=False).mean()
    out['ema_slope'] = out['ema22'].diff()

    prev_close = out['close'].shift(1)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = _rolling_mean_np(tr.values, mod.ATR_LEN)

    # swing_high = high.rolling(N).max().shift(1); shift는 nan 앞당김
    sw_hi = _rolling_max_np(out['high'].values, mod.SWING_LOOKBACK)
    sw_lo = _rolling_min_np(out['low'].values, mod.SWING_LOOKBACK)
    # shift(1): 한 칸씩 미룸
    sw_hi_shift = np.concatenate(([np.nan], sw_hi[:-1]))
    sw_lo_shift = np.concatenate(([np.nan], sw_lo[:-1]))
    out['swing_high'] = sw_hi_shift
    out['swing_low'] = sw_lo_shift
    out['prev_high'] = out['high'].shift(1)
    out['prev_low'] = out['low'].shift(1)

    out['stretch_long'] = (out['ema22'] - out['low']) / out['atr']
    out['stretch_short'] = (out['high'] - out['ema22']) / out['atr']
    out['bull_reversal'] = out['close'] > out['prev_high']
    out['bear_reversal'] = out['close'] < out['prev_low']
    out.dropna(inplace=True)
    return out


def run_variant(mod, base_df, ticks: int, time_mode: str, min_open=None, max_open=None):
    mod.MIN_TARGET_TICKS = ticks
    mod.TIME_FILTER_MODE = time_mode
    mod.ENTRY_MIN_FROM_OPEN = min_open
    mod.ENTRY_MAX_FROM_OPEN = max_open
    trades, eq_df = mod.run_backtest(base_df)
    stats = mod.summarize(trades, eq_df)
    return trades, stats


def enrich_trades(trades: list, us_tz) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        entry_time = pd.Timestamp(t.entry_time)
        if entry_time.tzinfo is None:
            entry_time = entry_time.tz_localize('UTC')
        local = entry_time.tz_convert(us_tz)
        mins_from_open = (local.hour * 60 + local.minute) - (9 * 60 + 30)
        rows.append({
            'side': t.side,
            'entry_time_et': local,
            'weekday': local.strftime('%A'),
            'weekday_num': local.weekday(),
            'hour_et': local.hour,
            'mins_from_open': mins_from_open,
            'bars_held': t.bars_held,
            'reason': t.reason,
            'gross_pnl': t.gross_pnl,
            'net_pnl': t.net_pnl,
            'date_et': local.date(),
        })
    return pd.DataFrame(rows)


def opening_bucket(mins):
    if mins is None or mins < 0:
        return 'premarket_or_overnight'
    if mins < 30:
        return '00-30'
    if mins < 60:
        return '30-60'
    if mins < 90:
        return '60-90'
    if mins < 120:
        return '90-120'
    if mins < 180:
        return '120-180'
    if mins < 240:
        return '180-240'
    return '240+'


def summarize_group(df: pd.DataFrame, col: str, order=None):
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(col).agg(
        trades=('net_pnl', 'count'),
        wins=('net_pnl', lambda s: int((s > 0).sum())),
        losses=('net_pnl', lambda s: int((s <= 0).sum())),
        net_pnl=('net_pnl', 'sum'),
        avg_pnl=('net_pnl', 'mean'),
    )
    g['win_rate'] = (g['wins'] / g['trades'] * 100).round(2)
    g = g[['trades', 'wins', 'losses', 'win_rate', 'net_pnl', 'avg_pnl']]
    if order is not None:
        g = g.reindex([o for o in order if o in g.index])
    return g.round(2)


def main():
    print(f"[load] {CSV_PATH}")
    base = load_csv()
    print(f"[load] rows={len(base):,}  {base.index[0]} ~ {base.index[-1]}")
    elapsed_days = (base.index[-1] - base.index[0]).total_seconds() / 86400.0
    print(f"[load] span_days={elapsed_days:.1f}")

    mod = load_module()
    base_df = add_indicators_np(base, mod)
    print(f"[indicators] rows={len(base_df):,}")

    print("\n================ VARIANT GRID ================")
    rows = []
    # time_mode × ticks
    for time_mode in ("off", "regular", "opening"):
        for ticks in (4, 6, 8):
            _, stats = run_variant(mod, base_df, ticks=ticks, time_mode=time_mode)
            rows.append({
                'label': f'ticks_{ticks}__{time_mode}',
                'ticks': ticks,
                'time_mode': time_mode,
                **stats,
            })
    # opening window variants (mirror best_90_120 strategy)
    opening_windows = [
        ('core_0_120', 0, 120),
        ('late_60_120', 60, 120),
        ('core_30_90', 30, 90),
        ('best_90_120', 90, 120),
        ('extended_90_180', 90, 180),
        ('extended_90_240', 90, 240),
        ('exclude_0_30_30_120', 30, 120),
    ]
    for label, lo, hi in opening_windows:
        mod.TIME_FILTER_MODE = 'off'  # turn off regular-hour flag; rely on min/max from open
        _, stats = run_variant(mod, base_df, ticks=6, time_mode='off', min_open=lo, max_open=hi)
        rows.append({
            'label': label,
            'ticks': 6,
            'time_mode': f'opening_{lo}_{hi}',
            **stats,
        })

    grid = pd.DataFrame(rows)
    grid = grid.sort_values('net_pnl', ascending=False).reset_index(drop=True)
    grid_path = OUT_DIR / "mnq_1year_variant_grid.csv"
    grid.to_csv(grid_path, index=False)
    print(grid.to_string(index=False))
    print(f"[save] {grid_path}")

    # 심층 분석 용 best_90_120 재실행
    print("\n================ DEEP DIVE: best_90_120 ================")
    mod.MIN_TARGET_TICKS = 6
    mod.TIME_FILTER_MODE = 'off'
    mod.ENTRY_MIN_FROM_OPEN = 90
    mod.ENTRY_MAX_FROM_OPEN = 120
    trades, eq_df = mod.run_backtest(base_df)
    stats = mod.summarize(trades, eq_df)
    print(f"trades={stats['trades']}  win_rate={stats['win_rate']:.2f}%  net=${stats['net_pnl']:.2f}  "
          f"return={stats['return_pct']:.2f}%  pf={stats['profit_factor']:.2f}  mdd={stats['max_drawdown_pct']:.2f}%")

    td = enrich_trades(trades, mod.US_TZ)
    if td.empty:
        print("No trades in best_90_120 window.")
        return

    print(f"\n[side]")
    side_df = summarize_group(td, 'side')
    print(side_df.to_string())
    side_df.to_csv(OUT_DIR / "mnq_1year_best90120_by_side.csv")

    td['opening_bucket'] = td['mins_from_open'].apply(opening_bucket)
    print(f"\n[opening_bucket]")
    bucket_df = summarize_group(td, 'opening_bucket',
                                 order=['premarket_or_overnight', '00-30', '30-60', '60-90',
                                        '90-120', '120-180', '180-240', '240+'])
    print(bucket_df.to_string())

    print(f"\n[weekday]")
    weekday_df = summarize_group(td, 'weekday',
                                  order=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
    print(weekday_df.to_string())
    weekday_df.to_csv(OUT_DIR / "mnq_1year_best90120_by_weekday.csv")

    print(f"\n[hour_et]")
    hour_df = summarize_group(td, 'hour_et', order=list(range(0, 24)))
    print(hour_df.to_string())

    print(f"\n[reason]")
    reason_df = summarize_group(td, 'reason')
    print(reason_df.to_string())

    # 월별/연환산
    td['year_month'] = pd.to_datetime(td['entry_time_et']).dt.to_period('M').astype(str)
    monthly = summarize_group(td, 'year_month')
    print(f"\n[monthly]")
    print(monthly.to_string())
    monthly.to_csv(OUT_DIR / "mnq_1year_best90120_monthly.csv")

    # 전체 기간 모든 거래 CSV
    all_trades_path = OUT_DIR / "mnq_1year_best90120_trades.csv"
    td.to_csv(all_trades_path, index=False)
    print(f"\n[save] {all_trades_path}")

    # 연환산 지표
    active_months = max(1, len(monthly))
    annualized_return_pct = stats['return_pct'] * (12.0 / active_months)
    print(f"\n================ ANNUALIZED ================")
    print(f"capital: $10,000 | actual span: {elapsed_days:.0f} days / {active_months} months")
    print(f"net_pnl: ${stats['net_pnl']:.2f}   return: {stats['return_pct']:.2f}%   "
          f"annualized≈ {annualized_return_pct:.2f}%")
    print(f"max_drawdown: {stats['max_drawdown_pct']:.2f}%   profit_factor: {stats['profit_factor']:.2f}")
    print(f"trades: {stats['trades']} ({stats['trades']/elapsed_days*30:.1f}/month)")


if __name__ == "__main__":
    main()
