# -*- coding: utf-8 -*-
"""캐시 우선 OHLC 로더 — 봇/백테 공통 사용.

cache_ohlc.py 가 만든 캐시를 우선 읽고, 없으면 None 반환.
호출자가 None 시 KIS_Common.GetOhlcv() fallback.

Phase 2 마이그레이션 시 봇/백테에서:
    df = load_cached_ohlc("KR", stock_code, limit) or Common.GetOhlcv("KR", stock_code, limit)

이렇게 한 줄 wrap 으로 캐시 우선 + 폴백 안전.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / 'autobot_data' / 'ohlc_cache'


def load_cached_ohlc(area: str, stock_code: str, limit: int = 500) -> Optional[pd.DataFrame]:
    """캐시에서 OHLC 로드. 없거나 실패 시 None.

    Args:
        area: "KR" 만 지원 (현재). US 는 추후.
        stock_code: 종목 코드.
        limit: 반환할 최근 행 수.

    Returns:
        DataFrame (datetime index, OHLC + 추가 컬럼) 또는 None.
    """
    if area != "KR":
        return None
    path = CACHE_DIR / f'KR_{stock_code}.csv'
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df is None or len(df) == 0:
            return None
        return df.iloc[-limit:].copy()
    except Exception as e:
        print(f"[cache_loader] {stock_code} load fail: {e}")
        return None


def cache_status() -> dict:
    """캐시 상태 진단용 — 종목별 마지막 데이터 날짜 반환."""
    if not CACHE_DIR.exists():
        return {'cache_dir': str(CACHE_DIR), 'exists': False, 'files': []}
    files = sorted(CACHE_DIR.glob('KR_*.csv'))
    out = []
    for p in files:
        try:
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            out.append({
                'code': p.stem.replace('KR_', ''),
                'rows': len(df),
                'last_date': str(df.index[-1].date()) if len(df) else None,
            })
        except Exception as e:
            out.append({'code': p.stem, 'error': str(e)})
    return {'cache_dir': str(CACHE_DIR), 'exists': True, 'files': out}


if __name__ == '__main__':
    import json
    print(json.dumps(cache_status(), indent=2, ensure_ascii=False))
