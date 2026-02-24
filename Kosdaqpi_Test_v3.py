import os
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR


Common.SetChangeMode(os.getenv("ACCOUNT_MODE", "VIRTUAL"))


def env_str(name, default):
    v = os.getenv(name)
    return default if v is None or v == "" else v


def env_float(name, default):
    v = os.getenv(name)
    return float(default) if v is None or v == "" else float(v)


def env_int(name, default):
    v = os.getenv(name)
    return int(default) if v is None or v == "" else int(v)


def env_bool(name, default):
    v = os.getenv(name)
    if v is None or v == "":
        return bool(default)
    return v.lower() in ("1", "true", "yes", "y", "on")


def validate_mode_credentials():
    mode = Common.GetNowDist()
    app_key = str(Common.GetAppKey(mode)).strip()
    app_secret = str(Common.GetAppSecret(mode)).strip()
    placeholder_tokens = {
        "your_virtual_app_key_here",
        "your_virtual_app_secret_here",
        "your_app_key_here",
        "your_app_secret_here",
    }
    if app_key in placeholder_tokens or app_secret in placeholder_tokens:
        print(f"[ERROR] {mode} 모드 인증키가 placeholder 값입니다.")
        print("- myStockInfo.yaml의 해당 모드 APP_KEY / APP_SECRET을 실제 값으로 설정하세요.")
        print("- 또는 ACCOUNT_MODE=REAL 로 실행해 REAL 키를 사용하세요.")
        raise SystemExit(1)


UNIVERSE = [x.strip() for x in env_str(
    "UNIVERSE_CODES",
    "122630,252670,233740,251340,069500,132030",
).split(",") if x.strip()]
INVERSE_CODES = set(
    [x.strip() for x in env_str("INVERSE_CODES", "252670,251340,114800").split(",") if x.strip()]
)
CORE_CODES = set(
    [x.strip() for x in env_str("CORE_CODES", "122630,252670,233740,251340").split(",") if x.strip()]
)
DEFENSIVE_CODES = set(
    [x.strip() for x in env_str("DEFENSIVE_CODES", "069500,132030").split(",") if x.strip()]
)
MARKET_PROXY = env_str("MARKET_PROXY_CODE", "122630")

TOTAL_MONEY = env_float("TOTAL_MONEY", 10_000_000)
FEE = env_float("FEE", 0.0015)
LIMIT_BARS = env_int("LIMIT_BARS", 2600)
START_YEAR = env_int("START_YEAR", 2017)

MAX_WEIGHT = env_float("MAX_WEIGHT", 0.35)
MAX_LEVERAGE = env_float("MAX_LEVERAGE", 1.2)
RISK_OFF_DD_ON = env_float("RISK_OFF_DD_ON", -0.12)
RISK_OFF_DD_OFF = env_float("RISK_OFF_DD_OFF", -0.05)

RISK_ON_POS = env_int("RISK_ON_POS", 4)
NEUTRAL_POS = env_int("NEUTRAL_POS", 3)
RISK_OFF_POS = env_int("RISK_OFF_POS", 2)
RISK_ON_TARGET_VOL = env_float("RISK_ON_TARGET_VOL", 0.24)
NEUTRAL_TARGET_VOL = env_float("NEUTRAL_TARGET_VOL", 0.16)
RISK_OFF_TARGET_VOL = env_float("RISK_OFF_TARGET_VOL", 0.10)

BACKTEST_START = env_str("BACKTEST_START", "")
BACKTEST_END = env_str("BACKTEST_END", "")
ENABLE_PLOT = env_bool("ENABLE_PLOT", True)
REBALANCE_FREQ_DAYS = env_int("REBALANCE_FREQ_DAYS", 5)
MIN_WEIGHT_CHANGE = env_float("MIN_WEIGHT_CHANGE", 0.06)


def get_name(code):
    try:
        n = KisKR.GetStockName(code)
        return n if n else code
    except Exception:
        return code


def prepare_df(code):
    try:
        df = Common.GetOhlcv("KR", code, LIMIT_BARS)
    except Exception as e:
        print(f"[WARN] {code} GetOhlcv 예외: {e}")
        return None

    if not isinstance(df, pd.DataFrame):
        print(f"[WARN] {code} GetOhlcv 반환 타입 이상: {type(df)}")
        return None

    if df is None or len(df) < 250:
        return None

    req = ["open", "high", "low", "close", "volume", "change"]
    if any(col not in df.columns for col in req):
        return None

    df = df.copy()
    df["prevClose"] = df["close"].shift(1)
    df["ma20"] = df["close"].rolling(20).mean().shift(1)
    df["ma60"] = df["close"].rolling(60).mean().shift(1)
    df["mom20"] = (df["prevClose"] / df["close"].shift(20)) - 1.0
    df["mom60"] = (df["prevClose"] / df["close"].shift(60)) - 1.0

    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = tr.rolling(14).mean().shift(1)
    df["atr_pct"] = (df["atr14"] / df["prevClose"]) * 100.0
    df["open_next"] = df["open"].shift(-1)
    df["ret_oo"] = (df["open_next"] / df["open"]) - 1.0
    df["code"] = code
    df.dropna(inplace=True)
    return df


def regime_of_row(proxy_row):
    if proxy_row is None:
        return "neutral"
    trend = 1 if proxy_row["ma20"] > proxy_row["ma60"] else -1
    mom = 1 if proxy_row["mom20"] > 0 else -1
    score = trend + mom
    if score >= 2:
        return "risk_on"
    if score <= -2:
        return "risk_off"
    return "neutral"


def target_params(regime):
    if regime == "risk_on":
        return RISK_ON_POS, RISK_ON_TARGET_VOL
    if regime == "risk_off":
        return RISK_OFF_POS, RISK_OFF_TARGET_VOL
    return NEUTRAL_POS, NEUTRAL_TARGET_VOL


def signal_and_score(row, is_inverse):
    long_signal = int(row["ma20"] > row["ma60"]) + int(row["mom20"] > 0) + int(row["mom60"] > 0)
    short_signal = int(row["ma20"] < row["ma60"]) + int(row["mom20"] < 0) + int(row["mom60"] < 0)
    if is_inverse:
        signal = short_signal >= 2
        score = (-row["mom20"]) * 0.6 + (-row["mom60"]) * 0.4
    else:
        signal = long_signal >= 2
        score = row["mom20"] * 0.6 + row["mom60"] * 0.4
    return signal, float(score)


def make_target_weights(day_rows, regime, risk_off_overlay):
    max_pos, target_vol = target_params(regime)
    if risk_off_overlay:
        max_pos = max(1, max_pos - 1)
        target_vol *= 0.75

    candidates = []
    for code, row in day_rows.items():
        if regime in ("risk_on", "neutral") and code not in CORE_CODES:
            continue
        if regime == "risk_off" and code not in CORE_CODES.union(DEFENSIVE_CODES):
            continue
        is_inv = code in INVERSE_CODES
        sig, score = signal_and_score(row, is_inv)
        atr_pct = max(float(row["atr_pct"]), 0.05)
        if sig:
            candidates.append((code, score, atr_pct))

    if not candidates:
        return {}

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = candidates[:max_pos]

    inv_risk = np.array([1.0 / c[2] for c in selected], dtype=float)
    w = inv_risk / inv_risk.sum()

    # Rough volatility targeting: ATR% proxy
    est_daily_vol = np.sqrt(np.sum((w * np.array([c[2] for c in selected]) / 100.0) ** 2))
    est_annual_vol = est_daily_vol * np.sqrt(252)
    leverage = min(MAX_LEVERAGE, target_vol / max(est_annual_vol, 1e-6))
    w = w * leverage
    w = np.clip(w, 0, MAX_WEIGHT)
    if w.sum() > 1.0:
        w = w / w.sum()

    return {c[0]: float(weight) for c, weight in zip(selected, w)}


def run():
    validate_mode_credentials()
    print(f"계좌 모드: {Common.GetNowDist()}")
    print("테스트하는 총 금액: ", format(round(TOTAL_MONEY), ","))
    print("유니버스:", UNIVERSE)

    data_map = {}
    names = {}
    for code in UNIVERSE:
        names[code] = get_name(code)
        df = prepare_df(code)
        if df is not None and len(df) > 0:
            data_map[code] = df
        else:
            print(f"[WARN] {code} 데이터 로딩 실패/부족으로 제외")

    if MARKET_PROXY not in data_map:
        print(f"[ERROR] MARKET_PROXY_CODE({MARKET_PROXY}) 데이터가 없어 백테스트를 중단합니다.")
        return 1

    if len(data_map) < 2:
        print("[ERROR] 유효 종목이 부족합니다.")
        return 1

    common_dates = None
    for df in data_map.values():
        idx = set(df.index)
        common_dates = idx if common_dates is None else common_dates.intersection(idx)
    dates = sorted(list(common_dates))
    if len(dates) < 200:
        print("[ERROR] 공통 날짜가 너무 적습니다.")
        return 1

    if BACKTEST_START:
        s = pd.to_datetime(BACKTEST_START)
        dates = [d for d in dates if pd.to_datetime(d) >= s]
    if BACKTEST_END:
        e = pd.to_datetime(BACKTEST_END)
        dates = [d for d in dates if pd.to_datetime(d) <= e]

    dates = [d for d in dates if pd.to_datetime(d).year >= START_YEAR]
    if len(dates) < 30:
        print("[ERROR] 백테스트 기간이 너무 짧습니다.")
        return 1

    value = TOTAL_MONEY
    peak = TOTAL_MONEY
    risk_off_overlay = False
    weights = {}
    last_regime = None
    last_rebalance_idx = -999

    value_curve = []
    trade_open = {}
    stock_stats = {
        c: {"try": 0, "success": 0, "fail": 0, "accRev": 0.0}
        for c in data_map.keys()
    }

    for i, date in enumerate(dates[:-1]):
        day_rows = {}
        for code, df in data_map.items():
            r = df.loc[df.index == date]
            if len(r) == 1:
                day_rows[code] = r.iloc[0]

        proxy_row = day_rows.get(MARKET_PROXY)
        regime = regime_of_row(proxy_row)
        raw_target_w = make_target_weights(day_rows, regime, risk_off_overlay)

        do_rebalance = False
        if regime != last_regime:
            do_rebalance = True
        elif i - last_rebalance_idx >= REBALANCE_FREQ_DAYS:
            do_rebalance = True

        if do_rebalance:
            all_codes = set(weights.keys()).union(set(raw_target_w.keys()))
            delta = sum(abs(raw_target_w.get(c, 0.0) - weights.get(c, 0.0)) for c in all_codes)
            target_w = raw_target_w if delta >= MIN_WEIGHT_CHANGE else dict(weights)
            if target_w is raw_target_w:
                last_rebalance_idx = i
        else:
            target_w = dict(weights)

        last_regime = regime

        # trade stats: close and open
        for code, prev_w in list(weights.items()):
            if prev_w > 0 and target_w.get(code, 0.0) <= 0:
                row = day_rows.get(code)
                if row is not None and code in trade_open:
                    exit_p = float(row["open"]) * (1.0 - FEE)
                    entry_p = trade_open[code]
                    rr = (exit_p / entry_p - 1.0) * 100.0
                    stock_stats[code]["try"] += 1
                    stock_stats[code]["accRev"] += rr
                    if rr > 0:
                        stock_stats[code]["success"] += 1
                    else:
                        stock_stats[code]["fail"] += 1
                    del trade_open[code]

        for code, w in target_w.items():
            if w > 0 and weights.get(code, 0.0) <= 0:
                row = day_rows.get(code)
                if row is not None:
                    trade_open[code] = float(row["open"]) * (1.0 + FEE)

        # turnover fee
        all_codes = set(weights.keys()).union(set(target_w.keys()))
        turnover = sum(abs(target_w.get(c, 0.0) - weights.get(c, 0.0)) for c in all_codes)
        value *= (1.0 - turnover * FEE)
        weights = target_w

        # open-to-open return
        day_ret = 0.0
        for code, w in weights.items():
            row = day_rows.get(code)
            if row is not None:
                day_ret += w * float(row["ret_oo"])
        value *= (1.0 + day_ret)

        if value > peak:
            peak = value
        dd = value / peak - 1.0
        if (not risk_off_overlay) and dd <= RISK_OFF_DD_ON:
            risk_off_overlay = True
        elif risk_off_overlay and dd >= RISK_OFF_DD_OFF:
            risk_off_overlay = False

        value_curve.append((date, value))

    result_df = pd.DataFrame(value_curve, columns=["date", "Total_Money"]).set_index("date")
    result_df["Ror"] = np.nan_to_num(result_df["Total_Money"].pct_change()) + 1
    result_df["Cum_Ror"] = result_df["Ror"].cumprod()
    result_df["Highwatermark"] = result_df["Cum_Ror"].cummax()
    result_df["Drawdown"] = (result_df["Cum_Ror"] / result_df["Highwatermark"]) - 1
    result_df["MaxDrawdown"] = result_df["Drawdown"].cummin()

    start_date = pd.to_datetime(result_df.index[0])
    end_date = pd.to_datetime(result_df.index[-1])
    years = (end_date - start_date).days / 365.25
    final_money = float(result_df["Total_Money"].iloc[-1])
    revenue_rate = (final_money / TOTAL_MONEY - 1.0) * 100.0
    mdd = float(result_df["MaxDrawdown"].min()) * 100.0
    cagr = ((final_money / TOTAL_MONEY) ** (1 / max(years, 1e-6)) - 1) * 100.0

    total_try = sum(v["try"] for v in stock_stats.values())
    total_success = sum(v["success"] for v in stock_stats.values())
    total_fail = sum(v["fail"] for v in stock_stats.values())

    print("\n\n--------------------")
    print(f"--->>> {str(start_date.date())} ~ {str(end_date.date())} <<<---")
    for code in data_map.keys():
        s = stock_stats[code]
        print(f"{names.get(code, code)}  ( {code} )")
        if s["try"] > 0:
            win = (s["success"] / s["try"]) * 100.0
            avg = s["accRev"] / s["try"]
            print(f"성공: {s['success']}  실패: {s['fail']}  -> 승률:  {round(win,2)}  %")
            print(f"매매당 평균 수익률: {round(avg,2)}")
        else:
            print("성공: 0  실패: 0  -> 승률:  0.0  %")
            print("매매당 평균 수익률: 0.0")
        print()

    print("---------- 총 결과 ----------")
    print(
        f"최초 금액: {format(int(round(TOTAL_MONEY,0)), ',')}  "
        f"최종 금액: {format(int(round(final_money,0)), ',')}  \n"
        f"수익률: {round(revenue_rate,2)} % MDD: {round(mdd,2)} %"
    )
    if total_try > 0:
        print(f"성공: {total_success}  실패: {total_fail}  -> 승률:  {round(total_success/total_try*100.0,2)}  %")
    print(f"연복리수익률(CAGR): {round(cagr,2)} %\n")

    if ENABLE_PLOT:
        result_df.index = pd.to_datetime(result_df.index)
        fig, axs = plt.subplots(2, 1, figsize=(10, 10))
        axs[0].plot(result_df["Cum_Ror"] * 100, label="Strategy")
        axs[0].set_ylabel("Cumulative Return (%)")
        axs[0].set_title("Return Chart")
        axs[0].legend()
        axs[1].plot(result_df.index, result_df["MaxDrawdown"] * 100, label="MDD")
        axs[1].plot(result_df.index, result_df["Drawdown"] * 100, label="Drawdown")
        axs[1].set_ylabel("Drawdown (%)")
        axs[1].set_title("Drawdown Chart")
        axs[1].legend()
        plt.tight_layout()
        plt.show()

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
