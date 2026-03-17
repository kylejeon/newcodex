#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_FILE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_best.py')
BASE_DIR = BASE_FILE.parent

# 코스피 튜닝 조합
KOSPI_PARAM_GRID = [
    # label, sell_d11_th, sell_d20_low, sell_d20_high, min_hold_days, buy_rsi_252670, buy_disp_low_122630, buy_disp_high_122630, buy_rsi_122630
    ('base', 106, 98, 105, 0, 70, 98, 106, 80),
    ('buy_loose_rsi', 106, 98, 105, 0, 72, 98, 106, 82),
    ('buy_tight_rsi', 106, 98, 105, 0, 68, 98, 106, 78),
    ('buy_wide_disp', 106, 98, 105, 0, 70, 97, 107, 80),
    ('buy_tight_disp', 106, 98, 105, 0, 70, 99, 105, 80),
    ('sell_d11_105', 105, 98, 105, 0, 70, 98, 106, 80),
    ('sell_d11_107', 107, 98, 105, 0, 70, 98, 106, 80),
    ('combo_attack', 106, 98, 105, 0, 73, 97, 107, 82),
    ('combo_balance', 106, 98, 105, 1, 71, 98, 106, 80),
]

PERIODS = [
    ('full', 2017, 2099),
    ('2022_2026', 2022, 2026),
    ('2023_2026', 2023, 2026),
]

RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)')
RE_RETURN_MDD = re.compile(r'수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%')
RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%')
RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%')


def patch_script(
    src: str,
    sy: int,
    ey: int,
    d11: int,
    d20_low: int,
    d20_high: int,
    hold_days: int,
    buy_rsi_252670: int,
    buy_disp_low_122630: int,
    buy_disp_high_122630: int,
    buy_rsi_122630: int,
) -> str:
    out = src

    out = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {sy}', out)
    if 'EndYear =' in out:
        out = re.sub(r'EndYear\s*=\s*\d+', f'EndYear = {ey}', out)
    else:
        out = out.replace(f'StartYear = {sy}', f'StartYear = {sy}\nEndYear = {ey}')

    out = out.replace(
        'int(date_object.strftime("%Y")) >= StartYear',
        'int(date_object.strftime("%Y")) >= StartYear and int(date_object.strftime("%Y")) <= EndYear',
    )

    out = re.sub(r'KOSPI_252670_DISPARITY11_TH\s*=\s*\d+', f'KOSPI_252670_DISPARITY11_TH = {d11}', out)
    out = re.sub(r'KOSPI_122630_DISPARITY_LOW\s*=\s*\d+', f'KOSPI_122630_DISPARITY_LOW = {d20_low}', out)
    out = re.sub(r'KOSPI_122630_DISPARITY_HIGH\s*=\s*\d+', f'KOSPI_122630_DISPARITY_HIGH = {d20_high}', out)
    out = re.sub(r'KOSPI_MIN_HOLD_DAYS\s*=\s*\d+', f'KOSPI_MIN_HOLD_DAYS = {hold_days}', out)
    out = re.sub(r'KOSPI_252670_BUY_RSI_MAX\s*=\s*\d+', f'KOSPI_252670_BUY_RSI_MAX = {buy_rsi_252670}', out)
    out = re.sub(r'KOSPI_122630_BUY_DISPARITY_LOW\s*=\s*\d+', f'KOSPI_122630_BUY_DISPARITY_LOW = {buy_disp_low_122630}', out)
    out = re.sub(r'KOSPI_122630_BUY_DISPARITY_HIGH\s*=\s*\d+', f'KOSPI_122630_BUY_DISPARITY_HIGH = {buy_disp_high_122630}', out)
    out = re.sub(r'KOSPI_122630_BUY_RSI_MAX\s*=\s*\d+', f'KOSPI_122630_BUY_RSI_MAX = {buy_rsi_122630}', out)

    out = out.replace('plt.show()', "print('[INFO] plot skipped')")
    return out


def parse_metrics(text: str) -> dict:
    m1 = RE_FINAL.search(text)
    m2 = RE_RETURN_MDD.search(text)
    m3 = RE_WIN.search(text)
    m4 = RE_CAGR.search(text)
    if not (m1 and m2 and m3 and m4):
        return {'ok': False}
    return {
        'ok': True,
        'final': int(m1.group(2).replace(',', '')),
        'ret': float(m2.group(1)),
        'mdd': float(m2.group(2)),
        'win': float(m3.group(3)),
        'cagr': float(m4.group(1)),
    }


def run_one(py_path: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env['MPLBACKEND'] = 'Agg'
    old_pp = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f'{BASE_DIR}:{old_pp}' if old_pp else str(BASE_DIR)
    p = subprocess.run(
        [sys.executable, str(py_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(BASE_DIR),
        env=env,
        timeout=1800,
    )
    return p.returncode, p.stdout


def score(metric: dict) -> float:
    # CAGR 높고 MDD 절대값 낮을수록 가산
    return metric['cagr'] - (abs(metric['mdd']) * 0.35)


def main() -> int:
    src = BASE_FILE.read_text(encoding='utf-8')
    rows = []

    for label, d11, lo, hi, hold, buy_rsi_252670, buy_disp_low_122630, buy_disp_high_122630, buy_rsi_122630 in KOSPI_PARAM_GRID:
        for plabel, sy, ey in PERIODS:
            print(
                f'[RUN] {label} | {plabel} | d11={d11} d20=({lo},{hi}) hold={hold} '
                f'brsi={buy_rsi_252670} bdisp=({buy_disp_low_122630},{buy_disp_high_122630}) brsiL={buy_rsi_122630}'
            )
            patched = patch_script(
                src, sy, ey, d11, lo, hi, hold,
                buy_rsi_252670, buy_disp_low_122630, buy_disp_high_122630, buy_rsi_122630
            )
            with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8', dir=str(BASE_DIR)) as tf:
                tf.write(patched)
                tmp_path = Path(tf.name)

            try:
                code, out = run_one(tmp_path)
            except subprocess.TimeoutExpired:
                rows.append((label, plabel, False, 'timeout', None))
                tmp_path.unlink(missing_ok=True)
                continue

            m = parse_metrics(out)
            if code != 0 or not m.get('ok'):
                tail = '\n'.join(out.splitlines()[-20:])
                rows.append((label, plabel, False, f'code={code}', tail))
            else:
                rows.append((label, plabel, True, m, None))

            tmp_path.unlink(missing_ok=True)

    print('\n================ KOSPI TUNING SUMMARY ================')
    print('label\tperiod\tok\tret%\tmdd%\tcagr%\twin%\tfinal\tscore')
    ok_rows = []
    for label, plabel, ok, info, tail in rows:
        if ok:
            m = info
            s = score(m)
            ok_rows.append((label, plabel, s, m))
            print(f"{label}\t{plabel}\tY\t{m['ret']:.2f}\t{m['mdd']:.2f}\t{m['cagr']:.2f}\t{m['win']:.2f}\t{m['final']:,}\t{s:.2f}")
        else:
            print(f'{label}\t{plabel}\tN\t-\t-\t-\t-\t-\t-')
            if tail:
                print('--- tail ---')
                print(tail)
                print('------------')

    # full 기간 기준 랭킹
    full_rank = [(label, s, m) for (label, p, s, m) in ok_rows if p == 'full']
    full_rank.sort(key=lambda x: x[1], reverse=True)

    print('\n================ FULL RANK (score desc) ================')
    for i, (label, s, m) in enumerate(full_rank[:10], 1):
        print(f"{i}. {label}: cagr={m['cagr']:.2f}, mdd={m['mdd']:.2f}, ret={m['ret']:.2f}, score={s:.2f}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
