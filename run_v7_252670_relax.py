# -*- coding: utf-8 -*-
'''
252670 (KOSPI 숏) 매수 조건 완화 실험.

현재 outer+inner 10개 AND 조건:
  outer: close > ma3/6/19 AND prevRSI<70 AND RSI 상승
  inner: volume↑ AND low↑ AND close>ma60 AND ma60↑ AND ma3>ma6>ma19

5년에 21건, 최근 16개월에 0건 → 신호 과소.

완화 변형 (누적):
  R1  inner 에서 "ma60↑" (ma60_before2 < ma60_before) 제거
  R2  R1 + "ma3 > ma6 > ma19" 제거
  R3  R2 + "prevVolume2 < prevVolume" 제거
  R4  R3 + "prevLow2 < prevLow" 제거
  R5  R4 + "prevRSI2 < prevRSI" 도 제거

두 구간에서 비교:
  - 2025-01 ~ 2026-04 (in-sample, 16개월)
  - 2020 ~ 2024 (out-of-sample, 5년, 중 2022 약세장 포함)
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


# ===== 252670 매수 조건 변형 =====
# outer 는 모든 변형에서 동일하게 유지
OUTER_COND = (
    "PrevClosePrice > stock_data['ma3_before'].values[0]  and "
    "PrevClosePrice > stock_data['ma6_before'].values[0]  and "
    "PrevClosePrice > stock_data['ma19_before'].values[0] and "
    "stock_data['prevRSI'].values[0] < KOSPI_252670_BUY_RSI_MAX and "
    "stock_data['prevRSI2'].values[0] < stock_data['prevRSI'].values[0]"
)

# inner 변형 (각 라인이 완화된 inner 조건)
INNER_VARIANTS = {
    'baseline': (
        "(stock_data['prevVolume2'].values[0] < stock_data['prevVolume'].values[0]) and "
        "(stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
        "PrevClosePrice > stock_data['ma60_before'].values[0] and "
        "stock_data['ma60_before2'].values[0] < stock_data['ma60_before'].values[0]  and "
        "stock_data['ma3_before'].values[0]  > stock_data['ma6_before'].values[0]  > stock_data['ma19_before'].values[0]"
    ),
    'R1_drop_ma60_up': (
        "(stock_data['prevVolume2'].values[0] < stock_data['prevVolume'].values[0]) and "
        "(stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
        "PrevClosePrice > stock_data['ma60_before'].values[0] and "
        "stock_data['ma3_before'].values[0]  > stock_data['ma6_before'].values[0]  > stock_data['ma19_before'].values[0]"
    ),
    'R2_drop_ma_align': (
        "(stock_data['prevVolume2'].values[0] < stock_data['prevVolume'].values[0]) and "
        "(stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
        "PrevClosePrice > stock_data['ma60_before'].values[0]"
    ),
    'R3_drop_volume': (
        "(stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
        "PrevClosePrice > stock_data['ma60_before'].values[0]"
    ),
    'R4_drop_low': (
        "PrevClosePrice > stock_data['ma60_before'].values[0]"
    ),
    'R5_drop_RSI_rising': (
        "PrevClosePrice > stock_data['ma60_before'].values[0]"
        # 동시에 outer 의 prevRSI2 < prevRSI 도 제거 (patch 시 outer 도 교체)
    ),
}

# R5 는 outer 도 변경: RSI rising 조건 제거
OUTER_R5 = (
    "PrevClosePrice > stock_data['ma3_before'].values[0]  and "
    "PrevClosePrice > stock_data['ma6_before'].values[0]  and "
    "PrevClosePrice > stock_data['ma19_before'].values[0] and "
    "stock_data['prevRSI'].values[0] < KOSPI_252670_BUY_RSI_MAX"
)

# 원본 소스의 실제 조건 라인 찾기 (exact match)
BASELINE_OUTER_LINE = (
    "                        if PrevClosePrice > stock_data['ma3_before'].values[0]  and "
    "PrevClosePrice > stock_data['ma6_before'].values[0]  and "
    "PrevClosePrice > stock_data['ma19_before'].values[0] and "
    "stock_data['prevRSI'].values[0] < KOSPI_252670_BUY_RSI_MAX and "
    "stock_data['prevRSI2'].values[0] < stock_data['prevRSI'].values[0]:"
)
BASELINE_INNER_LINE = (
    "                            if (stock_data['prevVolume2'].values[0] < stock_data['prevVolume'].values[0]) and "
    "(stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
    "PrevClosePrice > stock_data['ma60_before'].values[0] and "
    "stock_data['ma60_before2'].values[0] < stock_data['ma60_before'].values[0]  and "
    "stock_data['ma3_before'].values[0]  > stock_data['ma6_before'].values[0]  > stock_data['ma19_before'].values[0]  :"
)


def patch_252670(src: str, variant_key: str) -> str:
    if variant_key == 'baseline':
        return src
    if BASELINE_OUTER_LINE not in src:
        raise RuntimeError("252670 outer baseline line not found")
    if BASELINE_INNER_LINE not in src:
        raise RuntimeError("252670 inner baseline line not found")

    if variant_key == 'R5_drop_RSI_rising':
        outer_repl = "                        if " + OUTER_R5 + ":"
        src = src.replace(BASELINE_OUTER_LINE, outer_repl, 1)

    new_inner = INNER_VARIANTS[variant_key]
    inner_repl = "                            if " + new_inner + ":"
    src = src.replace(BASELINE_INNER_LINE, inner_repl, 1)
    return src


def patch_year_range(src: str, start_year: int, end_year: int | None) -> str:
    src = re.sub(r'^StartYear\s*=\s*\d+', f'StartYear = {start_year}',
                 src, count=1, flags=re.MULTILINE)
    if end_year is not None:
        if 'EndYear =' not in src:
            src = src.replace(
                f'StartYear = {start_year}',
                f'StartYear = {start_year}\nEndYear = {end_year}', 1)
        else:
            src = re.sub(r'EndYear\s*=\s*\d+', f'EndYear = {end_year}', src, count=1)
        src = src.replace(
            'int(date_object.strftime("%Y")) >= StartYear',
            'int(date_object.strftime("%Y")) >= StartYear and int(date_object.strftime("%Y")) <= EndYear',
        )
    return src


def run_config(variant_key: str, start_year: int, end_year: int | None, tag: str) -> dict:
    equity_csv = OUT_DIR / f'v7_relax252670_{tag}_{variant_key}_equity.csv'
    trades_csv = OUT_DIR / f'v7_relax252670_{tag}_{variant_key}_trades.csv'
    with open(trades_csv, 'w') as f:
        f.write('date,code,name,buy_date,buy_price,first_money,sell_price,revenue_rate,return_money\n')

    src = BASE_FILE.read_text()
    src = patch_252670(src, variant_key)
    src = patch_year_range(src, start_year, end_year)
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

    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE_FILE.parent),
                                     mode='w', delete=False) as f:
        tmp = Path(f.name)
        f.write(src)
    print(f"  [run] {tag} / {variant_key}")
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              capture_output=True, text=True, timeout=1800,
                              cwd=str(BASE_FILE.parent))
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print(f"    FAILED: {proc.stderr[-1500:]}")
        return {'variant': variant_key, 'ok': False}

    df = pd.read_csv(equity_csv, index_col=0, parse_dates=[0]).sort_index()
    df['Total_Money'] = df['Total_Money'].astype(float)

    # 기간 슬라이스
    if end_year is not None:
        period_df = df[(df.index.year >= start_year) & (df.index.year <= end_year)]
    else:
        period_df = df[df.index.year >= start_year]

    if len(period_df) < 2:
        return {'variant': variant_key, 'ok': False, 'error': 'empty period'}

    base = float(period_df['Total_Money'].iloc[0])
    final = float(period_df['Total_Money'].iloc[-1])
    total_ret = (final / base - 1) * 100
    cm = period_df['Total_Money'].cummax()
    mdd = float(((period_df['Total_Money'] / cm) - 1).min() * 100)
    years = (period_df.index[-1] - period_df.index[0]).days / 365.25
    cagr = ((final / base) ** (1 / years) - 1) * 100 if years > 0 else 0

    # 2022 단일 연도 (out-of-sample 용)
    y22 = df[df.index.year == 2022]
    r22 = None
    if len(y22) > 1:
        r22 = (float(y22['Total_Money'].iloc[-1]) / float(y22['Total_Money'].iloc[0]) - 1) * 100

    # 2026-03
    mar = df[(df.index.year == 2026) & (df.index.month == 3)]
    mar_ret = None
    if len(mar):
        mar_ret = (float(mar['Total_Money'].iloc[-1]) / float(mar['Total_Money'].iloc[0]) - 1) * 100

    tr = pd.read_csv(trades_csv)
    tr['code'] = tr['code'].astype(str).str.zfill(6)
    if end_year is not None:
        tr['date_dt'] = pd.to_datetime(tr['date'])
        tr = tr[(tr['date_dt'].dt.year >= start_year) & (tr['date_dt'].dt.year <= end_year)]
    else:
        tr['date_dt'] = pd.to_datetime(tr['date'])
        tr = tr[tr['date_dt'].dt.year >= start_year]

    all_n = len(tr)
    all_wr = (tr['revenue_rate'] > 0).mean() * 100 if all_n else 0

    t252 = tr[tr['code'] == '252670']
    n252 = len(t252)
    wr252 = (t252['revenue_rate'] > 0).mean() * 100 if n252 else 0
    avg252 = float(t252['revenue_rate'].mean()) if n252 else 0

    return {
        'variant': variant_key, 'ok': True,
        'total_ret': round(total_ret, 2),
        'cagr': round(cagr, 2),
        'mdd': round(mdd, 2),
        'mar2026': round(mar_ret, 2) if mar_ret is not None else None,
        'y2022': round(r22, 2) if r22 is not None else None,
        'final': int(final),
        'all_n': all_n, 'all_wr': round(all_wr, 2),
        'n252': n252, 'wr252': round(wr252, 2), 'avg252': round(avg252, 2),
    }


def main():
    variants = ['baseline', 'R1_drop_ma60_up', 'R2_drop_ma_align',
                'R3_drop_volume', 'R4_drop_low', 'R5_drop_RSI_rising']

    print("\n=" * 50)
    print("### 최근 16개월 (2025-01 ~ 2026-04) ###")
    rows_recent = []
    for v in variants:
        r = run_config(v, start_year=2025, end_year=None, tag='recent')
        rows_recent.append(r)
    df_recent = pd.DataFrame([r for r in rows_recent if r.get('ok')])
    print(df_recent[['variant', 'total_ret', 'mdd', 'mar2026',
                      'all_n', 'n252', 'wr252', 'avg252', 'final']].to_string(index=False))

    print("\n=" * 50)
    print("### Out-of-sample 2020-2024 (5년) ###")
    rows_5y = []
    for v in variants:
        r = run_config(v, start_year=2020, end_year=2024, tag='2020_2024')
        rows_5y.append(r)
    df_5y = pd.DataFrame([r for r in rows_5y if r.get('ok')])
    print(df_5y[['variant', 'total_ret', 'cagr', 'mdd', 'y2022',
                  'all_n', 'n252', 'wr252', 'avg252', 'final']].to_string(index=False))

    # 종합 저장
    df_recent['period'] = 'recent_2025_2026'
    df_5y['period'] = '2020_2024_OOS'
    combined = pd.concat([df_recent, df_5y], ignore_index=True)
    combined.to_csv(OUT_DIR / 'v7_relax252670_compare.csv', index=False)
    print(f"\n[saved] {OUT_DIR / 'v7_relax252670_compare.csv'}")


if __name__ == "__main__":
    main()
