# -*- coding: utf-8 -*-
"""
일일 OHLCV + 외인 incremental fetch.

- kosdaq_cache/<ticker>.csv: pykrx 로 last_date 이후만 fetch
- kosdaq_investor_cache/<ticker>.csv: Naver finance page 1 만 fetch (최근 20일치)

Usage:
  python3 fetch_daily_update.py [--mode ohlcv|investor|all] [--full]

  --mode: 갱신 대상 (default: all)
  --full: 전체 universe (1208) — default. 옵션 안 줘도 전체.

Cron 권장:
  매일 15:40 (장 마감 10분 후)
  → 15:35 signal_bot/exit_monitor 보다 빠르면 데이터 미반영. 그래서 15:40
  → 또는 16:00 두고 signal_bot/exit_monitor 는 16:30 로 미루기

여기서는 단순화를 위해 매일 16:00 fetch, 16:30 봇 실행 권장.
"""
from __future__ import annotations
import argparse
import io
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    from pykrx import stock as krx
except ImportError:
    sys.exit("pykrx required: pip install pykrx")

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / 'kosdaq_cache'
INVESTOR_DIR = ROOT / 'kosdaq_investor_cache'
UNIVERSE_CSV = CACHE_DIR / 'universe.csv'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
INVESTOR_DIR.mkdir(parents=True, exist_ok=True)


def fetch_ohlcv_incremental(ticker, today_yyyymmdd):
    """Append today's OHLCV to existing cache. Returns ('updated', n) or ('skip', 0)."""
    cache = CACHE_DIR / f'{ticker}.csv'
    if not cache.exists():
        return 'no_cache', 0
    try:
        df = pd.read_csv(cache, index_col=0, parse_dates=[0])
    except Exception:
        return 'error', 0
    if len(df) == 0:
        return 'empty_cache', 0
    last_date = df.index[-1]
    start_dt = (last_date + pd.Timedelta(days=1))
    end_dt = pd.Timestamp(today_yyyymmdd)
    if start_dt > end_dt:
        return 'uptodate', 0
    try:
        new_df = krx.get_market_ohlcv(start_dt.strftime('%Y%m%d'),
                                        end_dt.strftime('%Y%m%d'), ticker)
        if new_df is None or len(new_df) == 0:
            return 'no_new_data', 0
        new_df = new_df.rename(columns={'시가':'Open','고가':'High','저가':'Low',
                                          '종가':'Close','거래량':'Volume'})
        new_df = new_df[['Open','High','Low','Close','Volume']]
        new_df.index.name = 'Date'
        combined = pd.concat([df, new_df])
        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
        combined.to_csv(cache)
        return 'updated', len(new_df)
    except Exception as e:
        return f'error: {e}', 0


def fetch_investor_incremental(ticker):
    """Fetch Naver finance page 1 (recent ~20 days) and merge."""
    cache = INVESTOR_DIR / f'{ticker}.csv'
    url = f'https://finance.naver.com/item/frgn.naver?code={ticker}&page=1'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = urllib.request.urlopen(req, timeout=15).read()
        text = data.decode('euc-kr', errors='ignore')
        tables = pd.read_html(io.StringIO(text))
    except Exception:
        return 'error', 0
    target = None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if len(t) > 5 and any('기관' in c and '순매매' in c for c in cols):
            target = t; break
        if len(t) > 5 and any('순매매' in c for c in cols) and any('외국인' in c for c in cols):
            target = t; break
    if target is None or len(target) < 2:
        return 'no_table', 0
    target.columns = ['_'.join(map(str, c)).strip() for c in target.columns]
    date_col = next((c for c in target.columns if c.startswith('날짜')), None)
    close_col = next((c for c in target.columns if c.startswith('종가')), None)
    inst_col = next((c for c in target.columns if '기관' in c and '순매매' in c), None)
    foreign_col = next((c for c in target.columns if '외국인' in c and '순매매' in c), None)
    foreign_hold_col = next((c for c in target.columns if '외국인' in c and '보유주수' in c), None)
    if not (date_col and inst_col and foreign_col):
        return 'no_cols', 0
    sub = target[[date_col, close_col, inst_col, foreign_col, foreign_hold_col]].copy()
    sub.columns = ['Date', 'Close', 'Inst_Net', 'Foreign_Net', 'Foreign_Hold']
    sub = sub.dropna(subset=['Date'])
    sub = sub[sub['Date'].astype(str).str.match(r'\d{4}\.\d{2}\.\d{2}')]
    sub['Date'] = pd.to_datetime(sub['Date'], format='%Y.%m.%d', errors='coerce')
    sub = sub.dropna(subset=['Date']).set_index('Date')
    for col in ['Close', 'Inst_Net', 'Foreign_Net', 'Foreign_Hold']:
        sub[col] = pd.to_numeric(sub[col].astype(str).str.replace(',', '').str.replace('--', '0'),
                                  errors='coerce').fillna(0)
    if cache.exists():
        try:
            existing = pd.read_csv(cache, index_col=0, parse_dates=[0])
            combined = pd.concat([existing, sub])
            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
            n_new = len(combined) - len(existing)
            combined.to_csv(cache)
            return 'updated', n_new
        except Exception:
            sub.to_csv(cache)
            return 'rebuilt', len(sub)
    else:
        sub.to_csv(cache)
        return 'new', len(sub)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['ohlcv', 'investor', 'all'], default='all')
    args = parser.parse_args()

    if not UNIVERSE_CSV.exists():
        sys.exit(f"Universe CSV not found: {UNIVERSE_CSV}")

    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    tickers = udf['ticker'].astype(str).tolist()
    today = datetime.now().strftime('%Y%m%d')

    print(f"="*70)
    print(f"Daily update — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {args.mode}, Universe: {len(tickers)} tickers")
    print(f"="*70)

    # OHLCV
    if args.mode in ('ohlcv', 'all'):
        print(f"\n[OHLCV] target: {today}")
        t_start = time.time()
        stats = {'updated': 0, 'uptodate': 0, 'no_cache': 0,
                 'no_new_data': 0, 'error': 0, 'empty_cache': 0}
        for i, ticker in enumerate(tickers, 1):
            status, n = fetch_ohlcv_incremental(ticker, today)
            if status in stats:
                stats[status] += 1
            elif status.startswith('error'):
                stats['error'] += 1
            if i % 100 == 0:
                elapsed = time.time() - t_start
                print(f"  [{i:4d}/{len(tickers)}] updated={stats['updated']} "
                      f"uptodate={stats['uptodate']} err={stats['error']} "
                      f"| {elapsed/60:.1f}min", flush=True)
            time.sleep(0.1)  # rate limit
        elapsed = time.time() - t_start
        print(f"\n[OHLCV done] {elapsed/60:.1f}min")
        print(f"  {stats}")

    # Investor
    if args.mode in ('investor', 'all'):
        print(f"\n[Investor] Naver page 1 (recent ~20d)")
        t_start = time.time()
        stats = {'updated': 0, 'rebuilt': 0, 'new': 0,
                 'error': 0, 'no_table': 0, 'no_cols': 0}
        for i, ticker in enumerate(tickers, 1):
            status, n = fetch_investor_incremental(ticker)
            if status in stats:
                stats[status] += 1
            if i % 100 == 0:
                elapsed = time.time() - t_start
                print(f"  [{i:4d}/{len(tickers)}] updated={stats['updated']} "
                      f"err={stats['error']} no_table={stats['no_table']} "
                      f"| {elapsed/60:.1f}min", flush=True)
            time.sleep(0.5)  # Naver rate limit
        elapsed = time.time() - t_start
        print(f"\n[Investor done] {elapsed/60:.1f}min")
        print(f"  {stats}")

    print(f"\n[Total done] {datetime.now().strftime('%H:%M:%S')}")


if __name__ == '__main__':
    main()
