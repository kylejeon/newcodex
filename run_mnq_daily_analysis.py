# -*- coding: utf-8 -*-

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path('/Users/yonghyuk/newcodex/MNQ_1m_25pct_backtest.py')
OUTPUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
OUTPUT_DIR.mkdir(exist_ok=True)

OPENING_VARIANTS = [
    (4, 'opening'),
    (6, 'opening'),
    (8, 'opening'),
]


def load_module():
    spec = importlib.util.spec_from_file_location('mnq_bt_daily', MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Failed to load module: {MODULE_PATH}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def trades_to_df(trades):
    if not trades:
        return pd.DataFrame(columns=['entry_time', 'exit_time', 'net_pnl', 'gross_pnl'])
    rows = []
    for t in trades:
        row = dict(t.__dict__)
        row['entry_time'] = pd.to_datetime(row['entry_time'], utc=True)
        row['exit_time'] = pd.to_datetime(row['exit_time'], utc=True)
        rows.append(row)
    return pd.DataFrame(rows)


def build_daily_table(trade_df: pd.DataFrame) -> pd.DataFrame:
    if trade_df.empty:
        return pd.DataFrame(columns=['date', 'trades', 'wins', 'losses', 'win_rate', 'gross_pnl', 'net_pnl', 'avg_trade_pnl'])

    local_exit = trade_df['exit_time'].dt.tz_convert('America/New_York')
    daily = trade_df.assign(trade_date=local_exit.dt.strftime('%Y-%m-%d')).groupby('trade_date').agg(
        trades=('net_pnl', 'size'),
        wins=('net_pnl', lambda s: int((s > 0).sum())),
        losses=('net_pnl', lambda s: int((s <= 0).sum())),
        gross_pnl=('gross_pnl', 'sum'),
        net_pnl=('net_pnl', 'sum'),
        avg_trade_pnl=('net_pnl', 'mean'),
    ).reset_index().rename(columns={'trade_date': 'date'})
    daily['win_rate'] = (daily['wins'] / daily['trades'] * 100.0).round(2)
    return daily[['date', 'trades', 'wins', 'losses', 'win_rate', 'gross_pnl', 'net_pnl', 'avg_trade_pnl']]


def summarize_daily(daily_df: pd.DataFrame) -> dict:
    if daily_df.empty:
        return {
            'days': 0,
            'green_days': 0,
            'red_days': 0,
            'green_rate': 0.0,
            'best_day': 0.0,
            'worst_day': 0.0,
            'avg_day': 0.0,
            'median_day': 0.0,
        }
    green = int((daily_df['net_pnl'] > 0).sum())
    red = int((daily_df['net_pnl'] <= 0).sum())
    return {
        'days': int(len(daily_df)),
        'green_days': green,
        'red_days': red,
        'green_rate': float(green / len(daily_df) * 100.0),
        'best_day': float(daily_df['net_pnl'].max()),
        'worst_day': float(daily_df['net_pnl'].min()),
        'avg_day': float(daily_df['net_pnl'].mean()),
        'median_day': float(daily_df['net_pnl'].median()),
    }


def run_variant(mod, base_df: pd.DataFrame, ticks: int, time_mode: str):
    mod.MIN_TARGET_TICKS = ticks
    mod.TIME_FILTER_MODE = time_mode
    trades, eq_df = mod.run_backtest(base_df)
    stats = mod.summarize(trades, eq_df)
    trade_df = trades_to_df(trades)
    daily_df = build_daily_table(trade_df)
    daily_stats = summarize_daily(daily_df)
    label = f'ticks_{ticks}__{time_mode}'
    daily_path = OUTPUT_DIR / f'{label}_daily.csv'
    daily_df.to_csv(daily_path, index=False)
    return {
        'label': label,
        'ticks': ticks,
        'time_mode': time_mode,
        **stats,
        **daily_stats,
        'daily_csv': str(daily_path),
    }, daily_df


def score(row):
    return row['return_pct'] - abs(row['max_drawdown_pct']) * 0.30 + (row['profit_factor'] - 1.0) * 12.0 + row['green_rate'] * 0.05


def main():
    mod = load_module()
    base_df = mod.add_indicators(mod.load_mnq_1m())

    rows = []
    daily_tables = {}

    print('MNQ opening 후보 하루별 성과 분석 시작')
    print(f'bars: {len(base_df):,}')

    for ticks, time_mode in OPENING_VARIANTS:
        print(f'[RUN] ticks={ticks}, time_mode={time_mode}')
        row, daily_df = run_variant(mod, base_df, ticks, time_mode)
        row['score'] = score(row)
        rows.append(row)
        daily_tables[row['label']] = daily_df

    result_df = pd.DataFrame(rows).sort_values(
        by=['score', 'profit_factor', 'return_pct', 'green_rate'],
        ascending=False,
    )

    summary_path = OUTPUT_DIR / 'mnq_opening_daily_summary.csv'
    result_df.to_csv(summary_path, index=False)

    print('\n================ DAILY SUMMARY ================')
    print('label\tscore\tdays\tgreen_rate\tbest_day\tworst_day\tavg_day\treturn\tpf\tmdd')
    for _, r in result_df.iterrows():
        print(
            f"{r['label']}\t{r['score']:.2f}\t{int(r['days'])}\t{r['green_rate']:.2f}\t"
            f"{r['best_day']:.2f}\t{r['worst_day']:.2f}\t{r['avg_day']:.2f}\t"
            f"{r['return_pct']:.2f}\t{r['profit_factor']:.2f}\t{r['max_drawdown_pct']:.2f}"
        )

    best = result_df.iloc[0]
    print('\nBest daily profile:')
    print(
        f"{best['label']} | days={int(best['days'])}, green_rate={best['green_rate']:.2f}%, "
        f"best_day=${best['best_day']:.2f}, worst_day=${best['worst_day']:.2f}, "
        f"avg_day=${best['avg_day']:.2f}, return={best['return_pct']:.2f}%, "
        f"pf={best['profit_factor']:.2f}, mdd={best['max_drawdown_pct']:.2f}%"
    )
    print(f'\nSummary CSV saved: {summary_path}')
    for label, daily_df in daily_tables.items():
        print(f'{label} daily rows: {len(daily_df)}')


if __name__ == '__main__':
    main()
