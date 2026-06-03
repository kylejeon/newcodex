# -*- coding: utf-8 -*-
"""V30A — V_FINAL 손실 trades 패턴 분석."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    UNIVERSE_CSV,
)

OUT = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')

# V28 KOSDAQ-only trades 사용 (cache 930)
tr = pd.read_csv(OUT / 'rocket_FINAL_trades.csv', parse_dates=['date','entry_date'],
                 dtype={'ticker': str})
tr['ticker'] = tr['ticker'].str.zfill(6)

print("="*78)
print("V30A — V_FINAL 손실 trades 패턴 분석")
print("="*78)

sells = tr[tr['side']=='SELL'].copy()
wins = sells[sells['pnl_pct'] > 0].copy()
losses = sells[sells['pnl_pct'] <= 0].copy()

print(f"\n[Overview]")
print(f"  Total: {len(sells)}, Wins: {len(wins)} ({len(wins)/len(sells)*100:.0f}%), "
      f"Losses: {len(losses)} ({len(losses)/len(sells)*100:.0f}%)")

# Load OHLCV for context
udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
name_map = dict(zip(udf['ticker'].astype(str), udf['name']))
data = load_universe_data(udf)
investor_data = load_investor_data()
print(f"  data: {len(data)} OHLCV, {len(investor_data)} investor cache")
data_ind = {t: compute_indicators(df) for t, df in data.items()}

# 분석 1: 손실 종목의 entry 일 상태 (re-compute)
print(f"\n[1] Loss trades entry day metrics")
print(f"  {'date':>11s}  {'ticker':>7s}  {'name':<14s}  {'pnl':>6s}  {'max':>5s}  "
      f"{'reason':>10s}  {'ret252':>7s}  {'52w':>6s}  {'MA200':>5s}  {'vol×':>5s}  {'ATRr':>5s}")
loss_info = []
for _, t in losses.sort_values('pnl_pct').iterrows():
    ticker = t['ticker']
    if ticker not in data_ind: continue
    df_ind = data_ind[ticker]
    e_date = pd.Timestamp(t['entry_date'])
    # Entry signal day = prev Friday
    valid = df_ind.index[df_ind.index < e_date]
    if len(valid) == 0: continue
    scan_date = valid[-1]
    row = df_ind.loc[scan_date]
    if pd.isna(row['Close']): continue
    ret252 = row['Ret_252d'] * 100
    dist52w = (row['High52w'] - row['Close']) / row['High52w'] * 100
    ma200d = row['Close'] / row['MA200']
    vol_surge = row['Volume'] / row['VolAvg50']
    atr_ratio = row['ATR10'] / row['ATR50']
    info = {
        'date': e_date.strftime('%Y-%m-%d'), 'ticker': str(ticker)[:7],
        'name': str(name_map.get(ticker, '?'))[:14],
        'pnl_pct': t['pnl_pct'], 'max_gain_pct': t['max_gain_pct'],
        'reason': str(t['reason']),
        'ret_252d': ret252, 'dist_52w': dist52w, 'ma200_dist': ma200d,
        'vol_surge': vol_surge, 'atr_ratio': atr_ratio,
        'hold_days': t['hold_days'],
    }
    loss_info.append(info)
    print(f"  {info['date']:>11s}  {info['ticker']:>7s}  {info['name']:<14s}  "
          f"{info['pnl_pct']:>+5.0f}%  {info['max_gain_pct']:>+4.0f}%  "
          f"{info['reason']:>10s}  {info['ret_252d']:>+6.0f}%  {info['dist_52w']:>+5.0f}%  "
          f"{info['ma200_dist']:>5.2f}  {info['vol_surge']:>5.2f}  {info['atr_ratio']:>5.2f}")

loss_df = pd.DataFrame(loss_info)

# Wins for comparison
print(f"\n[2] Win trades entry day metrics (비교용)")
print(f"  {'date':>11s}  {'ticker':>7s}  {'name':<14s}  {'pnl':>6s}  {'max':>5s}  "
      f"{'reason':>10s}  {'ret252':>7s}  {'52w':>6s}  {'MA200':>5s}  {'vol×':>5s}  {'ATRr':>5s}")
win_info = []
for _, t in wins.sort_values('pnl_pct', ascending=False).iterrows():
    ticker = t['ticker']
    if ticker not in data_ind: continue
    df_ind = data_ind[ticker]
    e_date = pd.Timestamp(t['entry_date'])
    valid = df_ind.index[df_ind.index < e_date]
    if len(valid) == 0: continue
    scan_date = valid[-1]
    row = df_ind.loc[scan_date]
    if pd.isna(row['Close']): continue
    ret252 = row['Ret_252d'] * 100
    dist52w = (row['High52w'] - row['Close']) / row['High52w'] * 100
    ma200d = row['Close'] / row['MA200']
    vol_surge = row['Volume'] / row['VolAvg50']
    atr_ratio = row['ATR10'] / row['ATR50']
    info = {
        'date': e_date.strftime('%Y-%m-%d'), 'ticker': str(ticker)[:7],
        'name': str(name_map.get(ticker, '?'))[:14],
        'pnl_pct': t['pnl_pct'], 'max_gain_pct': t['max_gain_pct'],
        'reason': str(t['reason']),
        'ret_252d': ret252, 'dist_52w': dist52w, 'ma200_dist': ma200d,
        'vol_surge': vol_surge, 'atr_ratio': atr_ratio,
        'hold_days': t['hold_days'],
    }
    win_info.append(info)
    print(f"  {info['date']:>11s}  {info['ticker']:>7s}  {info['name']:<14s}  "
          f"{info['pnl_pct']:>+5.0f}%  {info['max_gain_pct']:>+4.0f}%  "
          f"{info['reason']:>10s}  {info['ret_252d']:>+6.0f}%  {info['dist_52w']:>+5.0f}%  "
          f"{info['ma200_dist']:>5.2f}  {info['vol_surge']:>5.2f}  {info['atr_ratio']:>5.2f}")

win_df = pd.DataFrame(win_info)

# Statistics comparison
print(f"\n[3] Distribution comparison (Wins vs Losses)")
print(f"  {'metric':>15s}  {'Wins mean':>10s}  {'Losses mean':>11s}  {'Δ':>8s}  "
      f"{'Wins median':>12s}  {'Loss median':>11s}")
for col in ['ret_252d', 'dist_52w', 'ma200_dist', 'vol_surge', 'atr_ratio']:
    if col in loss_df.columns and col in win_df.columns:
        wm = win_df[col].mean()
        lm = loss_df[col].mean()
        wmed = win_df[col].median()
        lmed = loss_df[col].median()
        print(f"  {col:>15s}  {wm:>+9.2f}  {lm:>+10.2f}  {wm-lm:>+7.2f}  "
              f"{wmed:>+11.2f}  {lmed:>+10.2f}")

# Quartile analysis: what filter could separate?
print(f"\n[4] Filter candidate test — 단일 변수 threshold")
print(f"  변수가 winners/losers 분리 가능한지 측정")
for col, op in [('ret_252d', '<'), ('ret_252d', '>'), ('dist_52w', '<'), ('dist_52w', '>'),
                 ('ma200_dist', '<'), ('ma200_dist', '>'), ('vol_surge', '<'), ('vol_surge', '>'),
                 ('atr_ratio', '<'), ('atr_ratio', '>')]:
    if col not in loss_df.columns: continue
    all_df = pd.concat([win_df, loss_df])
    for q in [0.25, 0.50, 0.75]:
        th = all_df[col].quantile(q)
        if op == '<':
            wins_excl = (win_df[col] < th).sum()
            losses_excl = (loss_df[col] < th).sum()
        else:
            wins_excl = (win_df[col] > th).sum()
            losses_excl = (loss_df[col] > th).sum()
        if losses_excl >= 5 and wins_excl <= losses_excl * 0.5:
            print(f"  ★ filter [{col} {op} {th:.2f}] excludes "
                  f"{wins_excl} wins / {losses_excl} losses "
                  f"(W/L ratio {wins_excl/max(losses_excl,1):.2f})")

# Reason breakdown
print(f"\n[5] Loss reason distribution")
loss_reasons = losses['reason'].value_counts()
for r, c in loss_reasons.items():
    avg = losses[losses['reason']==r]['pnl_pct'].mean()
    print(f"  {str(r):>10s}: n={c}, avg P&L {avg:+.1f}%")

# Hold days distribution
print(f"\n[6] Hold days analysis")
print(f"  Wins:   median {wins['hold_days'].median():.0f}d, "
      f"mean {wins['hold_days'].mean():.0f}d")
print(f"  Losses: median {losses['hold_days'].median():.0f}d, "
      f"mean {losses['hold_days'].mean():.0f}d")
print(f"  short losses (<20d): n={(losses['hold_days']<20).sum()}, "
      f"avg P&L {losses[losses['hold_days']<20]['pnl_pct'].mean():+.1f}%")
print(f"  long  losses (≥60d): n={(losses['hold_days']>=60).sum()}, "
      f"avg P&L {losses[losses['hold_days']>=60]['pnl_pct'].mean():+.1f}%")

# Max gain 만 도달한 후 손실인 경우 (peak protection 실패)
print(f"\n[7] Max gain reached but exit loss")
mg_pos = losses[losses['max_gain_pct'] > 0]
print(f"  Losses with max_gain>0: n={len(mg_pos)}")
print(f"  max_gain >=10%: n={(losses['max_gain_pct']>=10).sum()}")
print(f"  max_gain >=20%: n={(losses['max_gain_pct']>=20).sum()}")
print(f"  Max gain stayed near 0% (entry 직후 실패): n={(losses['max_gain_pct']<5).sum()}")

# By year
print(f"\n[8] By year")
losses['year'] = losses['date'].dt.year
for y, g in losses.groupby('year'):
    print(f"  {int(y)}: {len(g)} losses, mean P&L {g['pnl_pct'].mean():+.1f}%")
