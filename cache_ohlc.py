#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily OHLC cache — 봇/백테 데이터 source 통일 인프라.

매일 18:00 cron 으로 실행. 장 마감 후 안정화된 OHLC 를 캐시에 저장.
다음날 봇과 백테 모두 같은 캐시를 사용 → trade 분기 원인 제거.

Phase 1 (현재): 캐시만 쌓음. 봇/백테 코드는 안 건드림.
Phase 2 (다음): 봇/백테가 ohlc_cache_loader 로 캐시 우선 사용.

사용:
    python cache_ohlc.py
"""
from __future__ import annotations
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import KIS_Common as Common  # noqa: E402

CACHE_DIR = ROOT / 'autobot_data' / 'ohlc_cache'

# v7_best + V_FINAL 대상 종목 (필요 시 확장)
STOCKS_KR = ["122630", "252670", "233740", "251340"]

# fetch 양 (5년 이상 — 백테 시뮬레이션도 가능하도록)
FETCH_LIMIT = 2200


def cache_one(stock_code: str) -> bool:
    """단일 종목 OHLC fetch + CSV 저장. 성공 시 True."""
    try:
        df = Common.GetOhlcv("KR", stock_code, FETCH_LIMIT)
        if df is None or len(df) == 0:
            print(f"  ! {stock_code}: empty data, skip")
            return False
        path = CACHE_DIR / f'KR_{stock_code}.csv'
        df.to_csv(path)
        print(f"  ✓ {stock_code}: {len(df):4d} rows  last={df.index[-1].date()}  → {path.name}")
        return True
    except Exception as e:
        print(f"  ! {stock_code}: error {e}")
        return False


def main():
    Common.SetChangeMode("REAL")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{datetime.now().isoformat(timespec='seconds')}] OHLC cache 시작 → {CACHE_DIR}")
    ok, fail = 0, 0
    for code in STOCKS_KR:
        if cache_one(code):
            ok += 1
        else:
            fail += 1
        time.sleep(0.5)  # KIS API rate limit 여유
    print(f"[{datetime.now().isoformat(timespec='seconds')}] 완료. OK={ok} FAIL={fail}")
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
