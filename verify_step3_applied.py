# -*- coding: utf-8 -*-
'''
Step 3(122630 하드스탑)만 적용된 v7_best 의 기대 성과:
 - 2025-01~2026-04 : baseline 대비 소폭 개선 (+3%p 수준)
 - 2020-2024       : baseline 과 동일 (발동 안 함)
 - 2026-03         : -24.94% → 더 나아져야 (단일 catastrophic trade 컷)

원본 v7_best.py 를 직접 실행 (patch 없이) 해서 숫자 확인.
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


def run(start_year: int, end_year: int | None, label: str) -> pd.DataFrame:
    equity_csv = OUT_DIR / f'v7_verify_step3_{label}_equity.csv'
    src = BASE_FILE.read_text()
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

    src = src.replace('plt.show()', "print('[skip plot]')")
    dump = (
        "    # INJECTED equity dump\n"
        f"    result_df.to_csv({str(equity_csv)!r})\n\n"
    )
    src = src.replace("    resultData['DateStr']", dump + "    resultData['DateStr']", 1)

    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE_FILE.parent),
                                     mode='w', delete=False) as f:
        tmp = Path(f.name)
        f.write(src)
    print(f"[run] {label}: {start_year}-{end_year}")
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              capture_output=True, text=True, timeout=1800,
                              cwd=str(BASE_FILE.parent))
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print(f"[run] FAILED: {proc.stderr[-1500:]}")
        raise RuntimeError("backtest failed")
    df = pd.read_csv(equity_csv, index_col=0, parse_dates=[0]).sort_index()
    df['Total_Money'] = df['Total_Money'].astype(float)
    return df


def report_recent(df: pd.DataFrame):
    df = df[df.index.year >= 2025]
    end = df.index[-1]
    oy = df[df.index >= end - pd.Timedelta(days=365)]
    base = float(oy['Total_Money'].iloc[0])
    final = float(df['Total_Money'].iloc[-1])
    ret_1y = (final / base - 1) * 100
    cm = oy['Total_Money'].cummax()
    mdd_1y = float(((oy['Total_Money'] / cm) - 1).min() * 100)

    all_base = float(df['Total_Money'].iloc[0])
    ret_all = (final / all_base - 1) * 100
    cm_a = df['Total_Money'].cummax()
    mdd_all = float(((df['Total_Money'] / cm_a) - 1).min() * 100)

    mar = df[(df.index.year == 2026) & (df.index.month == 3)]
    mar_ret = None
    if len(mar):
        mar_ret = (float(mar['Total_Money'].iloc[-1]) /
                   float(mar['Total_Money'].iloc[0]) - 1) * 100

    print(f"  1년: {ret_1y:+.2f}%  MDD: {mdd_1y:.2f}%")
    print(f"  2025-01 ~ : {ret_all:+.2f}%  MDD: {mdd_all:.2f}%")
    if mar_ret is not None:
        print(f"  2026-03:   {mar_ret:+.2f}%")
    return {'ret_1y': ret_1y, 'mdd_1y': mdd_1y, 'ret_all': ret_all,
            'mdd_all': mdd_all, 'mar2026': mar_ret}


def report_5year(df: pd.DataFrame):
    p = df[(df.index.year >= 2020) & (df.index.year <= 2024)]
    if len(p) == 0:
        print("  (no 2020-2024 data)")
        return {}
    base = float(p['Total_Money'].iloc[0])
    final = float(p['Total_Money'].iloc[-1])
    total = (final / base - 1) * 100
    cm = p['Total_Money'].cummax()
    mdd = float(((p['Total_Money'] / cm) - 1).min() * 100)
    years = (p.index[-1] - p.index[0]).days / 365.25
    cagr = ((final / base) ** (1 / years) - 1) * 100
    print(f"  2020-2024: {total:+.2f}%  CAGR: {cagr:.2f}%  MDD: {mdd:.2f}%")
    return {'total': total, 'cagr': cagr, 'mdd': mdd}


def main():
    print("\n================ 최근 구간 (StartYear=2025) ================")
    df_recent = run(2025, None, 'recent')
    r1 = report_recent(df_recent)

    print("\n================ Out-of-sample (StartYear=2020, EndYear=2024) ================")
    df_5y = run(2020, 2024, '2020_2024')
    r2 = report_5year(df_5y)

    print("\n================ Step 3 효과 (before/after 비교) ================")
    baseline_recent = {'ret_1y': 144.10, 'mdd_1y': -35.20, 'mar2026': -24.94}
    baseline_5y = {'total': 1204.97, 'cagr': 67.26, 'mdd': -15.08}

    print(f"[최근 1년]")
    print(f"  baseline:     {baseline_recent['ret_1y']:+.2f}%  MDD {baseline_recent['mdd_1y']:.2f}%  3월 {baseline_recent['mar2026']:.2f}%")
    if r1:
        print(f"  +Step 3:      {r1['ret_1y']:+.2f}%  MDD {r1['mdd_1y']:.2f}%  3월 {r1['mar2026']:+.2f}%")
        print(f"  → 변화:       {r1['ret_1y']-baseline_recent['ret_1y']:+.2f}%p  "
              f"MDD {r1['mdd_1y']-baseline_recent['mdd_1y']:+.2f}%p  "
              f"3월 {r1['mar2026']-baseline_recent['mar2026']:+.2f}%p")

    print(f"\n[2020-2024]")
    print(f"  baseline:     {baseline_5y['total']:+.2f}%  CAGR {baseline_5y['cagr']:.2f}%  MDD {baseline_5y['mdd']:.2f}%")
    if r2:
        print(f"  +Step 3:      {r2['total']:+.2f}%  CAGR {r2['cagr']:.2f}%  MDD {r2['mdd']:.2f}%")
        print(f"  → 변화:       {r2['total']-baseline_5y['total']:+.2f}%p  "
              f"CAGR {r2['cagr']-baseline_5y['cagr']:+.2f}%p  "
              f"MDD {r2['mdd']-baseline_5y['mdd']:+.2f}%p")


if __name__ == "__main__":
    main()
