# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pandas as pd

TRADE_LOG_FILE = Path('/Users/yonghyuk/newcodex/autobot_data/MNQ_1m_best_90_120_trades.jsonl')
OUTPUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_CSV = OUTPUT_DIR / 'mnq_paper_daily_report.csv'


def load_logs() -> pd.DataFrame:
    if not TRADE_LOG_FILE.exists():
        return pd.DataFrame()
    rows = []
    with open(TRADE_LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['date_kst'] = df['timestamp'].dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d')
    return df


def main():
    df = load_logs()
    if df.empty:
        print('거래 로그가 없습니다.')
        return

    exits = df[df['type'] == 'EXIT'].copy()
    if exits.empty:
        print('청산 로그가 없습니다.')
        return

    exits['net_pnl'] = exits['net_pnl'].astype(float)
    daily = exits.groupby('date_kst').agg(
        trades=('net_pnl', 'size'),
        wins=('net_pnl', lambda s: int((s > 0).sum())),
        losses=('net_pnl', lambda s: int((s <= 0).sum())),
        net_pnl=('net_pnl', 'sum'),
        avg_trade_pnl=('net_pnl', 'mean'),
    ).reset_index().rename(columns={'date_kst': 'date'})
    daily['win_rate'] = (daily['wins'] / daily['trades'] * 100.0).round(2)
    daily = daily[['date', 'trades', 'wins', 'losses', 'win_rate', 'net_pnl', 'avg_trade_pnl']]
    daily.to_csv(OUTPUT_CSV, index=False)

    total_trades = int(daily['trades'].sum())
    green_days = int((daily['net_pnl'] > 0).sum())
    red_days = int((daily['net_pnl'] <= 0).sum())

    print('================ MNQ PAPER DAILY REPORT ================')
    print(f'days: {len(daily)}')
    print(f'total_trades: {total_trades}')
    print(f'green_days/red_days: {green_days}/{red_days}')
    print(f'total_net_pnl: ${daily["net_pnl"].sum():,.2f}')
    print(f'avg_day_pnl: ${daily["net_pnl"].mean():,.2f}')
    print(f'best_day: ${daily["net_pnl"].max():,.2f}')
    print(f'worst_day: ${daily["net_pnl"].min():,.2f}')
    print('\n[최근 일별 성과]')
    print(daily.tail(10).to_string(index=False))
    print(f'\nCSV saved: {OUTPUT_CSV}')


if __name__ == '__main__':
    main()
