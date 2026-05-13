# -*- coding: utf-8 -*-
'''
2020-2024 5년 구간에 대해 세 패치(regime/251340 filter/122630 hardstop) 효과 검증.
run_v7_improvements_stack.py 과 같은 비교지만 기간이 다름.

- StartYear=2020, EndYear=2024 패치
- KIS GetOhlcv("KR", code, 2200) 은 오늘로부터 2200일 (~2020-04) 까지 커버
- 실제 2020-04~2024-12 범위로 컷
'''
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

BASE_FILE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_best.py')
OUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
OUT_DIR.mkdir(exist_ok=True)


def _set_const(src: str, name: str, value) -> str:
    pat = rf'^{re.escape(name)}\s*=\s*[-+]?\d+(?:\.\d+)?\s*$'
    if not re.search(pat, src, flags=re.MULTILINE):
        raise RuntimeError(f"const {name} not found")
    return re.sub(pat, f'{name} = {value}', src, count=1, flags=re.MULTILINE)


def _set_bool(src: str, name: str, value: bool) -> str:
    pat = rf'^{re.escape(name)}\s*=\s*(True|False)\s*$'
    if not re.search(pat, src, flags=re.MULTILINE):
        raise RuntimeError(f"bool {name} not found")
    return re.sub(pat, f'{name} = {value}', src, count=1, flags=re.MULTILINE)


def patch_year_range(src: str, start_year: int, end_year: int) -> str:
    src = re.sub(r'^StartYear\s*=\s*\d+', f'StartYear = {start_year}',
                 src, count=1, flags=re.MULTILINE)
    if 'EndYear =' not in src:
        src = src.replace(
            f'StartYear = {start_year}',
            f'StartYear = {start_year}\nEndYear = {end_year}',
            1,
        )
    else:
        src = re.sub(r'EndYear\s*=\s*\d+', f'EndYear = {end_year}', src, count=1)
    src = src.replace(
        'int(date_object.strftime("%Y")) >= StartYear',
        'int(date_object.strftime("%Y")) >= StartYear and int(date_object.strftime("%Y")) <= EndYear',
    )
    return src


def apply_regime_mild(src: str) -> str:
    src = _set_bool(src, 'ENABLE_REGIME_OVERLAY', True)
    for k, v in {
        'EXPOSURE_BULL': 1.00,
        'EXPOSURE_NEUTRAL': 0.85,
        'EXPOSURE_BEAR': 0.55,
        'EXPOSURE_CHOP': 0.45,
        'MIN_TOTAL_EXPOSURE': 0.40,
        'MAX_TOTAL_EXPOSURE': 1.00,
    }.items():
        src = _set_const(src, k, v)
    return src


def apply_251340_filter(src: str) -> str:
    marker = (
        "                        #KODEX 코스닥150선물인버스\n"
        "                        if stock_code == \"251340\":\n"
        "                            if stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]:\n"
        "                                IsBuyGo = False "
    )
    if marker not in src:
        raise RuntimeError("251340 filter marker not found")
    insert = (
        "                        #KODEX 코스닥150선물인버스\n"
        "                        if stock_code == \"251340\":\n"
        "                            if stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]:\n"
        "                                IsBuyGo = False \n"
        "                            if stock_data['prevClose'].values[0] > stock_data['ma60_before'].values[0]:\n"
        "                                IsBuyGo = False\n"
        "                            if stock_data['Disparity20'].values[0] > 105:\n"
        "                                IsBuyGo = False "
    )
    return src.replace(marker, insert, 1)


def apply_122630_hardstop(src: str, base_pct: float = 0.12, tight_pct: float = 0.09) -> str:
    anchor = "HARD_STOP_VOL_TH = 0.045"
    if anchor not in src:
        raise RuntimeError("anchor HARD_STOP_VOL_TH not found")
    const_block = (
        f"\nENABLE_122630_HARD_STOP = True\n"
        f"HARD_STOP_122630_PCT_TIGHT = {tight_pct}\n"
        f"HARD_STOP_122630_PCT_BASE = {base_pct}\n"
    )
    src = src.replace(anchor, anchor + const_block, 1)

    marker = (
        "                    IsSellGo = False\n"
        "                    hold_days = calc_hold_days(date, investData.get('Date', str(date)))\n"
    )
    if marker not in src:
        raise RuntimeError("KOSPI sell marker not found")
    inject = (
        "                    IsSellGo = False\n"
        "                    hold_days = calc_hold_days(date, investData.get('Date', str(date)))\n"
        "                    if ENABLE_122630_HARD_STOP and stock_code == \"122630\":\n"
        "                        _prev_range_ratio = (stock_data['prevHigh'].values[0] - stock_data['prevLow'].values[0]) / stock_data['prevClose'].values[0]\n"
        "                        _weak_trend = stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]\n"
        "                        _is_high_vol = _prev_range_ratio >= HARD_STOP_VOL_TH\n"
        "                        _hs_pct = HARD_STOP_122630_PCT_BASE\n"
        "                        if _weak_trend and _is_high_vol:\n"
        "                            _hs_pct = HARD_STOP_122630_PCT_TIGHT\n"
        "                        _HardStopPrice = investData['BuyPrice'] * (1.0 - _hs_pct)\n"
        "                        if stock_data['low'].values[0] <= _HardStopPrice:\n"
        "                            IsSellGo = True\n"
        "                            if NowOpenPrice <= _HardStopPrice:\n"
        "                                SellPrice = NowOpenPrice\n"
        "                            else:\n"
        "                                SellPrice = _HardStopPrice\n"
    )
    return src.replace(marker, inject, 1)


def patch_source(src: str, start_year: int, end_year: int, steps: set,
                 equity_csv: Path, trades_csv: Path) -> str:
    src = patch_year_range(src, start_year, end_year)

    if 1 in steps:
        src = apply_regime_mild(src)
    if 2 in steps:
        src = apply_251340_filter(src)
    if 3 in steps:
        src = apply_122630_hardstop(src)

    src = src.replace('plt.show()', "print('[skip plot]')")

    trade_write = (
        "                        try:\n"
        f"                            with open({str(trades_csv)!r}, 'a') as __tf:\n"
        "                                __tf.write(f'{str(date)},{stock_code},"
        "{GetStockName(stock_code, StockDataList)},{investData[\"Date\"]},{investData[\"BuyPrice\"]},"
        "{investData[\"FirstMoney\"]},{SellPrice},{RevenueRate},{ReturnMoney}\\n')\n"
        "                        except Exception:\n"
        "                            pass\n"
    )
    marker = '" 매도가", SellPrice * (1.0 - fee))'
    src = src.replace(marker, marker + "\n" + trade_write)

    dump = (
        "    # INJECTED equity dump\n"
        f"    result_df.to_csv({str(equity_csv)!r})\n\n"
    )
    src = src.replace("    resultData['DateStr']", dump + "    resultData['DateStr']", 1)
    return src


def run(label: str, steps: set, start_year: int = 2020, end_year: int = 2024) -> dict:
    equity_csv = OUT_DIR / f'v7_p2020_{label}_equity.csv'
    trades_csv = OUT_DIR / f'v7_p2020_{label}_trades.csv'
    with open(trades_csv, 'w') as f:
        f.write('date,code,name,buy_date,buy_price,first_money,sell_price,revenue_rate,return_money\n')

    src = BASE_FILE.read_text()
    patched = patch_source(src, start_year, end_year, steps, equity_csv, trades_csv)
    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE_FILE.parent),
                                     mode='w', delete=False) as f:
        tmp = Path(f.name)
        f.write(patched)

    print(f"\n[run] {label}  steps={sorted(steps)}  period={start_year}-{end_year}")
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              capture_output=True, text=True, timeout=1800,
                              cwd=str(BASE_FILE.parent))
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print(f"[run] {label} FAILED\n{proc.stderr[-2000:]}")
        return {'label': label, 'ok': False}

    df = pd.read_csv(equity_csv, index_col=0, parse_dates=[0]).sort_index()
    df['Total_Money'] = df['Total_Money'].astype(float)

    # 2020-01-01 ~ 2024-12-31 구간만
    period_df = df[(df.index.year >= start_year) & (df.index.year <= end_year)].copy()
    if len(period_df) == 0:
        return {'label': label, 'ok': False, 'error': 'empty period'}

    base = float(period_df['Total_Money'].iloc[0])
    final = float(period_df['Total_Money'].iloc[-1])
    total_ret = (final / base - 1) * 100
    cm = period_df['Total_Money'].cummax()
    mdd = float(((period_df['Total_Money'] / cm) - 1).min() * 100)

    # CAGR
    years = (period_df.index[-1] - period_df.index[0]).days / 365.25
    cagr = ((final / base) ** (1 / years) - 1) * 100 if years > 0 else 0

    # 연도별 성과
    period_df['year'] = period_df.index.year
    yearly = period_df.groupby('year')['Total_Money'].agg(['first', 'last'])
    yearly['ret_pct'] = (yearly['last'] / yearly['first'] - 1) * 100
    yearly = yearly.round(2)

    tr = pd.read_csv(trades_csv)
    if len(tr) > 0:
        tr['date_dt'] = pd.to_datetime(tr['date'])
        tr_in_period = tr[(tr['date_dt'].dt.year >= start_year) &
                          (tr['date_dt'].dt.year <= end_year)].copy()
        tr_in_period['code'] = tr_in_period['code'].astype(str).str.zfill(6)
        wins = int((tr_in_period['revenue_rate'] > 0).sum())
        losses = len(tr_in_period) - wins
        win_rate = wins / len(tr_in_period) * 100 if len(tr_in_period) else 0
        avg_ret = float(tr_in_period['revenue_rate'].mean()) if len(tr_in_period) else 0
        by_code = tr_in_period.groupby('code').agg(
            n=('revenue_rate', 'count'),
            wr=('revenue_rate', lambda s: (s > 0).mean() * 100),
            avg=('revenue_rate', 'mean'),
        ).round(2)
    else:
        win_rate = avg_ret = 0
        wins = losses = 0
        by_code = pd.DataFrame()

    return {
        'label': label, 'ok': True,
        'total_ret': round(total_ret, 2), 'mdd': round(mdd, 2),
        'cagr': round(cagr, 2), 'final': int(final),
        'trades': int(len(tr_in_period) if 'tr_in_period' in locals() else 0),
        'win_rate': round(win_rate, 2), 'avg_ret': round(avg_ret, 2),
        'yearly': yearly.to_dict('index'),
        'by_code': by_code.to_dict('index') if not by_code.empty else {},
    }


def main():
    configs = [
        ('baseline', set()),
        ('step1_regime', {1}),
        ('step12_regime_251filter', {1, 2}),
        ('step123_all', {1, 2, 3}),
    ]
    rows = []
    code_breakdowns = {}
    yearly_breakdowns = {}
    for label, steps in configs:
        r = run(label, steps)
        rows.append(r)
        if r.get('ok'):
            code_breakdowns[label] = r.get('by_code', {})
            yearly_breakdowns[label] = r.get('yearly', {})

    df = pd.DataFrame([{k: v for k, v in r.items()
                        if k not in ('yearly', 'by_code')}
                        for r in rows if r.get('ok')])
    df = df[['label', 'total_ret', 'cagr', 'mdd', 'trades',
             'win_rate', 'avg_ret', 'final']]
    print("\n" + "=" * 100)
    print("   2020-2024 (5년) 구간: Step 1→2→3 누적 개선")
    print("=" * 100)
    print(df.to_string(index=False))

    print("\n[연도별 수익률 (%)]")
    years_sorted = sorted(set().union(*(set(yb.keys()) for yb in yearly_breakdowns.values())))
    hdr = "year"
    for lbl in yearly_breakdowns.keys():
        hdr += f"  {lbl:>30}"
    print(hdr)
    for y in years_sorted:
        row = f"{y}"
        for lbl in yearly_breakdowns.keys():
            d = yearly_breakdowns[lbl].get(y)
            if d:
                row += f"  {d['ret_pct']:>30.2f}"
            else:
                row += f"  {'(none)':>30}"
        print(row)

    print("\n[종목별 성과]  (거래수 / 승률 / 평균 수익률)")
    all_codes = set()
    for b in code_breakdowns.values():
        all_codes.update(b.keys())
    all_codes = sorted(all_codes)
    hdr = "code      "
    for lbl in code_breakdowns.keys():
        hdr += f"  {lbl:>30}"
    print(hdr)
    for c in all_codes:
        row = f"{c:<10}"
        for lbl in code_breakdowns.keys():
            d = code_breakdowns[lbl].get(c)
            if d:
                row += f"  {int(d['n']):>3}t {d['wr']:>5.1f}% {d['avg']:+6.2f}%       "
            else:
                row += f"  {'(none)':>30}"
        print(row)

    df.to_csv(OUT_DIR / 'v7_improvements_2020_2024.csv', index=False)
    print(f"\n[saved] {OUT_DIR / 'v7_improvements_2020_2024.csv'}")


if __name__ == "__main__":
    main()
