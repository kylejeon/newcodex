# -*- coding: utf-8 -*-

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path('/Users/yonghyuk/newcodex/MNQ_1m_25pct_backtest.py')
OUTPUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
OUTPUT_DIR.mkdir(exist_ok=True)


def load_module():
    spec = importlib.util.spec_from_file_location('mnq_bt_window', MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Failed to load module: {MODULE_PATH}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_variant(mod, base_df: pd.DataFrame, label: str, min_tick: int, min_from_open, max_from_open):
    mod.MIN_TARGET_TICKS = min_tick
    mod.TIME_FILTER_MODE = 'opening'
    mod.ENTRY_MIN_FROM_OPEN = min_from_open
    mod.ENTRY_MAX_FROM_OPEN = max_from_open
    trades, eq_df = mod.run_backtest(base_df)
    stats = mod.summarize(trades, eq_df)
    return {
        'label': label,
        'ticks': min_tick,
        'min_from_open': min_from_open,
        'max_from_open': max_from_open,
        **stats,
    }


def score(row):
    return row['return_pct'] - abs(row['max_drawdown_pct']) * 0.35 + max(row['profit_factor'] - 1.0, -1.0) * 10.0


def main():
    mod = load_module()
    base_df = mod.add_indicators(mod.load_mnq_1m())

    variants = [
        ('opening_all_0_120', 6, 0, 120),
        ('exclude_0_30__30_120', 6, 30, 120),
        ('core_30_90', 6, 30, 90),
        ('late_60_120', 6, 60, 120),
        ('best_90_120', 6, 90, 120),
    ]

    rows = []
    print('MNQ opening 구간 비교 시작')
    print(f'bars: {len(base_df):,}')
    for label, ticks, min_from_open, max_from_open in variants:
        print(f'[RUN] {label} | ticks={ticks} | mins={min_from_open}~{max_from_open}')
        row = run_variant(mod, base_df, label, ticks, min_from_open, max_from_open)
        row['score'] = score(row)
        rows.append(row)

    result_df = pd.DataFrame(rows).sort_values(
        by=['score', 'profit_factor', 'return_pct'],
        ascending=False,
    )
    out_csv = OUTPUT_DIR / 'mnq_opening_window_compare.csv'
    result_df.to_csv(out_csv, index=False)

    print('\n================ WINDOW SUMMARY ================')
    print('label\tscore\ttrades\twin_rate\treturn\tpf\tmdd\tavg_trade')
    for _, r in result_df.iterrows():
        print(
            f"{r['label']}\t{r['score']:.2f}\t{int(r['trades'])}\t{r['win_rate']:.2f}\t"
            f"{r['return_pct']:.2f}\t{r['profit_factor']:.2f}\t{r['max_drawdown_pct']:.2f}\t{r['avg_trade_pnl']:.2f}"
        )

    best = result_df.iloc[0]
    print('\nBest window candidate:')
    print(
        f"{best['label']} | trades={int(best['trades'])}, win_rate={best['win_rate']:.2f}%, "
        f"return={best['return_pct']:.2f}%, pf={best['profit_factor']:.2f}, "
        f"mdd={best['max_drawdown_pct']:.2f}%, avg_trade=${best['avg_trade_pnl']:.2f}"
    )
    print(f'\nCSV saved: {out_csv}')


if __name__ == '__main__':
    main()
