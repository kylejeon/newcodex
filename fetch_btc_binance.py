# -*- coding: utf-8 -*-
'''
Binance 공개 API로 BTCUSDT 1분봉 다운로드.
- API 키 불필요 (공개 엔드포인트)
- klines endpoint, 1회 max 1000캔들
- 1년치 ≈ 525,600캔들 → 약 526회 요청
- weight=1/call, rate limit 1200/min이라 여유 있음
'''
from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

OUTPUT = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")  # 경로 재사용(리네임 안 함)
OUTPUT.mkdir(exist_ok=True)

URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
LIMIT = 1000  # 한 번에 받을 수 있는 최대
SLEEP = 0.15  # 안전 여유


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_chunk(session: requests.Session, start_ms: int, end_ms: int):
    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": LIMIT,
    }
    r = session.get(URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def iterate_klines(start: datetime, end: datetime) -> Iterable[list]:
    session = requests.Session()
    cursor = ms(start)
    end_ms = ms(end)
    total = 0
    last_log = time.time()
    while cursor < end_ms:
        data = fetch_chunk(session, cursor, end_ms)
        if not data:
            break
        for row in data:
            yield row
        total += len(data)
        cursor = data[-1][0] + 60_000  # 다음 분
        if time.time() - last_log > 3:
            print(f"  progress: {total:,} rows, cursor={datetime.fromtimestamp(cursor/1000, tz=timezone.utc)}")
            last_log = time.time()
        time.sleep(SLEEP)
    print(f"  done: {total:,} rows")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--output", type=str, default=str(OUTPUT / "btc_1m_binance.csv"))
    args = parser.parse_args()

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    print(f"[fetch] {SYMBOL} {INTERVAL}  {start} ~ {end}")

    out_path = Path(args.output)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for row in iterate_klines(start, end):
            # binance klines: [openTime, o, h, l, c, v, closeTime, ...]
            open_time_ms = int(row[0])
            ts = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).isoformat()
            w.writerow([ts, row[1], row[2], row[3], row[4], row[5]])
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"[save] {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
