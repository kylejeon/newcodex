# -*- coding: utf-8 -*-
'''
MNQ 1m opening bot (best_90_120)

목적:
- MNQ 1분봉 해석형 전략의 실시간 감시/알림/상태관리 봇
- 현재 기준 전략: best_90_120 + MIN_TARGET_TICKS=6
- 기존 봇처럼 1분마다 실행되며 상태 JSON과 텔레그램 알림을 사용

중요:
- 이 저장소에는 MNQ 실주문 브로커 어댑터가 없어서 기본값은 PAPER_TRADING=True 입니다.
- 즉시 실주문이 아니라 "paper/live-adapter-ready" 구조입니다.
- 나중에 broker adapter 부분만 교체하면 실주문 연결이 가능합니다.
'''

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

import telegram_alert


# ===== Strategy constants =====
TICKER = 'MNQ=F'
POINT_VALUE = 2.0
CONTRACTS = int(os.environ.get('MNQ_CONTRACTS', '1'))
COMMISSION_PER_SIDE = float(os.environ.get('MNQ_COMMISSION_PER_SIDE', '1.2'))
TICK_SIZE = 0.25
MIN_TARGET_TICKS = 6

EMA_LEN = 22
ATR_LEN = 14
SWING_LOOKBACK = 30
STRETCH_ATR = 1.4
MAX_HOLD_BARS = 40
TARGET_RETRACE = 0.25
STOP_ATR_BUFFER = 0.45
MIN_IMPULSE_ATR = 1.8

US_TZ = ZoneInfo('America/New_York')
KST_TZ = ZoneInfo('Asia/Seoul')
PAPER_TRADING = os.environ.get('MNQ_PAPER_TRADING', '1') != '0'

# best_90_120
ENTRY_MIN_FROM_OPEN = 90
ENTRY_MAX_FROM_OPEN = 120
BOT_NAME = 'MNQ_1m_best_90_120'
PORTFOLIO_NAME = 'MNQ 1분봉 25% 되돌림 전략'
AUTOBOT_DATA_DIR = os.environ.get(
    'AUTOBOT_DATA_DIR',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'autobot_data'),
)
os.makedirs(AUTOBOT_DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(AUTOBOT_DATA_DIR, f'{BOT_NAME}_state.json')
TRADE_LOG_FILE = os.path.join(AUTOBOT_DATA_DIR, f'{BOT_NAME}_trades.jsonl')


@dataclass
class PositionState:
    side: str
    entry_time: str
    entry_price: float
    stop_price: float
    target_price: float
    entry_bar_index: int
    bars_held: int
    signal_time: str
    reason: str


@dataclass
class BotState:
    last_checked_bar: str
    last_signal_bar: str
    position: Optional[dict]


def _json_safe(v):
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_json_safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def load_state() -> BotState:
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return BotState(**raw)
    except Exception:
        return BotState(last_checked_bar='', last_signal_bar='', position=None)


def save_state(state: BotState):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(_json_safe(asdict(state)), f, ensure_ascii=False)


def append_trade_log(row: dict):
    with open(TRADE_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(_json_safe(row), ensure_ascii=False) + '\n')


def send(msg: str):
    print(msg)
    telegram_alert.SendMessage(msg)


def fmt_ts(ts_str: str, tz_name: str = 'Asia/Seoul') -> str:
    ts = pd.Timestamp(ts_str)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    return ts.tz_convert(tz_name).strftime('%m-%d %H:%M')


def fmt_px(v: float) -> str:
    return f'{v:,.2f}'


def build_entry_message(pos: PositionState, mins_from_open: int) -> str:
    mode = 'PAPER' if PAPER_TRADING else 'LIVE'
    return (
        f'[{mode}] {PORTFOLIO_NAME}\\n'
        f'진입: {pos.side} {CONTRACTS}계약\\n'
        f'신호시각: {fmt_ts(pos.signal_time)}\\n'
        f'진입시각: {fmt_ts(pos.entry_time)}\\n'
        f'진입가: {fmt_px(pos.entry_price)}\\n'
        f'목표가: {fmt_px(pos.target_price)}\\n'
        f'손절가: {fmt_px(pos.stop_price)}\\n'
        f'개장후: {mins_from_open}분'
    )


def build_hold_message(pos: PositionState) -> str:
    mode = 'PAPER' if PAPER_TRADING else 'LIVE'
    return (
        f'[{mode}] {PORTFOLIO_NAME} 보유중\\n'
        f'포지션: {pos.side} {CONTRACTS}계약\\n'
        f'진입시각: {fmt_ts(pos.entry_time)}\\n'
        f'진입가: {fmt_px(pos.entry_price)}\\n'
        f'목표가: {fmt_px(pos.target_price)}\\n'
        f'손절가: {fmt_px(pos.stop_price)}\\n'
        f'보유바수: {pos.bars_held}'
    )


def build_exit_message(pos: PositionState, exit_price: float, reason: str, net: float) -> str:
    mode = 'PAPER' if PAPER_TRADING else 'LIVE'
    return (
        f'[{mode}] {PORTFOLIO_NAME} 청산\\n'
        f'포지션: {pos.side} {CONTRACTS}계약\\n'
        f'청산사유: {reason}\\n'
        f'진입가: {fmt_px(pos.entry_price)}\\n'
        f'청산가: {fmt_px(exit_price)}\\n'
        f'목표가: {fmt_px(pos.target_price)}\\n'
        f'손절가: {fmt_px(pos.stop_price)}\\n'
        f'손익: ${net:,.2f}'
    )


def fetch_intraday() -> pd.DataFrame:
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=7)
    df = yf.download(
        TICKER,
        start=start_dt,
        end=end_dt,
        interval='1m',
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or len(df) == 0:
        raise RuntimeError('MNQ 1분봉 데이터를 가져오지 못했습니다.')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.lower)
    df = df[['open', 'high', 'low', 'close', 'volume']].copy()
    df.dropna(inplace=True)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['ema22'] = out['close'].ewm(span=EMA_LEN, adjust=False).mean()
    out['ema_slope'] = out['ema22'].diff()

    prev_close = out['close'].shift(1)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = tr.rolling(ATR_LEN).mean()
    out['swing_high'] = out['high'].rolling(SWING_LOOKBACK).max().shift(1)
    out['swing_low'] = out['low'].rolling(SWING_LOOKBACK).min().shift(1)
    out['prev_high'] = out['high'].shift(1)
    out['prev_low'] = out['low'].shift(1)
    out['stretch_long'] = (out['ema22'] - out['low']) / out['atr']
    out['stretch_short'] = (out['high'] - out['ema22']) / out['atr']
    out['bull_reversal'] = out['close'] > out['prev_high']
    out['bear_reversal'] = out['close'] < out['prev_low']
    out.dropna(inplace=True)
    return out


def long_signal(row: pd.Series) -> bool:
    impulse = row['swing_high'] - row['low']
    return (
        row['ema_slope'] < 0
        and row['stretch_long'] >= STRETCH_ATR
        and row['bull_reversal']
        and impulse >= row['atr'] * MIN_IMPULSE_ATR
    )


def short_signal(row: pd.Series) -> bool:
    impulse = row['high'] - row['swing_low']
    return (
        row['ema_slope'] > 0
        and row['stretch_short'] >= STRETCH_ATR
        and row['bear_reversal']
        and impulse >= row['atr'] * MIN_IMPULSE_ATR
    )


def calc_long_target_stop(row: pd.Series) -> tuple[float, float]:
    impulse = row['swing_high'] - row['low']
    target = row['low'] + impulse * TARGET_RETRACE
    stop = row['low'] - row['atr'] * STOP_ATR_BUFFER
    return float(target), float(stop)


def calc_short_target_stop(row: pd.Series) -> tuple[float, float]:
    impulse = row['high'] - row['swing_low']
    target = row['high'] - impulse * TARGET_RETRACE
    stop = row['high'] + row['atr'] * STOP_ATR_BUFFER
    return float(target), float(stop)


def pnl(side: str, entry: float, exit_price: float) -> float:
    raw = (exit_price - entry) if side == 'LONG' else (entry - exit_price)
    return raw * POINT_VALUE * CONTRACTS


def minutes_from_open(ts) -> int:
    local_ts = pd.Timestamp(ts).tz_convert(US_TZ)
    return (local_ts.hour * 60 + local_ts.minute) - (9 * 60 + 30)


def is_entry_time(ts) -> bool:
    mins = minutes_from_open(ts)
    return ENTRY_MIN_FROM_OPEN <= mins <= ENTRY_MAX_FROM_OPEN


def market_is_open_now() -> bool:
    now_et = datetime.now(US_TZ)
    if now_et.weekday() >= 5:
        return False
    hhmm = now_et.hour * 100 + now_et.minute
    return 930 <= hhmm <= 1600


def place_order(side: str, qty: int, price_hint: float, reason: str) -> dict:
    # Placeholder adapter. Replace this function when real futures broker API is available.
    return {
        'paper': PAPER_TRADING,
        'side': side,
        'qty': qty,
        'price_hint': price_hint,
        'reason': reason,
        'time': datetime.now(timezone.utc).isoformat(),
        'status': 'FILLED_PAPER' if PAPER_TRADING else 'NOT_IMPLEMENTED',
    }


def make_entry_from_signal(df: pd.DataFrame, row: pd.Series, signal_side: str, signal_idx: int) -> Optional[PositionState]:
    entry = float(df.iloc[signal_idx + 1]['open'])
    if signal_side == 'LONG':
        target, stop = calc_long_target_stop(row)
        target_distance = target - entry
    else:
        target, stop = calc_short_target_stop(row)
        target_distance = entry - target

    if target_distance < MIN_TARGET_TICKS * TICK_SIZE:
        return None

    return PositionState(
        side=signal_side,
        entry_time=str(df.index[signal_idx + 1]),
        entry_price=entry,
        stop_price=float(stop),
        target_price=float(target),
        entry_bar_index=int(signal_idx + 1),
        bars_held=0,
        signal_time=str(df.index[signal_idx]),
        reason='signal_entry',
    )


def check_exit(pos: PositionState, current_bar: pd.Series, current_time, current_idx: int):
    exit_price = None
    reason = None
    if pos.side == 'LONG':
        hit_stop = float(current_bar['low']) <= pos.stop_price
        hit_target = float(current_bar['high']) >= pos.target_price
        if hit_stop and hit_target:
            exit_price = pos.stop_price
            reason = 'same_bar_stop_first'
        elif hit_stop:
            exit_price = pos.stop_price
            reason = 'stop'
        elif hit_target:
            exit_price = pos.target_price
            reason = 'target_25pct'
    else:
        hit_stop = float(current_bar['high']) >= pos.stop_price
        hit_target = float(current_bar['low']) <= pos.target_price
        if hit_stop and hit_target:
            exit_price = pos.stop_price
            reason = 'same_bar_stop_first'
        elif hit_stop:
            exit_price = pos.stop_price
            reason = 'stop'
        elif hit_target:
            exit_price = pos.target_price
            reason = 'target_25pct'

    bars_held = current_idx - pos.entry_bar_index + 1
    if exit_price is None and bars_held >= MAX_HOLD_BARS:
        exit_price = float(current_bar['close'])
        reason = 'time_exit'

    return exit_price, reason, bars_held


def main():
    state = load_state()
    now_kst = datetime.now(KST_TZ)
    print(now_kst)

    if not market_is_open_now():
        print('미국 정규장이 아닙니다.')
        return

    df = add_indicators(fetch_intraday())
    if len(df) < 3:
        print('데이터 부족')
        return

    # Use last fully available bar as decision bar.
    last_idx = len(df) - 2
    row = df.iloc[last_idx]
    signal_bar_time = str(df.index[last_idx])

    if state.last_checked_bar == signal_bar_time and state.position is None:
        print('이미 점검한 최신 바입니다.')
        return

    if state.position is not None:
        pos = PositionState(**state.position)
        current_bar = df.iloc[-1]
        current_time = df.index[-1]
        exit_price, reason, bars_held = check_exit(pos, current_bar, current_time, len(df) - 1)
        pos.bars_held = bars_held

        if exit_price is None:
            state.position = asdict(pos)
            state.last_checked_bar = str(df.index[-1])
            save_state(state)
            print(build_hold_message(pos))
            return

        order = place_order('SELL' if pos.side == 'LONG' else 'BUY', CONTRACTS, exit_price, reason)
        gross = pnl(pos.side, pos.entry_price, exit_price)
        net = gross - (COMMISSION_PER_SIDE * 2 * CONTRACTS)
        msg = build_exit_message(pos, exit_price, reason, net)
        send(msg)
        append_trade_log({
            'type': 'EXIT',
            'position': asdict(pos),
            'exit_price': exit_price,
            'exit_reason': reason,
            'gross_pnl': gross,
            'net_pnl': net,
            'order': order,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        state.position = None
        state.last_checked_bar = str(df.index[-1])
        save_state(state)
        return

    if not is_entry_time(df.index[last_idx]):
        state.last_checked_bar = signal_bar_time
        save_state(state)
        print('진입 허용 시간대가 아닙니다.')
        return

    signal_side = None
    if long_signal(row):
        signal_side = 'LONG'
    elif short_signal(row):
        signal_side = 'SHORT'

    if signal_side is None:
        state.last_checked_bar = signal_bar_time
        save_state(state)
        print('신호 없음')
        return

    if state.last_signal_bar == signal_bar_time:
        print('이미 처리한 신호 바입니다.')
        return

    pos = make_entry_from_signal(df, row, signal_side, last_idx)
    state.last_checked_bar = signal_bar_time
    state.last_signal_bar = signal_bar_time

    if pos is None:
        save_state(state)
        print('최소 목표틱 미충족으로 진입 거부')
        return

    order = place_order('BUY' if signal_side == 'LONG' else 'SELL', CONTRACTS, pos.entry_price, 'entry')
    state.position = asdict(pos)
    save_state(state)

    mins = minutes_from_open(df.index[last_idx])
    msg = build_entry_message(pos, mins)
    send(msg)
    append_trade_log({
        'type': 'ENTRY',
        'position': asdict(pos),
        'order': order,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })


if __name__ == '__main__':
    main()
