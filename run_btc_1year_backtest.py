# -*- coding: utf-8 -*-
'''
BTCUSDT 1분봉 1년치 25% 되돌림 전략 백테스트.

MNQ 전략과 동일한 신호 규칙을 암호화폐에 이식:
- 22EMA 역추세 + stretch 기반 진입
- 25% 되돌림 익절, ATR 기반 손절
- 40분 시간청산

차이점:
- 24/7 거래 (개장 필터 무의미)
- Position = fractional BTC로 $10k notional 고정
- Commission = Binance 표준 0.1% × 2방향
- MIN_TARGET_TICKS 대신 MIN_TARGET_PCT 사용
'''
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


CSV_PATH = Path("/Users/yonghyuk/newcodex/mnq_backtest_output/btc_1m_binance.csv")
OUT_DIR = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")

# === 경제 파라미터 ===
START_CAPITAL = 10_000.0
NOTIONAL_PER_TRADE = 10_000.0       # 거래당 노출 $ 고정
COMMISSION_RATE = 0.001             # Binance 현물 maker/taker 0.1%
MIN_TARGET_PCT = 0.004              # 최소 0.4% 목표 (수수료 0.2% 커버 + 0.2% 이상 순수익)

# === 전략 파라미터 (기본은 MNQ와 동일) ===
EMA_LEN = 22
ATR_LEN = 14
SWING_LOOKBACK = 30
STRETCH_ATR = 1.4
MAX_HOLD_BARS = 40
TARGET_RETRACE = 0.25
STOP_ATR_BUFFER = 0.45
MIN_IMPULSE_ATR = 1.8


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
    return_pct: float


# ============ numpy-based rolling (pandas 2.3.3 bug 우회) ============
def _rolling_mean_np(arr, window):
    out = np.full(len(arr), np.nan, dtype=np.float64)
    cs = np.concatenate(([0.0], np.cumsum(arr, dtype=np.float64)))
    out[window - 1:] = (cs[window:] - cs[:-window]) / window
    return out


def _rolling_max_np(arr, window):
    out = np.full(len(arr), np.nan, dtype=np.float64)
    # chunked으로 조금 빠르게
    a = np.asarray(arr, dtype=np.float64)
    n = len(a)
    for i in range(window - 1, n):
        out[i] = a[i - window + 1:i + 1].max()
    return out


def _rolling_min_np(arr, window):
    out = np.full(len(arr), np.nan, dtype=np.float64)
    a = np.asarray(arr, dtype=np.float64)
    n = len(a)
    for i in range(window - 1, n):
        out[i] = a[i - window + 1:i + 1].min()
    return out


def add_indicators(df, ema_len=EMA_LEN, atr_len=ATR_LEN, swing=SWING_LOOKBACK):
    out = df.copy()
    out['ema22'] = out['close'].ewm(span=ema_len, adjust=False).mean()
    out['ema_slope'] = out['ema22'].diff()
    prev_close = out['close'].shift(1)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = _rolling_mean_np(tr.values, atr_len)
    sw_hi = _rolling_max_np(out['high'].values, swing)
    sw_lo = _rolling_min_np(out['low'].values, swing)
    out['swing_high'] = np.concatenate(([np.nan], sw_hi[:-1]))
    out['swing_low'] = np.concatenate(([np.nan], sw_lo[:-1]))
    out['prev_high'] = out['high'].shift(1)
    out['prev_low'] = out['low'].shift(1)
    out['stretch_long'] = (out['ema22'] - out['low']) / out['atr']
    out['stretch_short'] = (out['high'] - out['ema22']) / out['atr']
    out['bull_reversal'] = out['close'] > out['prev_high']
    out['bear_reversal'] = out['close'] < out['prev_low']
    out.dropna(inplace=True)
    return out


def long_signal(row, stretch_atr, min_impulse_atr):
    impulse = row['swing_high'] - row['low']
    return (
        row['ema_slope'] < 0
        and row['stretch_long'] >= stretch_atr
        and row['bull_reversal']
        and impulse >= row['atr'] * min_impulse_atr
    )


def short_signal(row, stretch_atr, min_impulse_atr):
    impulse = row['high'] - row['swing_low']
    return (
        row['ema_slope'] > 0
        and row['stretch_short'] >= stretch_atr
        and row['bear_reversal']
        and impulse >= row['atr'] * min_impulse_atr
    )


def calc_long_target_stop(row, retrace, stop_atr_buffer):
    impulse = row['swing_high'] - row['low']
    target = row['low'] + impulse * retrace
    stop = row['low'] - row['atr'] * stop_atr_buffer
    return float(target), float(stop)


def calc_short_target_stop(row, retrace, stop_atr_buffer):
    impulse = row['high'] - row['swing_low']
    target = row['high'] - impulse * retrace
    stop = row['high'] + row['atr'] * stop_atr_buffer
    return float(target), float(stop)


def run_backtest(df: pd.DataFrame,
                 stretch_atr=STRETCH_ATR,
                 retrace=TARGET_RETRACE,
                 stop_atr_buffer=STOP_ATR_BUFFER,
                 min_impulse_atr=MIN_IMPULSE_ATR,
                 max_hold_bars=MAX_HOLD_BARS,
                 hour_filter=None):
    '''hour_filter: set of UTC hours allowed (None = 24시간 전부)'''
    trades = []
    equity = START_CAPITAL
    equity_curve = [(df.index[0], equity)]

    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    # 컬럼 위치를 미리 잡아두면 iloc보다 빠르다
    cols = {c: df.columns.get_loc(c) for c in df.columns}
    arr = df.values
    idx = df.index

    def row_view(i):
        # iloc 없이 record 반환
        return {k: arr[i, v] for k, v in cols.items()}

    n = len(df)
    i = 1
    while i < n - 1:
        row = row_view(i)

        # 시간대 필터
        if hour_filter is not None:
            hh = idx[i].hour
            if hh not in hour_filter:
                i += 1
                continue

        signal_side = None
        if long_signal(row, stretch_atr, min_impulse_atr):
            signal_side = 'LONG'
            target, stop = calc_long_target_stop(row, retrace, stop_atr_buffer)
        elif short_signal(row, stretch_atr, min_impulse_atr):
            signal_side = 'SHORT'
            target, stop = calc_short_target_stop(row, retrace, stop_atr_buffer)

        if signal_side is None:
            i += 1
            continue

        entry = float(opens[i + 1])
        if signal_side == 'LONG':
            target_dist = target - entry
        else:
            target_dist = entry - target

        # 최소 목표 비율 필터
        if target_dist <= 0 or (target_dist / entry) < MIN_TARGET_PCT:
            i += 1
            continue

        entry_idx = i + 1
        exit_price = None
        exit_time = None
        reason = None
        bars_held = 0

        end_j = min(entry_idx + max_hold_bars, n)
        for j in range(entry_idx, end_j):
            bars_held += 1
            if signal_side == 'LONG':
                hit_stop = lows[j] <= stop
                hit_target = highs[j] >= target
                if hit_stop and hit_target:
                    exit_price = stop
                    reason = 'same_bar_stop_first'
                elif hit_stop:
                    exit_price = stop
                    reason = 'stop'
                elif hit_target:
                    exit_price = target
                    reason = 'target_25pct'
            else:
                hit_stop = highs[j] >= stop
                hit_target = lows[j] <= target
                if hit_stop and hit_target:
                    exit_price = stop
                    reason = 'same_bar_stop_first'
                elif hit_stop:
                    exit_price = stop
                    reason = 'stop'
                elif hit_target:
                    exit_price = target
                    reason = 'target_25pct'
            if exit_price is not None:
                exit_time = idx[j]
                break

        if exit_price is None:
            forced = end_j - 1
            exit_price = float(closes[forced])
            exit_time = idx[forced]
            reason = 'time_exit'
            bars_held = forced - entry_idx + 1

        # Position size: fixed notional
        qty = NOTIONAL_PER_TRADE / entry
        raw_move = (exit_price - entry) if signal_side == 'LONG' else (entry - exit_price)
        gross = raw_move * qty
        # 수수료: 진입·청산 양쪽 노셔널 기준
        commission = (NOTIONAL_PER_TRADE * COMMISSION_RATE
                      + (exit_price * qty) * COMMISSION_RATE)
        net = gross - commission
        ret_pct = net / START_CAPITAL * 100.0
        equity += net

        trades.append(Trade(
            side=signal_side,
            entry_time=str(idx[entry_idx]),
            exit_time=str(exit_time),
            entry=entry,
            exit=exit_price,
            stop=float(stop),
            target=float(target),
            bars_held=bars_held,
            reason=reason,
            gross_pnl=gross,
            net_pnl=net,
            return_pct=ret_pct,
        ))
        equity_curve.append((exit_time, equity))
        # 같은 봉 재진입 방지
        i = idx.get_loc(exit_time) + 1

    eq_df = pd.DataFrame(equity_curve, columns=['time', 'equity']).drop_duplicates('time')
    eq_df.set_index('time', inplace=True)
    return trades, eq_df


def summarize(trades, eq_df):
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'net_pnl': 0, 'final_equity': START_CAPITAL, 'return_pct': 0,
                'profit_factor': 0, 'max_drawdown_pct': 0, 'avg_trade_pnl': 0,
                'avg_win': 0, 'avg_loss': 0}
    df = pd.DataFrame([asdict(t) for t in trades])
    wins = df[df['net_pnl'] > 0]
    losses = df[df['net_pnl'] <= 0]
    gp = wins['net_pnl'].sum()
    gl = abs(losses['net_pnl'].sum())
    final = float(eq_df['equity'].iloc[-1])
    cummax = eq_df['equity'].cummax()
    dd = (eq_df['equity'] / cummax - 1.0) * 100.0
    return {
        'trades': len(df),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(df) * 100.0,
        'net_pnl': float(df['net_pnl'].sum()),
        'final_equity': final,
        'return_pct': (final / START_CAPITAL - 1.0) * 100.0,
        'profit_factor': float(gp / gl) if gl > 0 else float('inf'),
        'max_drawdown_pct': float(dd.min()),
        'avg_trade_pnl': float(df['net_pnl'].mean()),
        'avg_win': float(wins['net_pnl'].mean()) if len(wins) else 0.0,
        'avg_loss': float(losses['net_pnl'].mean()) if len(losses) else 0.0,
    }


def load_csv():
    df = pd.read_csv(CSV_PATH, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    return df


def main():
    print(f"[load] {CSV_PATH}")
    base = load_csv()
    span_days = (base.index[-1] - base.index[0]).total_seconds() / 86400.0
    print(f"[load] rows={len(base):,}  {base.index[0]} ~ {base.index[-1]}  span={span_days:.1f}d")
    buyhold = (base['close'].iloc[-1] / base['close'].iloc[0] - 1.0) * 100.0
    print(f"[ref] buy-and-hold return: {buyhold:.2f}%")

    idf = add_indicators(base)
    print(f"[indicators] rows={len(idf):,}")

    # ========= 기본 파라미터 (MNQ와 동일) =========
    print("\n================ BASELINE (MNQ default params) ================")
    trades, eq = run_backtest(idf)
    stats = summarize(trades, eq)
    print(f"trades={stats['trades']}  win_rate={stats['win_rate']:.2f}%  net=${stats['net_pnl']:.2f}  "
          f"ret={stats['return_pct']:.2f}%  pf={stats['profit_factor']:.2f}  mdd={stats['max_drawdown_pct']:.2f}%")
    print(f"avg_win=${stats['avg_win']:.2f}  avg_loss=${stats['avg_loss']:.2f}")

    # Trade-level 분석
    td = pd.DataFrame([asdict(t) for t in trades])
    if not td.empty:
        td['entry_ts'] = pd.to_datetime(td['entry_time'])
        td['hour_utc'] = td['entry_ts'].dt.hour
        td['weekday'] = td['entry_ts'].dt.day_name()
        td['reason_grp'] = td['reason']
        td['month'] = td['entry_ts'].dt.to_period('M').astype(str)
        td.to_csv(OUT_DIR / 'btc_1year_baseline_trades.csv', index=False)

        print("\n[reason]")
        print(td.groupby('reason_grp').agg(n=('net_pnl', 'count'),
                                            net=('net_pnl', 'sum'),
                                            avg=('net_pnl', 'mean')).round(2).to_string())

        print("\n[hour_utc buckets]  (UTC 기준)")
        hour_grp = td.groupby('hour_utc').agg(n=('net_pnl', 'count'),
                                               net=('net_pnl', 'sum'),
                                               avg=('net_pnl', 'mean'),
                                               wr=('net_pnl', lambda s: (s > 0).mean() * 100))
        print(hour_grp.round(2).to_string())
        hour_grp.to_csv(OUT_DIR / 'btc_1year_baseline_by_hour.csv')

        print("\n[weekday]")
        wd_grp = td.groupby('weekday').agg(n=('net_pnl', 'count'),
                                            net=('net_pnl', 'sum'),
                                            avg=('net_pnl', 'mean'),
                                            wr=('net_pnl', lambda s: (s > 0).mean() * 100))
        wd_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        wd_grp = wd_grp.reindex([w for w in wd_order if w in wd_grp.index])
        print(wd_grp.round(2).to_string())
        wd_grp.to_csv(OUT_DIR / 'btc_1year_baseline_by_weekday.csv')

        print("\n[monthly]")
        m_grp = td.groupby('month').agg(n=('net_pnl', 'count'),
                                         net=('net_pnl', 'sum'),
                                         avg=('net_pnl', 'mean'),
                                         wr=('net_pnl', lambda s: (s > 0).mean() * 100))
        print(m_grp.round(2).to_string())
        m_grp.to_csv(OUT_DIR / 'btc_1year_baseline_monthly.csv')

    # ========= 파라미터 스윕 =========
    print("\n================ PARAMETER SWEEP ================")
    variants = []
    configs = [
        # (label, stretch, retrace, stop_buf, impulse)
        ('baseline(1.4,0.25,0.45,1.8)', 1.4, 0.25, 0.45, 1.8),
        ('wider_target_0.50',            1.4, 0.50, 0.45, 1.8),
        ('wider_target_0.75',            1.4, 0.75, 0.45, 1.8),
        ('wider_target_1.00',            1.4, 1.00, 0.45, 1.8),
        ('tight_stop_0.25',              1.4, 0.25, 0.25, 1.8),
        ('strict_stretch_2.0',           2.0, 0.50, 0.45, 1.8),
        ('strict_stretch_2.5',           2.5, 0.50, 0.45, 1.8),
        ('strict_stretch_3.0',           3.0, 0.50, 0.45, 1.8),
        ('strict_impulse_3.0',           1.4, 0.50, 0.45, 3.0),
        ('combo_A(2.0,0.50,0.25,2.5)',   2.0, 0.50, 0.25, 2.5),
        ('combo_B(2.5,0.75,0.30,3.0)',   2.5, 0.75, 0.30, 3.0),
        ('combo_C(2.5,1.00,0.45,3.0)',   2.5, 1.00, 0.45, 3.0),
        ('combo_D(3.0,1.00,0.45,3.0)',   3.0, 1.00, 0.45, 3.0),
        ('combo_E(3.0,0.75,0.30,3.0)',   3.0, 0.75, 0.30, 3.0),
    ]
    for label, s, r, sb, mi in configs:
        tr, eq = run_backtest(idf, stretch_atr=s, retrace=r,
                              stop_atr_buffer=sb, min_impulse_atr=mi)
        st = summarize(tr, eq)
        variants.append({'label': label, 'stretch': s, 'retrace': r,
                         'stop_buf': sb, 'impulse': mi, **st})
    var_df = pd.DataFrame(variants).sort_values('net_pnl', ascending=False).reset_index(drop=True)
    print(var_df.to_string(index=False))
    var_df.to_csv(OUT_DIR / 'btc_1year_variant_grid.csv', index=False)

    # ========= 시간대 필터 실험 (UTC 기준 상위 버킷) =========
    print("\n================ HOUR FILTER (baseline params) ================")
    # 상위 4개 UTC 시간대 선택
    if not td.empty:
        best_hours = hour_grp.sort_values('avg', ascending=False).head(6).index.tolist()
        print(f"top-6 hours by avg pnl: {best_hours}")
        tr, eq = run_backtest(idf, hour_filter=set(best_hours))
        st = summarize(tr, eq)
        print(f"trades={st['trades']}  win_rate={st['win_rate']:.2f}%  net=${st['net_pnl']:.2f}  "
              f"ret={st['return_pct']:.2f}%  pf={st['profit_factor']:.2f}  mdd={st['max_drawdown_pct']:.2f}%")

    print("\n================ BUY & HOLD BENCHMARK ================")
    first = float(base['close'].iloc[0])
    last = float(base['close'].iloc[-1])
    bh_ret = (last / first - 1.0) * 100.0
    print(f"BTC: {first:,.2f} → {last:,.2f}  return={bh_ret:.2f}%")


if __name__ == "__main__":
    main()
