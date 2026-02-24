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
    placeholders = {
        "your_virtual_app_key_here",
        "your_virtual_app_secret_here",
        "your_app_key_here",
        "your_app_secret_here",
    }
    if app_key in placeholders or app_secret in placeholders:
        print(f"[ERROR] {mode} 모드 인증키가 placeholder 값입니다.")
        raise SystemExit(1)


UNIVERSE = [x.strip() for x in env_str("UNIVERSE_CODES", "122630,252670,233740,251340,069500,132030").split(",") if x.strip()]
CORE_CODES = set([x.strip() for x in env_str("CORE_CODES", "122630,252670,233740,251340").split(",") if x.strip()])
DEF_CODES = set([x.strip() for x in env_str("DEFENSIVE_CODES", "069500,132030").split(",") if x.strip()])
INV_CODES = set([x.strip() for x in env_str("INVERSE_CODES", "252670,251340").split(",") if x.strip()])
LONG_CODES = CORE_CODES - INV_CODES
MARKET_PROXY = env_str("MARKET_PROXY_CODE", "122630")

TOTAL_MONEY = env_float("TOTAL_MONEY", 10_000_000)
FEE = env_float("FEE", 0.0015)
LIMIT_BARS = env_int("LIMIT_BARS", 2600)
START_YEAR = env_int("START_YEAR", 2017)
MAX_WEIGHT = env_float("MAX_WEIGHT", 0.40)
MAX_LEVERAGE = env_float("MAX_LEVERAGE", 1.15)
TARGET_VOL = env_float("TARGET_VOL", 0.20)
RISK_ON_TARGET_VOL = env_float("RISK_ON_TARGET_VOL", 0.24)
NEUTRAL_TARGET_VOL = env_float("NEUTRAL_TARGET_VOL", 0.16)
RISK_OFF_TARGET_VOL = env_float("RISK_OFF_TARGET_VOL", 0.11)
REBALANCE_DAYS = env_int("REBALANCE_DAYS", 3)
MIN_TURNOVER = env_float("MIN_TURNOVER", 0.07)
ENABLE_PLOT = env_bool("ENABLE_PLOT", True)

BACKTEST_START = env_str("BACKTEST_START", "")
BACKTEST_END = env_str("BACKTEST_END", "")


def get_name(code):
    try:
        name = KisKR.GetStockName(code)
        return name if name else code
    except Exception:
        return code


def calc_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    gain = up.ewm(com=period - 1, min_periods=period).mean()
    loss = down.ewm(com=period - 1, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def prepare_df(code):
    try:
        df = Common.GetOhlcv("KR", code, LIMIT_BARS)
    except Exception as e:
        print(f"[WARN] {code} GetOhlcv 예외: {e}")
        return None

    if not isinstance(df, pd.DataFrame) or len(df) < 250:
        return None
    req = ["open", "high", "low", "close", "volume", "change"]
    if any(col not in df.columns for col in req):
        return None

    df = df.copy()
    df["prevClose"] = df["close"].shift(1)
    df["ma5"] = df["close"].rolling(5).mean().shift(1)
    df["ma20"] = df["close"].rolling(20).mean().shift(1)
    df["ma60"] = df["close"].rolling(60).mean().shift(1)
    df["mom10"] = (df["prevClose"] / df["close"].shift(10)) - 1.0
    df["mom20"] = (df["prevClose"] / df["close"].shift(20)) - 1.0
    df["mom60"] = (df["prevClose"] / df["close"].shift(60)) - 1.0
    df["rsi14"] = calc_rsi(df["close"], 14).shift(1)

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


def regime(proxy_row):
    if proxy_row is None:
        return "neutral"
    score = 0
    score += 1 if proxy_row["ma20"] > proxy_row["ma60"] else -1
    score += 1 if proxy_row["mom20"] > 0 else -1
    score += 1 if proxy_row["mom60"] > 0 else -1
    if score >= 2:
        return "risk_on"
    if score <= -2:
        return "risk_off"
    return "neutral"


def strategy_scores(code, row, rgm):
    is_inv = code in INV_CODES
    is_def = code in DEF_CODES
    is_long = code in LONG_CODES

    # A: trend
    if is_inv:
        a = (1 if row["ma20"] < row["ma60"] else -1) + (1 if row["mom20"] < 0 else -1)
    else:
        a = (1 if row["ma20"] > row["ma60"] else -1) + (1 if row["mom20"] > 0 else -1)
    a = a * 0.5

    # B: mean-reversion
    if is_inv:
        b = max(0.0, (row["rsi14"] - 60.0) / 40.0)
    else:
        b = max(0.0, (40.0 - row["rsi14"]) / 40.0)
    b = min(1.0, b)

    # C: defensive
    if is_def and rgm == "risk_off":
        c = 1.0 + max(0.0, row["mom20"])
    elif code in CORE_CODES:
        c = 0.4 if rgm == "risk_on" else 0.2
    else:
        c = 0.0

    if rgm == "risk_on":
        wa, wb, wc = 0.70, 0.20, 0.10
    elif rgm == "neutral":
        wa, wb, wc = 0.50, 0.30, 0.20
    else:
        wa, wb, wc = 0.25, 0.15, 0.60

    s = (wa * a) + (wb * b) + (wc * c)
    # 레짐별 강한 게이팅: 인버스는 리스크오프에서만 적극 사용
    if rgm == "risk_on" and is_inv:
        s = 0.0
    if rgm == "risk_off" and is_long and (not is_def):
        s *= 0.35
    if rgm == "neutral" and is_inv:
        s *= 0.4
    return max(0.0, s)


def target_weights(day_rows, rgm):
    scored = []
    for code, row in day_rows.items():
        if rgm == "risk_on" and code not in LONG_CODES.union(DEF_CODES):
            continue
        if rgm == "risk_on" and code in DEF_CODES:
            continue
        if rgm == "neutral" and code not in CORE_CODES.union(DEF_CODES):
            continue
        if rgm == "risk_off" and code not in INV_CODES.union(DEF_CODES):
            continue
        score = strategy_scores(code, row, rgm)
        if score <= 0:
            continue
        vol = max(float(row["atr_pct"]), 0.05)
        scored.append((code, score, vol))

    if not scored:
        return {}

    scored.sort(key=lambda x: x[1], reverse=True)
    max_n = 3 if rgm == "risk_on" else (3 if rgm == "neutral" else 2)
    sel = scored[:max_n]

    raw = np.array([(x[1] / x[2]) for x in sel], dtype=float)
    w = raw / raw.sum()

    est_daily_vol = np.sqrt(np.sum((w * np.array([x[2] for x in sel]) / 100.0) ** 2))
    est_ann_vol = est_daily_vol * np.sqrt(252)
    if rgm == "risk_on":
        tv = RISK_ON_TARGET_VOL
    elif rgm == "neutral":
        tv = NEUTRAL_TARGET_VOL
    else:
        tv = RISK_OFF_TARGET_VOL
    lev = min(MAX_LEVERAGE, tv / max(est_ann_vol, 1e-9))
    w = w * lev
    w = np.clip(w, 0, MAX_WEIGHT)
    if w.sum() > 1.0:
        w = w / w.sum()

    return {x[0]: float(y) for x, y in zip(sel, w)}


def run():
    validate_mode_credentials()
    print(f"계좌 모드: {Common.GetNowDist()}")
    print("테스트하는 총 금액: ", format(round(TOTAL_MONEY), ","))
    print("유니버스:", UNIVERSE)

    names = {c: get_name(c) for c in UNIVERSE}
    data_map = {}
    for c in UNIVERSE:
        df = prepare_df(c)
        if df is None:
            print(f"[WARN] {c} 데이터 로딩 실패/부족으로 제외")
            continue
        data_map[c] = df

    if MARKET_PROXY not in data_map:
        print(f"[ERROR] MARKET_PROXY_CODE({MARKET_PROXY}) 데이터가 없어 백테스트 중단")
        return 1
    if len(data_map) < 2:
        print("[ERROR] 유효 데이터 종목 부족")
        return 1

    common_dates = None
    for df in data_map.values():
        idx = set(df.index)
        common_dates = idx if common_dates is None else common_dates.intersection(idx)
    dates = sorted(common_dates)

    if BACKTEST_START:
        s = pd.to_datetime(BACKTEST_START)
        dates = [d for d in dates if pd.to_datetime(d) >= s]
    if BACKTEST_END:
        e = pd.to_datetime(BACKTEST_END)
        dates = [d for d in dates if pd.to_datetime(d) <= e]
    dates = [d for d in dates if pd.to_datetime(d).year >= START_YEAR]
    if len(dates) < 30:
        print("[ERROR] 백테스트 기간 부족")
        return 1

    val = TOTAL_MONEY
    peak = TOTAL_MONEY
    weights = {}
    curve = []
    last_rebalance = -999
    last_regime = None

    trade_open = {}
    stats = {c: {"try": 0, "success": 0, "fail": 0, "accRev": 0.0} for c in data_map.keys()}

    for i, dt in enumerate(dates[:-1]):
        day_rows = {}
        for c, df in data_map.items():
            r = df.loc[df.index == dt]
            if len(r) == 1:
                day_rows[c] = r.iloc[0]
        rgm = regime(day_rows.get(MARKET_PROXY))
        raw_target = target_weights(day_rows, rgm)

        rebalance = (rgm != last_regime) or (i - last_rebalance >= REBALANCE_DAYS)
        if rebalance:
            all_codes = set(weights.keys()).union(raw_target.keys())
            delta = sum(abs(raw_target.get(c, 0.0) - weights.get(c, 0.0)) for c in all_codes)
            target = raw_target if delta >= MIN_TURNOVER else dict(weights)
            if target is raw_target:
                last_rebalance = i
        else:
            target = dict(weights)
        last_regime = rgm

        for c, old_w in list(weights.items()):
            if old_w > 0 and target.get(c, 0.0) <= 0 and c in trade_open and c in day_rows:
                exit_p = float(day_rows[c]["open"]) * (1.0 - FEE)
                rr = (exit_p / trade_open[c] - 1.0) * 100.0
                stats[c]["try"] += 1
                stats[c]["accRev"] += rr
                if rr > 0:
                    stats[c]["success"] += 1
                else:
                    stats[c]["fail"] += 1
                del trade_open[c]

        for c, new_w in target.items():
            if new_w > 0 and weights.get(c, 0.0) <= 0 and c in day_rows:
                trade_open[c] = float(day_rows[c]["open"]) * (1.0 + FEE)

        all_codes = set(weights.keys()).union(target.keys())
        turnover = sum(abs(target.get(c, 0.0) - weights.get(c, 0.0)) for c in all_codes)
        val *= (1.0 - turnover * FEE)
        weights = target

        day_ret = 0.0
        for c, w in weights.items():
            if c in day_rows:
                day_ret += w * float(day_rows[c]["ret_oo"])
        val *= (1.0 + day_ret)
        peak = max(peak, val)
        curve.append((dt, val, val / peak - 1.0))

    result_df = pd.DataFrame(curve, columns=["date", "Total_Money", "Drawdown"]).set_index("date")
    result_df["Ror"] = np.nan_to_num(result_df["Total_Money"].pct_change()) + 1
    result_df["Cum_Ror"] = result_df["Ror"].cumprod()
    result_df["MaxDrawdown"] = result_df["Drawdown"].cummin()

    start_date = pd.to_datetime(result_df.index[0])
    end_date = pd.to_datetime(result_df.index[-1])
    years = (end_date - start_date).days / 365.25
    final_money = float(result_df["Total_Money"].iloc[-1])
    revenue = (final_money / TOTAL_MONEY - 1.0) * 100.0
    mdd = float(result_df["MaxDrawdown"].min()) * 100.0
    cagr = ((final_money / TOTAL_MONEY) ** (1 / max(years, 1e-9)) - 1.0) * 100.0

    t_try = sum(v["try"] for v in stats.values())
    t_suc = sum(v["success"] for v in stats.values())
    t_fail = sum(v["fail"] for v in stats.values())

    print("\n\n--------------------")
    print(f"--->>> {start_date.date()} ~ {end_date.date()} <<<---")
    for c in data_map.keys():
        s = stats[c]
        print(f"{names.get(c, c)}  ( {c} )")
        if s["try"] > 0:
            print(f"성공: {s['success']}  실패: {s['fail']}  -> 승률:  {round(s['success']/s['try']*100.0,2)}  %")
            print(f"매매당 평균 수익률: {round(s['accRev']/s['try'],2)}")
        else:
            print("성공: 0  실패: 0  -> 승률:  0.0  %")
            print("매매당 평균 수익률: 0.0")
        print()

    print("---------- 총 결과 ----------")
    print(
        f"최초 금액: {format(int(round(TOTAL_MONEY,0)), ',')}  최종 금액: {format(int(round(final_money,0)), ',')}  \n"
        f"수익률: {round(revenue,2)} % MDD: {round(mdd,2)} %"
    )
    if t_try > 0:
        print(f"성공: {t_suc}  실패: {t_fail}  -> 승률:  {round(t_suc/t_try*100.0,2)}  %")
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
