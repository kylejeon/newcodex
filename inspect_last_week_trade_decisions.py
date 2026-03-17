#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
from typing import Dict, List, Tuple

import pandas as pd

import KIS_Common as Common

TARGET_CODES = ["122630", "233740"]
RSI_PERIOD = 14
GUGAN_LENGTH = 7

# Kosdaqpi_Bot_TR_best.py defaults
ENABLE_233740_HARD_STOP = True
HARD_STOP_233740_PCT_TIGHT = 0.085
HARD_STOP_233740_PCT_BASE = 0.125
HARD_STOP_VOL_TH = 0.045


def has_nan(vals: List[float]) -> bool:
    return any(pd.isna(v) or (isinstance(v, float) and math.isnan(v)) for v in vals)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out = out.sort_index()

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

    return out


def eval_buy_122630(row: pd.Series) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    need = [row["prevlow2"], row["prevlow"], row["disparity20"], row["prevrsi"]]
    if has_nan(need):
        return False, ["지표부족"]

    c1 = row["prevlow2"] < row["prevlow"]
    c2 = (row["disparity20"] < 98) or (row["disparity20"] > 106)
    c3 = row["prevrsi"] < 80
    ok = c1 and c2 and c3

    if not c1:
        reasons.append("prevLow2<prevLow 불충족")
    if not c2:
        reasons.append("Disparity20 범위 미충족(<98 or >106)")
    if not c3:
        reasons.append("prevRSI<80 불충족")

    return ok, reasons


def eval_sell_122630(row: pd.Series) -> Tuple[bool, str]:
    need = [row["prevlow2"], row["prevlow"], row["prevvolume"], row["prevvolume2"], row["prevvolume3"], row["disparity20"]]
    if has_nan(need):
        return False, "지표부족"

    total_volume = (row["prevvolume"] + row["prevvolume2"] + row["prevvolume3"]) / 3.0
    hold_cond = ((row["prevlow2"] < row["prevlow"]) or (row["prevvolume"] < total_volume)) and ((row["disparity20"] < 98) or (row["disparity20"] > 105))

    # bot: hold_cond 이면 홀드, 아니면 매도
    if hold_cond:
        return False, "홀드 조건 충족"
    return True, "홀드 조건 미충족 -> 시가 매도"


def calc_dolpa_233740(row: pd.Series) -> float:
    prev_close = row["prevclose"]
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

    return row["open"] + ((row["prevhigh"] - row["prevlow"]) * dolpa_rate)


def eval_buy_233740(row: pd.Series) -> Tuple[bool, List[str], float]:
    reasons: List[str] = []
    need = [
        row["open"], row["high"], row["prevclose"], row["prevhigh"], row["prevlow"],
        row["ma10_before"], row["ma20_before"], row["ma60_before"], row["ma120_before"],
        row[f"high_{GUGAN_LENGTH}_max"], row[f"low_{GUGAN_LENGTH}_min"],
        row["prev_obv_ma2"], row["prev_obv_ma"], row["prev_obv"],
    ]
    if has_nan(need):
        return False, ["지표부족"], float("nan")

    dolpa = calc_dolpa_233740(row)
    ok = row["high"] >= dolpa
    if not ok:
        reasons.append(f"고가가 돌파가 미도달(high<{dolpa:.2f})")
        return False, reasons, dolpa

    if row["prevlow"] > row["open"] and row["prevclose"] < row["ma10_before"]:
        reasons.append("갭/ma10 필터 탈락")
        ok = False

    is_jung = row["ma10_before"] > row["ma20_before"] > row["ma60_before"] > row["ma120_before"]
    if not is_jung:
        high_price = row[f"high_{GUGAN_LENGTH}_max"]
        low_price = row[f"low_{GUGAN_LENGTH}_min"]
        maximum_price = low_price + ((high_price - low_price) / 4.0) * 3.0
        if row["open"] > maximum_price:
            reasons.append("open>상단 3/4 구간")
            ok = False

    if ok and row["prev_obv_ma2"] > row["prev_obv_ma"] and row["prev_obv"] < row["prev_obv_ma"]:
        reasons.append("OBV 필터 탈락")
        ok = False

    return ok, reasons, dolpa


def eval_sell_233740(row: pd.Series, buy_price: float) -> Tuple[bool, str, float, float]:
    need = [row["open"], row["prevhigh"], row["prevlow"], row["prevclose"], row["ma60_before"], row["ma20_before"], row["low"]]
    if has_nan(need):
        return False, "지표부족", float("nan"), float("nan")

    cut_rate = 0.4 if row["prevclose"] > row["ma60_before"] else 0.3
    cut_price = row["open"] - ((row["prevhigh"] - row["prevlow"]) * cut_rate)

    hard_stop_trigger = False
    hard_stop_price = float("nan")
    if ENABLE_233740_HARD_STOP and buy_price > 0:
        prev_range_ratio = (row["prevhigh"] - row["prevlow"]) / max(1.0, row["prevclose"])
        weak_trend = row["prevclose"] <= row["ma20_before"]
        is_high_vol = prev_range_ratio >= HARD_STOP_VOL_TH

        hard_stop_pct = HARD_STOP_233740_PCT_TIGHT if (weak_trend and is_high_vol) else HARD_STOP_233740_PCT_BASE
        hard_stop_price = buy_price * (1.0 - hard_stop_pct)
        if row["low"] <= hard_stop_price:
            hard_stop_trigger = True

    cut_trigger = row["low"] <= cut_price
    sell = cut_trigger or hard_stop_trigger

    if hard_stop_trigger:
        return True, f"하드스탑 트리거(low<= {hard_stop_price:.2f})", cut_price, hard_stop_price
    if cut_trigger:
        return True, f"컷프라이스 트리거(low<= {cut_price:.2f})", cut_price, hard_stop_price
    return False, "매도 미충족", cut_price, hard_stop_price


def main():
    Common.SetChangeMode("REAL")

    code_df: Dict[str, pd.DataFrame] = {}
    for code in TARGET_CODES:
        df = Common.GetOhlcv("KR", code, 260)
        if df is None or len(df) == 0:
            raise RuntimeError(f"{code} 데이터 조회 실패")
        code_df[code] = add_indicators(df)

    common_dates = sorted(set.intersection(*[set(df.index) for df in code_df.values()]))
    last_dates = common_dates[-7:]

    print("최근 1주(최근 7거래일) 122630/233740 신호 점검")
    print("기준 날짜:", [str(pd.Timestamp(d).date()) for d in last_dates])
    print()

    # user-provided fills for verification
    buy_price_122630 = 87130.0
    buy_price_233740 = 16875.0

    for d in last_dates:
        ds = str(pd.Timestamp(d).date())
        r122 = code_df["122630"].loc[d]
        r233 = code_df["233740"].loc[d]

        buy122, reasons122 = eval_buy_122630(r122)
        sell122, sell_reason122 = eval_sell_122630(r122)

        buy233, reasons233, dolpa233 = eval_buy_233740(r233)
        sell233, sell_reason233, cut233, hard233 = eval_sell_233740(r233, buy_price_233740)

        print(f"=== {ds} ===")
        print(f"122630 BUY: {'충족' if buy122 else '미충족'}")
        if reasons122:
            print("  -", "; ".join(reasons122))
        print(f"122630 SELL(보유 가정): {'충족' if sell122 else '미충족'} | {sell_reason122}")

        print(f"233740 BUY: {'충족' if buy233 else '미충족'} (돌파가 {dolpa233:.2f}, 고가 {r233['high']:.2f})")
        if reasons233:
            print("  -", "; ".join(reasons233))
        hard_txt = "nan" if pd.isna(hard233) else f"{hard233:.2f}"
        print(f"233740 SELL(보유 가정): {'충족' if sell233 else '미충족'} | {sell_reason233} | CutPrice={cut233:.2f}, HardStop={hard_txt}")
        print()


if __name__ == "__main__":
    main()
