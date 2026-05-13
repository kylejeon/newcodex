# -*- coding: utf-8 -*-
'''
MNQ 1분봉 최근 1개월 백테스트

목적:
- 기존 코스피/코스닥 전략과 분리된 별도 아이디어 검증용
- 첨부 PDF의 핵심 개념을 "실행 가능한 규칙"으로 바꾼 해석형 백테스트

핵심 해석:
1. 1분봉 사용
2. 22EMA를 기준선으로 사용
3. 가격이 22EMA에서 과도하게 이탈했을 때(괴리감)
4. 반전 확인 신호가 나오면 역추세 단타 진입
5. 최근 충격 구간(impulse)의 25% 되돌림에서 청산

주의:
- PDF의 설명을 정량 규칙으로 재구성한 "해석형 전략"입니다.
- 원문 강의/영상의 정확한 체결 규칙과 완전히 같지 않습니다.
- MNQ는 Yahoo Finance 티커 MNQ=F 기준으로 1분봉 최근 30일 데이터를 사용합니다.
'''

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo


TICKER = "MNQ=F"
PERIOD = "30d"
INTERVAL = "1m"
LOOKBACK_DAYS = 29
START_CAPITAL = 10_000.0
CONTRACTS = 1
POINT_VALUE = 2.0          # MNQ = $2 per point
COMMISSION_PER_SIDE = 1.2  # 대략적인 수수료 가정
TICK_SIZE = 0.25
MIN_TARGET_TICKS = 4       # 최소 4틱(=1포인트) 이상 남아 있어야 진입

# 전략 파라미터
EMA_LEN = 22
ATR_LEN = 14
SWING_LOOKBACK = 30
STRETCH_ATR = 1.4          # EMA 기준 얼마나 멀어졌는지(ATR 배수)
MAX_HOLD_BARS = 40         # 40분 내에 목표/손절 안 나면 시간청산
TARGET_RETRACE = 0.25      # PDF 핵심: 25% 되돌림
STOP_ATR_BUFFER = 0.45     # 극값 바깥 손절 버퍼
MIN_IMPULSE_ATR = 1.8      # 충격 구간이 너무 작으면 스킵

# 시간대 필터
TIME_FILTER_MODE = "off"   # off | regular | opening
US_TZ = ZoneInfo("America/New_York")
ENTRY_MIN_FROM_OPEN = None
ENTRY_MAX_FROM_OPEN = None

OUTPUT_DIR = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class Trade:
    side: str
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    stop: float
    target: float
    bars_held: int
    reason: str
    gross_pnl: float
    net_pnl: float
    ret_on_capital_pct: float


def load_mnq_1m() -> pd.DataFrame:
    # Yahoo 1분봉은 한 번에 약 8일 제한이 있으므로 7일씩 나눠서 이어붙인다.
    end_dt = datetime.now(timezone.utc)
    # Yahoo는 "최근 30일 이내" 조건을 엄격하게 보므로 29일로 약간 여유를 둔다.
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    chunks = []
    cursor = start_dt

    while cursor < end_dt:
        chunk_end = min(cursor + timedelta(days=7), end_dt)
        part = yf.download(
            TICKER,
            start=cursor,
            end=chunk_end,
            interval=INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if part is not None and len(part) > 0:
            chunks.append(part)
        cursor = chunk_end

    if not chunks:
        raise RuntimeError("MNQ 1분봉 데이터를 가져오지 못했습니다.")

    df = pd.concat(chunks)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.rename(columns=str.lower)
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"필수 컬럼 누락: {required - set(df.columns)}")

    df = df[list(required)].copy()
    df.dropna(inplace=True)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema22"] = out["close"].ewm(span=EMA_LEN, adjust=False).mean()
    out["ema_slope"] = out["ema22"].diff()

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(ATR_LEN).mean()

    out["swing_high"] = out["high"].rolling(SWING_LOOKBACK).max().shift(1)
    out["swing_low"] = out["low"].rolling(SWING_LOOKBACK).min().shift(1)
    out["prev_high"] = out["high"].shift(1)
    out["prev_low"] = out["low"].shift(1)

    out["stretch_long"] = (out["ema22"] - out["low"]) / out["atr"]
    out["stretch_short"] = (out["high"] - out["ema22"]) / out["atr"]
    out["bull_reversal"] = out["close"] > out["prev_high"]
    out["bear_reversal"] = out["close"] < out["prev_low"]

    out.dropna(inplace=True)
    return out


def long_signal(row: pd.Series) -> bool:
    impulse = row["swing_high"] - row["low"]
    return (
        row["ema_slope"] < 0
        and row["stretch_long"] >= STRETCH_ATR
        and row["bull_reversal"]
        and impulse >= row["atr"] * MIN_IMPULSE_ATR
    )


def short_signal(row: pd.Series) -> bool:
    impulse = row["high"] - row["swing_low"]
    return (
        row["ema_slope"] > 0
        and row["stretch_short"] >= STRETCH_ATR
        and row["bear_reversal"]
        and impulse >= row["atr"] * MIN_IMPULSE_ATR
    )


def calc_long_target_stop(row: pd.Series) -> tuple[float, float]:
    impulse = row["swing_high"] - row["low"]
    target = row["low"] + impulse * TARGET_RETRACE
    stop = row["low"] - row["atr"] * STOP_ATR_BUFFER
    return float(target), float(stop)


def calc_short_target_stop(row: pd.Series) -> tuple[float, float]:
    impulse = row["high"] - row["swing_low"]
    target = row["high"] - impulse * TARGET_RETRACE
    stop = row["high"] + row["atr"] * STOP_ATR_BUFFER
    return float(target), float(stop)


def pnl(side: str, entry: float, exit_price: float) -> float:
    raw = (exit_price - entry) if side == "LONG" else (entry - exit_price)
    return raw * POINT_VALUE * CONTRACTS


def is_trade_time(ts) -> bool:
    local_ts = pd.Timestamp(ts).tz_convert(US_TZ)
    hhmm = local_ts.hour * 100 + local_ts.minute
    mins_from_open = (local_ts.hour * 60 + local_ts.minute) - (9 * 60 + 30)

    if ENTRY_MIN_FROM_OPEN is not None and mins_from_open < ENTRY_MIN_FROM_OPEN:
        return False
    if ENTRY_MAX_FROM_OPEN is not None and mins_from_open > ENTRY_MAX_FROM_OPEN:
        return False

    if TIME_FILTER_MODE == "off":
        return True

    if TIME_FILTER_MODE == "regular":
        return 930 <= hhmm <= 1600
    if TIME_FILTER_MODE == "opening":
        return 930 <= hhmm <= 1130
    return True


def run_backtest(df: pd.DataFrame) -> tuple[list[Trade], pd.DataFrame]:
    trades: list[Trade] = []
    equity = START_CAPITAL
    equity_curve = []

    i = 1
    while i < len(df) - 1:
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        signal_side = None
        target = stop = entry = None

        if long_signal(row):
            signal_side = "LONG"
            target, stop = calc_long_target_stop(row)
        elif short_signal(row):
            signal_side = "SHORT"
            target, stop = calc_short_target_stop(row)

        if signal_side is None:
            equity_curve.append((df.index[i], equity))
            i += 1
            continue

        if not is_trade_time(df.index[i]):
            equity_curve.append((df.index[i], equity))
            i += 1
            continue

        entry = float(next_row["open"])
        if signal_side == "LONG":
            target_distance = target - entry
        else:
            target_distance = entry - target

        if target_distance < MIN_TARGET_TICKS * TICK_SIZE:
            equity_curve.append((df.index[i], equity))
            i += 1
            continue

        entry_idx = i + 1
        exit_price = None
        exit_time = None
        reason = None
        bars_held = 0

        for j in range(entry_idx, min(entry_idx + MAX_HOLD_BARS, len(df))):
            bar = df.iloc[j]
            bars_held += 1

            if signal_side == "LONG":
                hit_stop = float(bar["low"]) <= stop
                hit_target = float(bar["high"]) >= target
                if hit_stop and hit_target:
                    exit_price = stop
                    reason = "same_bar_stop_first"
                    exit_time = df.index[j]
                    break
                if hit_stop:
                    exit_price = stop
                    reason = "stop"
                    exit_time = df.index[j]
                    break
                if hit_target:
                    exit_price = target
                    reason = "target_25pct"
                    exit_time = df.index[j]
                    break
            else:
                hit_stop = float(bar["high"]) >= stop
                hit_target = float(bar["low"]) <= target
                if hit_stop and hit_target:
                    exit_price = stop
                    reason = "same_bar_stop_first"
                    exit_time = df.index[j]
                    break
                if hit_stop:
                    exit_price = stop
                    reason = "stop"
                    exit_time = df.index[j]
                    break
                if hit_target:
                    exit_price = target
                    reason = "target_25pct"
                    exit_time = df.index[j]
                    break

        if exit_price is None:
            forced_idx = min(entry_idx + MAX_HOLD_BARS - 1, len(df) - 1)
            exit_price = float(df.iloc[forced_idx]["close"])
            exit_time = df.index[forced_idx]
            reason = "time_exit"
            bars_held = forced_idx - entry_idx + 1

        gross = pnl(signal_side, entry, exit_price)
        net = gross - (COMMISSION_PER_SIDE * 2 * CONTRACTS)
        equity += net
        ret_pct = (net / START_CAPITAL) * 100.0

        trades.append(
            Trade(
                side=signal_side,
                entry_time=str(df.index[entry_idx]),
                exit_time=str(exit_time),
                entry=entry,
                exit=exit_price,
                stop=float(stop),
                target=float(target),
                bars_held=bars_held,
                reason=reason,
                gross_pnl=gross,
                net_pnl=net,
                ret_on_capital_pct=ret_pct,
            )
        )
        equity_curve.append((exit_time, equity))

        # 같은 봉 재진입 방지
        i = df.index.get_loc(exit_time) + 1

    eq_df = pd.DataFrame(equity_curve, columns=["time", "equity"]).drop_duplicates(subset=["time"])
    if len(eq_df) == 0:
        eq_df = pd.DataFrame({"time": [df.index[0]], "equity": [START_CAPITAL]})
    eq_df.set_index("time", inplace=True)
    return trades, eq_df


def summarize(trades: list[Trade], eq_df: pd.DataFrame) -> dict:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "final_equity": START_CAPITAL,
            "return_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_trade_pnl": 0.0,
        }

    trade_df = pd.DataFrame([asdict(t) for t in trades])
    wins = trade_df[trade_df["net_pnl"] > 0]
    losses = trade_df[trade_df["net_pnl"] <= 0]
    gross_profit = wins["net_pnl"].sum()
    gross_loss = abs(losses["net_pnl"].sum())
    final_equity = float(eq_df["equity"].iloc[-1])
    cummax = eq_df["equity"].cummax()
    dd = (eq_df["equity"] / cummax - 1.0) * 100.0

    return {
        "trades": int(len(trade_df)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": float(len(wins) / len(trade_df) * 100.0),
        "net_pnl": float(trade_df["net_pnl"].sum()),
        "final_equity": final_equity,
        "return_pct": float((final_equity / START_CAPITAL - 1.0) * 100.0),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "max_drawdown_pct": float(dd.min()),
        "avg_trade_pnl": float(trade_df["net_pnl"].mean()),
    }


def save_outputs(df: pd.DataFrame, trades: list[Trade], eq_df: pd.DataFrame) -> None:
    trade_df = pd.DataFrame([asdict(t) for t in trades]) if trades else pd.DataFrame()
    bars_path = OUTPUT_DIR / "mnq_1m_bars.csv"
    trades_path = OUTPUT_DIR / "mnq_1m_25pct_trades.csv"
    equity_path = OUTPUT_DIR / "mnq_1m_25pct_equity.csv"
    plot_path = OUTPUT_DIR / "mnq_1m_25pct_equity.png"

    df.to_csv(bars_path)
    trade_df.to_csv(trades_path, index=False)
    eq_df.to_csv(equity_path)

    plt.figure(figsize=(12, 5))
    plt.plot(eq_df.index, eq_df["equity"], label="Equity")
    plt.title("MNQ 1m 25% Retrace Strategy Equity Curve")
    plt.xlabel("Time")
    plt.ylabel("Equity ($)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(plot_path, dpi=160)
    plt.close()

    print("\n[저장 파일]")
    print(bars_path)
    print(trades_path)
    print(equity_path)
    print(plot_path)


def main():
    print(f"MNQ 1분봉 백테스트 시작: ticker={TICKER}, period={PERIOD}, interval={INTERVAL}")
    df = load_mnq_1m()
    df = add_indicators(df)
    trades, eq_df = run_backtest(df)
    stats = summarize(trades, eq_df)
    save_outputs(df, trades, eq_df)

    print("\n================ SUMMARY ================")
    print(f"ticker: {TICKER}")
    print(f"bars: {len(df):,}")
    print(f"trades: {stats['trades']}")
    print(f"wins/losses: {stats['wins']}/{stats['losses']}")
    print(f"win_rate: {stats['win_rate']:.2f}%")
    print(f"net_pnl: ${stats['net_pnl']:.2f}")
    print(f"final_equity: ${stats['final_equity']:.2f}")
    print(f"return: {stats['return_pct']:.2f}%")
    print(f"profit_factor: {stats['profit_factor']:.2f}")
    print(f"max_drawdown: {stats['max_drawdown_pct']:.2f}%")
    print(f"avg_trade_pnl: ${stats['avg_trade_pnl']:.2f}")

    if trades:
        print("\n[최근 10건]")
        trade_df = pd.DataFrame([asdict(t) for t in trades])
        print(trade_df.tail(10).to_string(index=False))
    else:
        print("\n체결된 거래가 없습니다. 파라미터를 완화해 보세요.")


if __name__ == "__main__":
    main()
