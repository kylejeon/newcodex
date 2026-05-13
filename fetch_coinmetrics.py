# -*- coding: utf-8 -*-
'''
Coin Metrics Community API v4로 BTC/ETH 일봉 온체인 지표 다운로드.
- 무료, API 키 불필요
- 페이지네이션 처리
- 커뮤니티 무료 티어 메트릭만 사용
'''
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")
OUT_DIR.mkdir(exist_ok=True)

BASE_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"

# 무료 커뮤니티 티어 확인된 메트릭만 사용 (403 체크 완료)
METRICS = [
    "PriceUSD",            # 종가 USD
    "CapMrktCurUSD",       # 시가총액
    "CapMVRVCur",          # MVRV 비율 (직접 제공!)
    "AdrActCnt",           # 활성 주소 수
    "TxCnt",               # 트랜잭션 수
    "SplyCur",             # 공급량
    "HashRate",            # 해시레이트 (BTC만, ETH는 merge 이후 없음)
]


def fetch_asset(asset: str, start: str, end: str, metrics=None) -> pd.DataFrame:
    if metrics is None:
        metrics = METRICS
    rows = []
    next_page = None
    session = requests.Session()
    while True:
        params = {
            "assets": asset,
            "metrics": ",".join(metrics),
            "frequency": "1d",
            "start_time": start,
            "end_time": end,
            "page_size": 10000,
        }
        if next_page:
            params["next_page_token"] = next_page
        r = session.get(BASE_URL, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        data = payload.get("data", [])
        rows.extend(data)
        next_page = payload.get("next_page_token")
        if not next_page:
            break
        time.sleep(0.2)
    if not rows:
        raise RuntimeError(f"empty response for {asset}")
    df = pd.DataFrame(rows)
    # 숫자 컬럼 변환
    for m in metrics:
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors="coerce")
    df["time"] = pd.to_datetime(df["time"])
    df.set_index("time", inplace=True)
    df.sort_index(inplace=True)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=pd.Timestamp.utcnow().strftime("%Y-%m-%d"))
    parser.add_argument("--assets", default="btc,eth")
    args = parser.parse_args()

    for asset in [a.strip() for a in args.assets.split(",") if a.strip()]:
        print(f"[fetch] {asset.upper()} {args.start} ~ {args.end}")
        # ETH는 HashRate 컬럼 못 받을 수도 있으니 안전하게 시도
        try:
            df = fetch_asset(asset, args.start, args.end)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (400, 404, 422):
                # 문제 메트릭 제거 후 재시도
                safer = [m for m in METRICS if m != "HashRate"]
                print(f"  retry without HashRate: {e}")
                df = fetch_asset(asset, args.start, args.end, metrics=safer)
            else:
                raise
        out_path = OUT_DIR / f"onchain_{asset}_daily.csv"
        df.to_csv(out_path)
        print(f"  rows={len(df):,} cols={list(df.columns)}")
        print(f"  head: {df.index[0].date()} ~ tail: {df.index[-1].date()}")
        print(f"  saved: {out_path}")


if __name__ == "__main__":
    main()
