# -*- coding: utf-8 -*-
'''
v7_best 구성별 비교 — regime overlay + DD guard 가 실제로 먹히도록
EXPOSURE_* / MIN_TOTAL_EXPOSURE 까지 override.

구성:
 1. baseline                  (둘 다 off, MIN/MAX=1.0 — 원본 기본값)
 2. regime_mild               (BULL=1.0, NEUTRAL=0.85, BEAR=0.55, CHOP=0.45, MIN=0.40)
 3. ddguard_only              (DD_EXPO 0.94/0.84/0.74 사용, MIN=0.70)
 4. both_mild                 (2 + 3 결합)
 5. regime_aggressive         (BULL=1.0, NEUTRAL=0.70, BEAR=0.30, CHOP=0.20, MIN=0.20)
 6. both_aggressive           (5 + DD_EXPO 0.85/0.65/0.45, MIN=0.20)
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
    # float literal 교체 (동일값일 땐 no-op지만 성공)
    pat = rf'^{re.escape(name)}\s*=\s*[-+]?\d+(?:\.\d+)?\s*$'
    if not re.search(pat, src, flags=re.MULTILINE):
        raise RuntimeError(f"const {name} not found in source")
    new = re.sub(pat, f'{name} = {value}', src, count=1, flags=re.MULTILINE)
    return new


def patch_source(src: str, start_year: int, regime: bool, dd_guard: bool,
                 overrides: dict, equity_csv: Path, trades_csv: Path) -> str:
    # 기본 토글
    src = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {start_year}', src)
    src = re.sub(r'ENABLE_REGIME_OVERLAY\s*=\s*(True|False)',
                 f'ENABLE_REGIME_OVERLAY = {regime}', src)
    src = re.sub(r'ENABLE_DD_GUARD\s*=\s*(True|False)',
                 f'ENABLE_DD_GUARD = {dd_guard}', src)
    # 상수 override
    for key, value in overrides.items():
        src = _set_const(src, key, value)

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
    if marker not in src:
        raise RuntimeError("trade log marker not found")
    src = src.replace(marker, marker + "\n" + trade_write)

    dump = (
        "    # INJECTED\n"
        f"    result_df.to_csv({str(equity_csv)!r})\n"
        f"    print('[INJECTED] equity saved')\n\n"
    )
    src = src.replace("    resultData['DateStr']", dump + "    resultData['DateStr']", 1)
    return src


def run_config(label: str, regime: bool, dd_guard: bool, overrides: dict) -> dict:
    print(f"[prep] {label}: overrides={overrides}", flush=True)
    equity_csv = OUT_DIR / f'v7_cfg_{label}_equity.csv'
    trades_csv = OUT_DIR / f'v7_cfg_{label}_trades.csv'
    with open(trades_csv, 'w') as f:
        f.write('date,code,name,buy_date,buy_price,first_money,sell_price,revenue_rate,return_money\n')

    src = BASE_FILE.read_text()
    patched = patch_source(src, 2025, regime, dd_guard, overrides, equity_csv, trades_csv)

    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE_FILE.parent),
                                     mode='w', delete=False) as f:
        tmp = Path(f.name)
        f.write(patched)

    print(f"\n[run] {label}: regime={regime} dd_guard={dd_guard} overrides={overrides}")
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              capture_output=True, text=True, timeout=1200,
                              cwd=str(BASE_FILE.parent))
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print(f"[run] {label} FAILED:\n{proc.stderr[-1500:]}")
        return {'label': label, 'ok': False}

    df = pd.read_csv(equity_csv, index_col=0, parse_dates=[0]).sort_index()
    df['Total_Money'] = df['Total_Money'].astype(float)

    end = df.index[-1]
    one_year_ago = end - pd.Timedelta(days=365)
    oy = df[df.index >= one_year_ago]
    final = float(df['Total_Money'].iloc[-1])
    ret_1y = (final / float(oy['Total_Money'].iloc[0]) - 1) * 100
    cm_1y = oy['Total_Money'].cummax()
    mdd_1y = float(((oy['Total_Money'] / cm_1y) - 1).min() * 100)

    tdf = df[df.index.year >= 2025]
    ret_all = (final / float(tdf['Total_Money'].iloc[0]) - 1) * 100
    cm_a = tdf['Total_Money'].cummax()
    mdd_all = float(((tdf['Total_Money'] / cm_a) - 1).min() * 100)

    mar = df[(df.index.year == 2026) & (df.index.month == 3)]
    mar_ret = None
    if len(mar):
        mar_ret = (float(mar['Total_Money'].iloc[-1]) /
                   float(mar['Total_Money'].iloc[0]) - 1) * 100

    tr = pd.read_csv(trades_csv)
    n = len(tr)
    wins = int((tr['revenue_rate'] > 0).sum()) if n else 0
    losses = n - wins
    win_rate = wins / n * 100 if n else 0
    avg_ret = float(tr['revenue_rate'].mean()) if n else 0

    return {
        'label': label, 'ok': True,
        'final': final, 'ret_1y': ret_1y, 'mdd_1y': mdd_1y,
        'ret_all': ret_all, 'mdd_all': mdd_all, 'mar2026': mar_ret,
        'trades': n, 'wins': wins, 'losses': losses,
        'win_rate': win_rate, 'avg_ret': avg_ret,
    }


def main():
    configs = [
        ('baseline',            False, False, {}),
        ('regime_mild',         True,  False, {
            'EXPOSURE_BULL': 1.00, 'EXPOSURE_NEUTRAL': 0.85,
            'EXPOSURE_BEAR': 0.55, 'EXPOSURE_CHOP': 0.45,
            'MIN_TOTAL_EXPOSURE': 0.40, 'MAX_TOTAL_EXPOSURE': 1.00,
        }),
        ('ddguard_only',        False, True,  {
            'DD_EXPO_1': 0.94, 'DD_EXPO_2': 0.84, 'DD_EXPO_3': 0.74,
            'MIN_TOTAL_EXPOSURE': 0.70, 'MAX_TOTAL_EXPOSURE': 1.00,
        }),
        ('both_mild',           True,  True,  {
            'EXPOSURE_BULL': 1.00, 'EXPOSURE_NEUTRAL': 0.85,
            'EXPOSURE_BEAR': 0.55, 'EXPOSURE_CHOP': 0.45,
            'DD_EXPO_1': 0.94, 'DD_EXPO_2': 0.84, 'DD_EXPO_3': 0.74,
            'MIN_TOTAL_EXPOSURE': 0.35, 'MAX_TOTAL_EXPOSURE': 1.00,
        }),
        ('regime_aggressive',   True,  False, {
            'EXPOSURE_BULL': 1.00, 'EXPOSURE_NEUTRAL': 0.70,
            'EXPOSURE_BEAR': 0.30, 'EXPOSURE_CHOP': 0.20,
            'MIN_TOTAL_EXPOSURE': 0.20, 'MAX_TOTAL_EXPOSURE': 1.00,
        }),
        ('both_aggressive',     True,  True,  {
            'EXPOSURE_BULL': 1.00, 'EXPOSURE_NEUTRAL': 0.70,
            'EXPOSURE_BEAR': 0.30, 'EXPOSURE_CHOP': 0.20,
            'DD_EXPO_1': 0.85, 'DD_EXPO_2': 0.65, 'DD_EXPO_3': 0.45,
            'MIN_TOTAL_EXPOSURE': 0.15, 'MAX_TOTAL_EXPOSURE': 1.00,
        }),
    ]
    rows = []
    for label, r, d, o in configs:
        rows.append(run_config(label, r, d, o))

    df = pd.DataFrame(rows)
    df = df[df['ok']]
    cols = ['label', 'ret_1y', 'mdd_1y', 'ret_all', 'mdd_all', 'mar2026',
            'trades', 'win_rate', 'avg_ret', 'final']
    out = df[cols].copy()
    for c in ['ret_1y', 'mdd_1y', 'ret_all', 'mdd_all', 'mar2026', 'win_rate', 'avg_ret']:
        out[c] = out[c].round(2)
    out['final'] = out['final'].apply(lambda v: f"{int(v):,}")
    out = out.sort_values('ret_1y', ascending=False)
    print("\n" + "=" * 110)
    print("    v7_best 구성별 비교 (2025-01 ~ 2026-04, 16개월)")
    print("=" * 110)
    print(out.to_string(index=False))

    df.to_csv(OUT_DIR / 'v7_regime_dd_compare.csv', index=False)
    print(f"\n[saved] {OUT_DIR / 'v7_regime_dd_compare.csv'}")


if __name__ == "__main__":
    main()
