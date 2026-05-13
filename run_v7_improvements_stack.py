# -*- coding: utf-8 -*-
'''
Step 1(regime_mild) + Step 2(251340 필터) + Step 3(122630 하드스탑) 스택 비교.

전략:
 baseline          : 원본 v7_best 파라미터 그대로
 step1             : regime overlay 정상 동작 (BULL=1.0/NEUTRAL=0.85/BEAR=0.55/CHOP=0.45, MIN=0.40)
 step12            : + 251340 매수 필터 (prev_close > ma60 또는 Disparity20 > 105 시 매수 금지)
 step123           : + 122630 하드스탑 (BASE=12%, TIGHT=9%)
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
    '''
    기존:
      if stock_code == "251340":
          if stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]:
              IsBuyGo = False
    추가 조건 주입:
      and prev_close > ma60_before → IsBuyGo = False
      and Disparity20 > 105 → IsBuyGo = False
    '''
    marker = (
        "                        #KODEX 코스닥150선물인버스\n"
        "                        if stock_code == \"251340\":\n"
        "                            if stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]:\n"
        "                                IsBuyGo = False "
    )
    if marker not in src:
        raise RuntimeError("251340 filter marker not found (buy-pass block)")
    insert = (
        "                        #KODEX 코스닥150선물인버스\n"
        "                        if stock_code == \"251340\":\n"
        "                            if stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]:\n"
        "                                IsBuyGo = False \n"
        "                            # [INJECTED Step2] 과열/후기 진입 차단\n"
        "                            if stock_data['prevClose'].values[0] > stock_data['ma60_before'].values[0]:\n"
        "                                IsBuyGo = False\n"
        "                            if stock_data['Disparity20'].values[0] > 105:\n"
        "                                IsBuyGo = False "
    )
    return src.replace(marker, insert, 1)


def apply_122630_hardstop(src: str, base_pct: float = 0.12, tight_pct: float = 0.09) -> str:
    '''
    코스피 sell block(line ~619) 안 IsSellGo=False 직후에 하드스탑 주입.
    원본:
        SellPrice = NowOpenPrice
        (blank)
        IsSellGo = False
        hold_days = calc_hold_days(...)
    주입 대상은 IsSellGo=False → hold_days 사이.
    '''
    # 먼저 하드스탑 상수 3종을 파일 상단에 추가
    const_block = (
        f"\nENABLE_122630_HARD_STOP = True\n"
        f"HARD_STOP_122630_PCT_TIGHT = {tight_pct}\n"
        f"HARD_STOP_122630_PCT_BASE = {base_pct}\n"
    )
    # HARD_STOP_VOL_TH 이미 존재, 그 밑에 삽입
    anchor = "HARD_STOP_VOL_TH = 0.045"
    if anchor not in src:
        raise RuntimeError("anchor HARD_STOP_VOL_TH not found")
    src = src.replace(anchor, anchor + const_block, 1)

    # 하드스탑 로직 삽입
    marker = (
        "                    IsSellGo = False\n"
        "                    hold_days = calc_hold_days(date, investData.get('Date', str(date)))\n"
    )
    if marker not in src:
        raise RuntimeError("KOSPI sell marker not found")
    inject = (
        "                    IsSellGo = False\n"
        "                    hold_days = calc_hold_days(date, investData.get('Date', str(date)))\n"
        "                    # [INJECTED Step3] 122630 하드스탑 - SellPrice/IsSellGo를 InvestMoney 업데이트 전에 확정\n"
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


def patch_source(src: str, start_year: int, steps: set,
                 equity_csv: Path, trades_csv: Path) -> str:
    src = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {start_year}', src)

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


def run(label: str, steps: set) -> dict:
    equity_csv = OUT_DIR / f'v7_stack_{label}_equity.csv'
    trades_csv = OUT_DIR / f'v7_stack_{label}_trades.csv'
    with open(trades_csv, 'w') as f:
        f.write('date,code,name,buy_date,buy_price,first_money,sell_price,revenue_rate,return_money\n')
    src = BASE_FILE.read_text()
    patched = patch_source(src, 2025, steps, equity_csv, trades_csv)
    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE_FILE.parent),
                                     mode='w', delete=False) as f:
        tmp = Path(f.name)
        f.write(patched)

    print(f"\n[run] {label}  steps={sorted(steps)}")
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              capture_output=True, text=True, timeout=1500,
                              cwd=str(BASE_FILE.parent))
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print(f"[run] {label} FAILED\n{proc.stderr[-1500:]}")
        return {'label': label, 'ok': False}

    df = pd.read_csv(equity_csv, index_col=0, parse_dates=[0]).sort_index()
    df['Total_Money'] = df['Total_Money'].astype(float)
    end = df.index[-1]
    oy = df[df.index >= end - pd.Timedelta(days=365)]
    final = float(df['Total_Money'].iloc[-1])
    ret_1y = (final / float(oy['Total_Money'].iloc[0]) - 1) * 100
    cm = oy['Total_Money'].cummax()
    mdd_1y = float(((oy['Total_Money'] / cm) - 1).min() * 100)

    tdf = df[df.index.year >= 2025]
    ret_all = (final / float(tdf['Total_Money'].iloc[0]) - 1) * 100
    mdd_all = float(((tdf['Total_Money'] / tdf['Total_Money'].cummax()) - 1).min() * 100)

    mar = df[(df.index.year == 2026) & (df.index.month == 3)]
    mar_ret = None
    if len(mar):
        mar_ret = (float(mar['Total_Money'].iloc[-1]) /
                   float(mar['Total_Money'].iloc[0]) - 1) * 100

    tr = pd.read_csv(trades_csv)
    tr['code'] = tr['code'].astype(str).str.zfill(6)
    stats_by_code = tr.groupby('code').agg(
        n=('revenue_rate', 'count'),
        wr=('revenue_rate', lambda s: (s > 0).mean() * 100),
        avg=('revenue_rate', 'mean'),
    ).round(2)

    return {
        'label': label, 'ok': True,
        'ret_1y': round(ret_1y, 2), 'mdd_1y': round(mdd_1y, 2),
        'ret_all': round(ret_all, 2), 'mdd_all': round(mdd_all, 2),
        'mar2026': round(mar_ret, 2) if mar_ret is not None else None,
        'final': int(final),
        'trades': len(tr),
        'stats_by_code': stats_by_code.to_dict('index'),
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
    for label, steps in configs:
        r = run(label, steps)
        rows.append(r)
        code_breakdowns[label] = r.get('stats_by_code', {})

    df = pd.DataFrame([{k: v for k, v in r.items() if k != 'stats_by_code'}
                        for r in rows if r.get('ok')])
    df = df[['label', 'ret_1y', 'mdd_1y', 'ret_all', 'mdd_all',
             'mar2026', 'trades', 'final']]
    print("\n" + "=" * 100)
    print("   스택 비교: Step 1→2→3 누적 개선")
    print("=" * 100)
    print(df.to_string(index=False))

    print("\n[종목별 성과 (거래수/승률/평균 수익률)]")
    all_codes = set()
    for b in code_breakdowns.values():
        all_codes.update(b.keys())
    all_codes = sorted(all_codes)

    hdr = "code      " + "  ".join(f"{lbl:>28}" for lbl in code_breakdowns.keys())
    print(hdr)
    for c in all_codes:
        row = f"{c:<10}"
        for lbl in code_breakdowns.keys():
            d = code_breakdowns[lbl].get(c)
            if d:
                row += f"  {int(d['n']):>5}t {d['wr']:>5.1f}% {d['avg']:+6.2f}%       "
            else:
                row += f"  {'(none)':>28}"
        print(row)

    df.to_csv(OUT_DIR / 'v7_improvements_stack.csv', index=False)
    print(f"\n[saved] {OUT_DIR / 'v7_improvements_stack.csv'}")


if __name__ == "__main__":
    main()
