# -*- coding: utf-8 -*-
'''
BTC/ETH 온체인 메트릭 기반 전략 백테스트.

데이터: Coin Metrics Community API v4 (무료 티어)
- PriceUSD, CapMrktCurUSD, CapMVRVCur, AdrActCnt, TxCnt, SplyCur, HashRate
- 2018-01-01 ~ 현재, 일봉

전략:
  A. MVRV Z-Score Mean Reversion: Z<-0.5 long, Z>3.5 exit
  B. Active Address Momentum: 30dMA > 90dMA AND price > 200dMA
  C. Hash Ribbon (BTC only): 30dMA hashrate > 60dMA
  D. Ensemble: 2-of-3 positive = long

포지션: 바이너리 (100% asset / 100% cash)
수수료: 0.1% per trade side (Binance spot 기준, on/off 시 적용)
리밸런스: 일봉 종가 기준 판단, 다음 날 시가 체결 (look-ahead 방지)
'''
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


DATA_DIR = Path("/Users/yonghyuk/newcodex/mnq_backtest_output")
OUT_DIR = DATA_DIR

COMMISSION_RATE = 0.001  # 0.1% per side
START_CAPITAL = 10_000.0


def load_asset(asset: str) -> pd.DataFrame:
    path = DATA_DIR / f"onchain_{asset}_daily.csv"
    df = pd.read_csv(path, parse_dates=['time'], index_col='time')
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='last')]
    return df


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # ---- A. MVRV Z-Score ----
    mvrv = out['CapMVRVCur']
    mvrv_mean = mvrv.rolling(365, min_periods=180).mean()
    mvrv_std = mvrv.rolling(365, min_periods=180).std()
    out['mvrv_z'] = (mvrv - mvrv_mean) / mvrv_std

    # ---- B. Active Addresses Momentum ----
    act = out['AdrActCnt']
    out['act_ma30'] = act.rolling(30, min_periods=15).mean()
    out['act_ma90'] = act.rolling(90, min_periods=45).mean()
    out['price_ma200'] = out['PriceUSD'].rolling(200, min_periods=100).mean()

    # ---- C. Hash Ribbon ----
    if 'HashRate' in out.columns and out['HashRate'].notna().sum() > 100:
        hr = out['HashRate']
        out['hash_ma30'] = hr.rolling(30, min_periods=15).mean()
        out['hash_ma60'] = hr.rolling(60, min_periods=30).mean()
    else:
        out['hash_ma30'] = np.nan
        out['hash_ma60'] = np.nan

    # ---- D. TxCnt momentum (보조 지표로 보관) ----
    tx = out['TxCnt']
    out['tx_ma30'] = tx.rolling(30, min_periods=15).mean()
    out['tx_ma90'] = tx.rolling(90, min_periods=45).mean()

    return out


# ============ 각 전략의 "long 유지" 불리언 시그널 ============

def strategy_mvrv(df: pd.DataFrame, z_long=-0.5, z_exit=3.5) -> pd.Series:
    '''
    Z가 z_long 미만일 때 진입 → 이후 Z가 z_exit 넘으면 청산.
    그 사이에 z_exit까지 안 가면 계속 유지.
    신호는 상태 기반이라 hysteresis 적용.
    '''
    z = df['mvrv_z']
    sig = pd.Series(False, index=df.index)
    holding = False
    for i, v in enumerate(z.values):
        if np.isnan(v):
            holding = False
            sig.iloc[i] = False
            continue
        if not holding and v < z_long:
            holding = True
        elif holding and v > z_exit:
            holding = False
        sig.iloc[i] = holding
    return sig


def strategy_active_addresses(df: pd.DataFrame) -> pd.Series:
    cond = (df['act_ma30'] > df['act_ma90']) & (df['PriceUSD'] > df['price_ma200'])
    return cond.fillna(False)


def strategy_hash_ribbon(df: pd.DataFrame) -> pd.Series:
    if df['hash_ma30'].notna().sum() < 50:
        # ETH merge 이후 유효 데이터 부족 → 항상 False
        return pd.Series(False, index=df.index)
    cond = df['hash_ma30'] > df['hash_ma60']
    return cond.fillna(False)


def strategy_ensemble(df: pd.DataFrame) -> pd.Series:
    a = strategy_mvrv(df).astype(int)
    b = strategy_active_addresses(df).astype(int)
    c = strategy_hash_ribbon(df).astype(int)
    vote = a + b + c
    # Hash ribbon 자체가 무효한 자산(ETH)이면 2-of-2로 환산
    if c.sum() == 0:
        return (a + b) >= 2
    return vote >= 2


# ============ 백테스트 엔진 ============

@dataclass
class BtResult:
    name: str
    asset: str
    equity: pd.Series
    trades: pd.DataFrame
    stats: dict


def backtest_binary(df: pd.DataFrame, signal: pd.Series, name: str, asset: str) -> BtResult:
    '''
    signal이 True인 날의 다음날에 포지션을 잡고, False인 날의 다음날에 청산.
    포지션 상태를 1일 shift 해서 look-ahead 방지.
    '''
    df = df.copy()
    df['signal'] = signal.reindex(df.index).fillna(False)
    df['position'] = df['signal'].shift(1).fillna(False)  # 전날 신호 → 오늘 집행

    # 일간 가격 수익률
    df['ret'] = df['PriceUSD'].pct_change().fillna(0)

    # 포지션 전환 감지
    pos = df['position'].astype(int)
    change = pos.diff().fillna(pos.iloc[0]).astype(int)
    # 수수료: 포지션 켜짐/꺼짐 각 1회씩 0.1%
    fee = change.abs() * COMMISSION_RATE

    strat_ret = pos * df['ret'] - fee
    df['strat_ret'] = strat_ret
    df['equity'] = START_CAPITAL * (1 + strat_ret).cumprod()

    # 거래 로그: 포지션 on → off 사이 하나의 거래
    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    for i, (ts, row) in enumerate(df.iterrows()):
        if row['position'] and not in_pos:
            in_pos = True
            entry_idx = ts
            entry_price = row['PriceUSD']
        elif not row['position'] and in_pos:
            in_pos = False
            exit_price = row['PriceUSD']
            gross_ret = (exit_price / entry_price) - 1.0 - 2 * COMMISSION_RATE
            trades.append({
                'entry': entry_idx,
                'exit': ts,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'days_held': (ts - entry_idx).days,
                'gross_ret_pct': gross_ret * 100,
            })
    if in_pos and entry_idx is not None:
        exit_price = df['PriceUSD'].iloc[-1]
        gross_ret = (exit_price / entry_price) - 1.0 - 2 * COMMISSION_RATE
        trades.append({
            'entry': entry_idx,
            'exit': df.index[-1],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'days_held': (df.index[-1] - entry_idx).days,
            'gross_ret_pct': gross_ret * 100,
            'status': 'OPEN',
        })
    trade_df = pd.DataFrame(trades)

    equity = df['equity']
    cummax = equity.cummax()
    dd = (equity / cummax - 1) * 100
    final = float(equity.iloc[-1])

    wins = trade_df[trade_df['gross_ret_pct'] > 0] if not trade_df.empty else trade_df
    losses = trade_df[trade_df['gross_ret_pct'] <= 0] if not trade_df.empty else trade_df

    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = (final / START_CAPITAL) ** (1 / years) - 1 if years > 0 else 0
    vol = df['strat_ret'].std() * np.sqrt(365)
    sharpe = df['strat_ret'].mean() * 365 / vol if vol > 0 else 0

    stats = {
        'name': name,
        'asset': asset,
        'trades': len(trade_df),
        'wins': len(wins) if len(trade_df) else 0,
        'losses': len(losses) if len(trade_df) else 0,
        'win_rate_pct': (len(wins) / len(trade_df) * 100) if len(trade_df) else 0,
        'final_equity': final,
        'total_return_pct': (final / START_CAPITAL - 1) * 100,
        'cagr_pct': cagr * 100,
        'max_drawdown_pct': float(dd.min()),
        'sharpe_annualized': sharpe,
        'avg_days_held': float(trade_df['days_held'].mean()) if len(trade_df) else 0,
        'avg_trade_ret_pct': float(trade_df['gross_ret_pct'].mean()) if len(trade_df) else 0,
        'time_in_market_pct': float(df['position'].mean() * 100),
    }
    return BtResult(name=name, asset=asset, equity=equity, trades=trade_df, stats=stats)


def buy_and_hold(df: pd.DataFrame, asset: str) -> BtResult:
    df = df.copy()
    df['ret'] = df['PriceUSD'].pct_change().fillna(0)
    # 첫 날 진입 수수료, 마지막 날 청산 수수료
    fee_series = pd.Series(0.0, index=df.index)
    fee_series.iloc[0] = COMMISSION_RATE
    fee_series.iloc[-1] = COMMISSION_RATE
    df['strat_ret'] = df['ret'] - fee_series
    df['equity'] = START_CAPITAL * (1 + df['strat_ret']).cumprod()
    equity = df['equity']
    cummax = equity.cummax()
    dd = (equity / cummax - 1) * 100
    final = float(equity.iloc[-1])
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = (final / START_CAPITAL) ** (1 / years) - 1 if years > 0 else 0
    vol = df['strat_ret'].std() * np.sqrt(365)
    sharpe = df['strat_ret'].mean() * 365 / vol if vol > 0 else 0
    stats = {
        'name': 'Buy_and_Hold',
        'asset': asset,
        'trades': 1,
        'wins': 1 if final > START_CAPITAL else 0,
        'losses': 0 if final > START_CAPITAL else 1,
        'win_rate_pct': 100.0 if final > START_CAPITAL else 0.0,
        'final_equity': final,
        'total_return_pct': (final / START_CAPITAL - 1) * 100,
        'cagr_pct': cagr * 100,
        'max_drawdown_pct': float(dd.min()),
        'sharpe_annualized': sharpe,
        'avg_days_held': float((df.index[-1] - df.index[0]).days),
        'avg_trade_ret_pct': (final / START_CAPITAL - 1) * 100,
        'time_in_market_pct': 100.0,
    }
    return BtResult(name='Buy_and_Hold', asset=asset, equity=equity,
                     trades=pd.DataFrame(), stats=stats)


def slice_period(equity: pd.Series, start_date) -> pd.Series:
    slc = equity[equity.index >= start_date].copy()
    if len(slc) == 0:
        return slc
    base = slc.iloc[0]
    return slc / base * START_CAPITAL


def period_stats(name: str, asset: str, equity_slice: pd.Series) -> dict:
    if len(equity_slice) < 2:
        return {'name': name, 'asset': asset, 'n_days': 0,
                'total_return_pct': 0, 'cagr_pct': 0, 'max_dd_pct': 0, 'sharpe': 0}
    final = float(equity_slice.iloc[-1])
    ret = (final / START_CAPITAL - 1) * 100
    years = (equity_slice.index[-1] - equity_slice.index[0]).days / 365.25
    cagr = (final / START_CAPITAL) ** (1 / years) - 1 if years > 0 else 0
    daily_ret = equity_slice.pct_change().fillna(0)
    vol = daily_ret.std() * np.sqrt(365)
    sharpe = daily_ret.mean() * 365 / vol if vol > 0 else 0
    cummax = equity_slice.cummax()
    dd = (equity_slice / cummax - 1) * 100
    return {
        'name': name, 'asset': asset,
        'n_days': len(equity_slice),
        'total_return_pct': ret,
        'cagr_pct': cagr * 100,
        'max_dd_pct': float(dd.min()),
        'sharpe': sharpe,
    }


def run_for_asset(asset: str) -> list[BtResult]:
    df = load_asset(asset)
    df = compute_signals(df)

    # 지표가 충분히 성숙해진 시점부터 (365일 MVRV z-score 필요)
    df = df.loc[df['mvrv_z'].notna() | df['act_ma90'].notna()].copy()

    results = []

    sig_mvrv = strategy_mvrv(df)
    sig_act = strategy_active_addresses(df)
    sig_hash = strategy_hash_ribbon(df)
    sig_ens = strategy_ensemble(df)

    results.append(backtest_binary(df, sig_mvrv, 'A_MVRV_Z', asset))
    results.append(backtest_binary(df, sig_act, 'B_AddrMomentum', asset))
    results.append(backtest_binary(df, sig_hash, 'C_HashRibbon', asset))
    results.append(backtest_binary(df, sig_ens, 'D_Ensemble', asset))
    results.append(buy_and_hold(df, asset))
    return results


def main():
    all_results: list[BtResult] = []
    for asset in ('btc', 'eth'):
        print(f"\n==== {asset.upper()} ====")
        results = run_for_asset(asset)
        all_results.extend(results)
        for r in results:
            s = r.stats
            print(f"  {s['name']:<20}  "
                  f"final=${s['final_equity']:>12,.0f}  "
                  f"return={s['total_return_pct']:>8.1f}%  "
                  f"CAGR={s['cagr_pct']:>6.1f}%  "
                  f"MDD={s['max_drawdown_pct']:>6.1f}%  "
                  f"Sharpe={s['sharpe_annualized']:>5.2f}  "
                  f"trades={s['trades']:>3}  "
                  f"TIM={s['time_in_market_pct']:>5.1f}%")

    # 요약 CSV
    summary = pd.DataFrame([r.stats for r in all_results])
    summary.to_csv(OUT_DIR / 'onchain_strategy_summary.csv', index=False)

    # Period-sliced (1y, 3y, 5y, full)
    end = max(r.equity.index[-1] for r in all_results)
    windows = {
        '1y': end - pd.Timedelta(days=365),
        '3y': end - pd.Timedelta(days=365 * 3),
        '5y': end - pd.Timedelta(days=365 * 5),
    }
    period_rows = []
    for r in all_results:
        for label, start in windows.items():
            sliced = slice_period(r.equity, start)
            if len(sliced) < 30:
                continue
            ps = period_stats(r.name, r.asset, sliced)
            ps['period'] = label
            period_rows.append(ps)
    period_df = pd.DataFrame(period_rows)
    if not period_df.empty:
        period_df = period_df[['asset', 'period', 'name', 'n_days',
                                'total_return_pct', 'cagr_pct', 'max_dd_pct', 'sharpe']]
        period_df = period_df.sort_values(['asset', 'period', 'name'])
        period_df.to_csv(OUT_DIR / 'onchain_strategy_by_period.csv', index=False)
        print("\n==== BY PERIOD ====")
        # 각 기간별로 예쁘게
        for label in ['1y', '3y', '5y']:
            sub = period_df[period_df['period'] == label].copy()
            if sub.empty:
                continue
            print(f"\n--- {label} ---")
            print(sub.round(2).to_string(index=False))

    # Equity curves 저장
    eq_data = {}
    for r in all_results:
        eq_data[f"{r.asset}_{r.name}"] = r.equity
    if eq_data:
        eq_df = pd.DataFrame(eq_data)
        eq_df.to_csv(OUT_DIR / 'onchain_equity_curves.csv')

    # 거래 로그 저장
    for r in all_results:
        if not r.trades.empty:
            r.trades.to_csv(OUT_DIR / f'onchain_trades_{r.asset}_{r.name}.csv', index=False)

    print(f"\n[saved] {OUT_DIR / 'onchain_strategy_summary.csv'}")
    print(f"[saved] {OUT_DIR / 'onchain_strategy_by_period.csv'}")
    print(f"[saved] {OUT_DIR / 'onchain_equity_curves.csv'}")


if __name__ == "__main__":
    main()
