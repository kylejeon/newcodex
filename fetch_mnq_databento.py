# -*- coding: utf-8 -*-
'''
Databento로 MNQ 1분봉 OHLCV를 받아와서 백테스트용 CSV로 저장.

사용법:
    export DATABENTO_API_KEY="db-..."
    python3 fetch_mnq_databento.py --days 365

비용 최소화를 위해 schema=ohlcv-1m 사용 (trades/mbo 대비 압도적으로 저렴).
연속물 심볼 MNQ.c.0 사용 (front month calendar roll).
'''
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import databento as db
import pandas as pd

OUTPUT_DIR = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")
OUTPUT_DIR.mkdir(exist_ok=True)
DATASET = "GLBX.MDP3"           # CME Globex MDP 3.0
SYMBOL = "MNQ.c.0"              # 연속물(front month)
SCHEMA = "ohlcv-1m"             # 1분봉 OHLCV


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365, help="소급할 일수")
    parser.add_argument("--dry-run", action="store_true", help="비용만 추정하고 종료")
    parser.add_argument("--output", type=str, default=str(OUTPUT_DIR / "mnq_1m_databento.csv"))
    args = parser.parse_args()

    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        key_file = Path(__file__).parent / ".databento_key"
        if key_file.exists():
            api_key = key_file.read_text().strip()
    if not api_key:
        print("ERROR: DATABENTO_API_KEY 환경변수 또는 .databento_key 파일을 설정하세요.", file=sys.stderr)
        sys.exit(1)

    # 무료 라이선스는 실시간 제공 안 됨. 24시간 지연 창으로 설정.
    end = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    # databento는 UTC ISO8601을 권장. 문자열로 전달.
    start_iso = start.strftime("%Y-%m-%dT%H:%M")
    end_iso = end.strftime("%Y-%m-%dT%H:%M")

    client = db.Historical(api_key)

    # 1) 비용 추정
    print(f"[cost] dataset={DATASET} symbol={SYMBOL} schema={SCHEMA}")
    print(f"[cost] range={start_iso} ~ {end_iso}")
    try:
        cost = client.metadata.get_cost(
            dataset=DATASET,
            symbols=[SYMBOL],
            schema=SCHEMA,
            stype_in="continuous",
            start=start_iso,
            end=end_iso,
        )
        print(f"[cost] estimated: ${cost:.4f}")
    except Exception as e:
        print(f"[cost] 추정 실패: {e}")
        cost = None

    if args.dry_run:
        print("[dry-run] 종료")
        return

    # 2) 데이터 요청
    print(f"[fetch] 시작: {datetime.now().isoformat()}")
    data = client.timeseries.get_range(
        dataset=DATASET,
        symbols=[SYMBOL],
        schema=SCHEMA,
        stype_in="continuous",
        start=start_iso,
        end=end_iso,
    )
    print(f"[fetch] 완료: {datetime.now().isoformat()}")

    # 3) DataFrame 변환
    df = data.to_df()
    print(f"[data] rows={len(df):,} columns={list(df.columns)}")
    if len(df) == 0:
        print("ERROR: 데이터 0건. 심볼/기간을 확인하세요.", file=sys.stderr)
        sys.exit(2)

    # 표준 컬럼으로 정리 (backtest와 호환)
    # databento OHLCV-1m: ts_event(index), open, high, low, close, volume, symbol
    if df.index.name in (None, "ts_event"):
        df.index.name = "ts"
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    out = df[keep].copy()
    # 가격 스케일링 (databento는 보통 1e-9 나노달러 단위지만 to_df()가 자동 스케일)
    # 확인: to_df()는 이미 price_type='standard' 로 되어 있어 실가격 반환

    out.to_csv(args.output)
    print(f"[save] {args.output}")
    print(f"[summary] first={out.index[0]} last={out.index[-1]}")
    print(out.head(3))
    print(out.tail(3))


if __name__ == "__main__":
    main()
