#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
from typing import Dict, List, Tuple

import pandas as pd

import KIS_Common as Common


TARGET_CODES = ["122630", "252670", "233740", "251340"]
GUGAN_LENGTH = 7
RSI_PERIOD = 14


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out = out.sort_index()

    # change column fallback
    if "change" not in out.columns:
        out["change"] = out["close"].pct_change().fillna(0.0)

    delta = out["close"].diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    gain = up.ewm(com=(RSI_PERIOD - 1), min_periods=RSI_PERIOD).mean()
    loss = down.abs().ewm(com=(RSI_PERIOD - 1), min_periods=RSI_PERIOD).mean()
    rs = gain / loss
    out["rsi"] = 100 - (100 / (1 + rs))

    out["prevrsi"] = out["rsi"].shift(1)
    out["prevrsi2"] = out["rsi"].shift(2)

    out[f"high_{GUGAN_LENGTH}_max"] = out["high"].rolling(GUGAN_LENGTH).max().shift(1)
    out[f"low_{GUGAN_LENGTH}_min"] = out["low"].rolling(GUGAN_LENGTH).min().shift(1)

    # OBV
    out["direction"] = 0
    out.loc[out["close"] > out["close"].shift(1), "direction"] = 1
    out.loc[out["close"] < out["close"].shift(1), "direction"] = -1
    out["obv"] = (out["direction"] * out["volume"]).cumsum()
    out["obv_ma"] = out["obv"].rolling(10).mean()
    out["prev_obv_ma"] = out["obv_ma"].shift(1)
    out["prev_obv_ma2"] = out["obv_ma"].shift(2)
    out["prev_obv"] = out["obv"].shift(1)

    out["prevvolume"] = out["volume"].shift(1)
    out["prevvolume2"] = out["volume"].shift(2)
    out["prevvolume3"] = out["volume"].shift(3)
    out["prevclose"] = out["close"].shift(1)
    out["prevopen"] = out["open"].shift(1)
    out["prevhigh"] = out["high"].shift(1)
    out["prevhigh2"] = out["high"].shift(2)
    out["prevlow"] = out["low"].shift(1)
    out["prevlow2"] = out["low"].shift(2)

    out["disparity20"] = out["prevclose"] / out["prevclose"].rolling(20).mean() * 100.0
    out["disparity11"] = out["prevclose"] / out["prevclose"].rolling(11).mean() * 100.0

    out["ma3_before"] = out["close"].rolling(3).mean().shift(1)
    out["ma6_before"] = out["close"].rolling(6).mean().shift(1)
    out["ma19_before"] = out["close"].rolling(19).mean().shift(1)
    out["ma10_before"] = out["close"].rolling(10).mean().shift(1)
    out["ma20_before"] = out["close"].rolling(20).mean().shift(1)
    out["ma20_before2"] = out["close"].rolling(20).mean().shift(2)
    out["ma60_before"] = out["close"].rolling(60).mean().shift(1)
    out["ma60_before2"] = out["close"].rolling(60).mean().shift(2)
    out["ma120_before"] = out["close"].rolling(120).mean().shift(1)
    out["prevchangema"] = out["change"].shift(1).rolling(20).mean()
    out["prevchangema_s"] = out["change"].shift(1).rolling(10).mean()

    return out


def has_nan(vals: List[float]) -> bool:
    return any(pd.isna(v) or (isinstance(v, float) and math.isnan(v)) for v in vals)


def eval_kospi(code: str, row: pd.Series) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    need = [
        row["prevclose"], row["ma3_before"], row["ma6_before"], row["ma19_before"],
        row["prevrsi"], row["prevrsi2"], row["prevvolume2"], row["prevvolume"],
        row["prevlow2"], row["prevlow"], row["ma60_before"], row["ma60_before2"],
    ]
    if has_nan(need):
        return False, ["지표부족(이평/RSI/거래량)"]

    prev_close = row["prevclose"]

    if code == "252670":
        c1 = prev_close > row["ma3_before"] and prev_close > row["ma6_before"] and prev_close > row["ma19_before"]
        c2 = row["prevrsi"] < 70 and row["prevrsi2"] < row["prevrsi"]
        c3 = row["prevvolume2"] < row["prevvolume"]
        c4 = row["prevlow2"] < row["prevlow"]
        c5 = prev_close > row["ma60_before"] and row["ma60_before2"] < row["ma60_before"]
        c6 = row["ma3_before"] > row["ma6_before"] > row["ma19_before"]
        ok = c1 and c2 and c3 and c4 and c5 and c6
        if not ok:
            if not c1:
                reasons.append("252670: prevClose가 ma3/6/19 위가 아님")
            if not c2:
                reasons.append("252670: RSI 조건 불충족")
            if not c3:
                reasons.append("252670: 거래량 증가 조건 불충족(prevVol2<prevVol)")
            if not c4:
                reasons.append("252670: 저가 상승 조건 불충족(prevLow2<prevLow)")
            if not c5:
                reasons.append("252670: ma60 상승/상회 조건 불충족")
            if not c6:
                reasons.append("252670: ma3>ma6>ma19 정배열 불충족")
        return ok, reasons

    # 122630
    need2 = [row["prevlow2"], row["prevlow"], row["disparity20"], row["prevrsi"]]
    if has_nan(need2):
        return False, ["지표부족(Disparity/RSI)"]
    c1 = row["prevlow2"] < row["prevlow"]
    c2 = (row["disparity20"] < 98) or (row["disparity20"] > 106)
    c3 = row["prevrsi"] < 80
    ok = c1 and c2 and c3
    if not ok:
        if not c1:
            reasons.append("122630: prevLow2<prevLow 불충족")
        if not c2:
            reasons.append("122630: Disparity20 범위 미충족(<98 or >106)")
        if not c3:
            reasons.append("122630: prevRSI<80 불충족")
    return ok, reasons


def eval_kosdaq(code: str, row: pd.Series) -> Tuple[bool, List[str], float]:
    reasons: List[str] = []

    need = [
        row["open"], row["high"], row["prevclose"], row["prevhigh"], row["prevlow"],
        row["ma10_before"], row["ma20_before"], row["ma60_before"], row["ma120_before"],
        row[f"high_{GUGAN_LENGTH}_max"], row[f"low_{GUGAN_LENGTH}_min"],
        row["prev_obv_ma2"], row["prev_obv_ma"], row["prev_obv"],
    ]
    if has_nan(need):
        return False, ["지표부족(돌파/이평/OBV)"], float("nan")

    prev_close = row["prevclose"]
    dolpa_rate = 0.4
    if code == "233740":
        dolpa_rate = 0.3 if prev_close > row["ma60_before"] else 0.4

    gap = (abs(row["open"] - prev_close) / prev_close) * 100.0
    gap_st = gap * 0.025
    if gap_st > 1.0:
        gap_st = 1.0
    if gap_st < 0:
        gap_st = 0.1
    if prev_close > row["open"] and gap >= 3.0:
        dolpa_rate *= (1.0 + gap_st)
    if prev_close < row["open"] and gap >= 3.0:
        dolpa_rate *= (1.0 - gap_st)

    dolpa_price = row["open"] + ((row["prevhigh"] - row["prevlow"]) * dolpa_rate)

    is_buy = dolpa_price <= row["high"]
    if not is_buy:
        reasons.append(f"{code}: 당일 고가가 돌파가 미도달(high<{dolpa_price:.2f})")
        return False, reasons, dolpa_price

    # additional filters
    if code == "251340":
        if row["prevclose"] <= row["ma20_before"]:
            reasons.append("251340: prevClose<=ma20_before 로 필터 탈락")
            is_buy = False
    else:
        if row["prevlow"] > row["open"] and row["prevclose"] < row["ma10_before"]:
            reasons.append("233740: 갭/ma10 필터 탈락")
            is_buy = False

    is_jung = row["ma10_before"] > row["ma20_before"] > row["ma60_before"] > row["ma120_before"]
    if not is_jung:
        high_price = row[f"high_{GUGAN_LENGTH}_max"]
        low_price = row[f"low_{GUGAN_LENGTH}_min"]
        maximum_price = low_price + ((high_price - low_price) / 4) * 3.0
        if row["open"] > maximum_price:
            reasons.append("추가개선 필터: open>상단 3/4 구간")
            is_buy = False

    if is_buy and row["prev_obv_ma2"] > row["prev_obv_ma"] and row["prev_obv"] < row["prev_obv_ma"]:
        reasons.append("OBV 필터 탈락(prev_obv_ma 하락 + prev_obv<prev_obv_ma)")
        is_buy = False

    return is_buy, reasons, dolpa_price


def main():
    Common.SetChangeMode("REAL")

    code_df: Dict[str, pd.DataFrame] = {}
    for code in TARGET_CODES:
        df = Common.GetOhlcv("KR", code, 260)
        if df is None or len(df) == 0:
            raise RuntimeError(f"{code} 데이터 조회 실패")
        code_df[code] = add_indicators(df)

    common_dates = sorted(set.intersection(*[set(df.index) for df in code_df.values()]))
    last_dates = common_dates[-5:]

    print("최근 1주(최근 5거래일) 신호 점검")
    print("기준 날짜:", [str(pd.Timestamp(d).date()) for d in last_dates])
    print()

    for d in last_dates:
        d_str = str(pd.Timestamp(d).date())
        print(f"=== {d_str} ===")
        for code in TARGET_CODES:
            row = code_df[code].loc[d]
            if code in ("122630", "252670"):
                ok, reasons = eval_kospi(code, row)
                status = "진입조건 충족" if ok else "미진입"
                print(f"{code}: {status}")
                if reasons:
                    for r in reasons:
                        print("  -", r)
            else:
                ok, reasons, dolpa = eval_kosdaq(code, row)
                status = "진입조건 충족" if ok else "미진입"
                if pd.notna(dolpa):
                    print(f"{code}: {status} (돌파가 {dolpa:.2f}, 고가 {row['high']:.2f})")
                else:
                    print(f"{code}: {status}")
                if reasons:
                    for r in reasons:
                        print("  -", r)
        print()


if __name__ == "__main__":
    main()

