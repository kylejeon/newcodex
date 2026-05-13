# -*- coding: utf-8 -*-

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path('/Users/yonghyuk/newcodex/MNQ_1m_25pct_backtest.py')
OUTPUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
OUTPUT_DIR.mkdir(exist_ok=True)

TICKS = 6
TIME_MODE = 'opening'
NY_TZ = 'America/New_York'


def load_module():
    spec = importlib.util.spec_from_file_location('mnq_bt_opening_analysis', MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Failed to load module: {MODULE_PATH}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def trades_to_df(trades):
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        row = dict(t.__dict__)
        row['entry_time'] = pd.to_datetime(row['entry_time'], utc=True)
        row['exit_time'] = pd.to_datetime(row['exit_time'], utc=True)
        rows.append(row)
    df = pd.DataFrame(rows)
    df['entry_et'] = df['entry_time'].dt.tz_convert(NY_TZ)
    df['exit_et'] = df['exit_time'].dt.tz_convert(NY_TZ)
    df['trade_date'] = df['exit_et'].dt.strftime('%Y-%m-%d')
    df['weekday'] = df['entry_et'].dt.day_name()
    df['entry_hhmm'] = df['entry_et'].dt.strftime('%H:%M')
    df['minutes_from_open'] = (df['entry_et'].dt.hour * 60 + df['entry_et'].dt.minute) - (9 * 60 + 30)
    return df


def opening_bucket(mins: int) -> str:
    if mins < 0:
        return 'pre_open'
    if mins < 30:
        return '00_30'
    if mins < 60:
        return '30_60'
    if mins < 90:
        return '60_90'
    if mins <= 120:
        return '90_120'
    return '120_plus'


def summarize_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[group_col, 'trades', 'wins', 'losses', 'win_rate', 'net_pnl', 'avg_trade_pnl'])
    out = df.groupby(group_col).agg(
        trades=('net_pnl', 'size'),
        wins=('net_pnl', lambda s: int((s > 0).sum())),
        losses=('net_pnl', lambda s: int((s <= 0).sum())),
        net_pnl=('net_pnl', 'sum'),
        avg_trade_pnl=('net_pnl', 'mean'),
    ).reset_index()
    out['win_rate'] = (out['wins'] / out['trades'] * 100.0).round(2)
    return out[[group_col, 'trades', 'wins', 'losses', 'win_rate', 'net_pnl', 'avg_trade_pnl']]


def summarize_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=['trade_date', 'trades', 'net_pnl'])
    return df.groupby('trade_date').agg(
        trades=('net_pnl', 'size'),
        net_pnl=('net_pnl', 'sum'),
    ).reset_index()


def main():
    mod = load_module()
    mod.MIN_TARGET_TICKS = TICKS
    mod.TIME_FILTER_MODE = TIME_MODE

    print(f'MNQ opening 요일/시간 분석 시작: ticks={TICKS}, time_mode={TIME_MODE}')
    base_df = mod.add_indicators(mod.load_mnq_1m())
    trades, eq_df = mod.run_backtest(base_df)
    stats = mod.summarize(trades, eq_df)
    trade_df = trades_to_df(trades)

    if trade_df.empty:
        print('거래가 없습니다.')
        return

    trade_df['opening_bucket'] = trade_df['minutes_from_open'].apply(opening_bucket)

    weekday_df = summarize_group(trade_df, 'weekday')
    bucket_df = summarize_group(trade_df, 'opening_bucket')
    hhmm_df = summarize_group(trade_df, 'entry_hhmm').sort_values(by='net_pnl', ascending=False)
    daily_df = summarize_daily(trade_df).sort_values(by='trade_date')

    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    weekday_df['weekday'] = pd.Categorical(weekday_df['weekday'], categories=weekday_order, ordered=True)
    weekday_df = weekday_df.sort_values('weekday')

    bucket_order = ['00_30', '30_60', '60_90', '90_120', '120_plus', 'pre_open']
    bucket_df['opening_bucket'] = pd.Categorical(bucket_df['opening_bucket'], categories=bucket_order, ordered=True)
    bucket_df = bucket_df.sort_values('opening_bucket')

    weekday_path = OUTPUT_DIR / 'mnq_opening_weekday_summary.csv'
    bucket_path = OUTPUT_DIR / 'mnq_opening_bucket_summary.csv'
    hhmm_path = OUTPUT_DIR / 'mnq_opening_entry_hhmm_summary.csv'
    daily_path = OUTPUT_DIR / 'mnq_opening_daily_detail.csv'

    weekday_df.to_csv(weekday_path, index=False)
    bucket_df.to_csv(bucket_path, index=False)
    hhmm_df.to_csv(hhmm_path, index=False)
    daily_df.to_csv(daily_path, index=False)

    print('\n================ STRATEGY SUMMARY ================')
    print(
        f"trades={stats['trades']}, win_rate={stats['win_rate']:.2f}%, return={stats['return_pct']:.2f}%, "
        f"pf={stats['profit_factor']:.2f}, mdd={stats['max_drawdown_pct']:.2f}%, avg_trade=${stats['avg_trade_pnl']:.2f}"
    )

    print('\n================ WEEKDAY SUMMARY ================')
    print('weekday\ttrades\twin_rate\tnet_pnl\tavg_trade')
    for _, r in weekday_df.iterrows():
        print(f"{r['weekday']}\t{int(r['trades'])}\t{r['win_rate']:.2f}\t{r['net_pnl']:.2f}\t{r['avg_trade_pnl']:.2f}")

    print('\n================ OPENING BUCKET SUMMARY ================')
    print('bucket\ttrades\twin_rate\tnet_pnl\tavg_trade')
    for _, r in bucket_df.iterrows():
        print(f"{r['opening_bucket']}\t{int(r['trades'])}\t{r['win_rate']:.2f}\t{r['net_pnl']:.2f}\t{r['avg_trade_pnl']:.2f}")

    print('\n================ BEST ENTRY HH:MM (TOP 15) ================')
    print('hhmm\ttrades\twin_rate\tnet_pnl\tavg_trade')
    for _, r in hhmm_df.head(15).iterrows():
        print(f"{r['entry_hhmm']}\t{int(r['trades'])}\t{r['win_rate']:.2f}\t{r['net_pnl']:.2f}\t{r['avg_trade_pnl']:.2f}")

    print('\n[저장 파일]')
    print(weekday_path)
    print(bucket_path)
    print(hhmm_path)
    print(daily_path)


if __name__ == '__main__':
    main()
