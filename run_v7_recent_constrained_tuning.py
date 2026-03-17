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

# 코스피 튜닝 후보 (기존 탐색셋 재사용)
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

PERIODS = {
    'past': (2017, 2021),
    'recent': (2022, 2026),
    'full': (2017, 2099),
}

# --- 제약 조건(2번) ---
MIN_PAST_CAGR = float(os.getenv('MIN_PAST_CAGR', '30.0'))
MIN_PAST_RET = float(os.getenv('MIN_PAST_RET', '800.0'))
MAX_PAST_MDD_ABS = float(os.getenv('MAX_PAST_MDD_ABS', '15.0'))

# --- 최근장 가중 목적함수(1번) ---
RECENT_SCORE_MDD_PENALTY = float(os.getenv('RECENT_SCORE_MDD_PENALTY', '0.35'))

RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)')
RE_RETURN_MDD = re.compile(r'수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%')
RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%')
RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%')


def patch_script(src: str, sy: int, ey: int, d11: int, d20_low: int, d20_high: int, hold_days: int,
                 buy_rsi_252670: int, buy_disp_low_122630: int, buy_disp_high_122630: int, buy_rsi_122630: int) -> str:
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


def recent_score(metric_recent: dict) -> float:
    return metric_recent['cagr'] - abs(metric_recent['mdd']) * RECENT_SCORE_MDD_PENALTY


def pass_constraints(metric_past: dict) -> bool:
    if metric_past['cagr'] < MIN_PAST_CAGR:
        return False
    if metric_past['ret'] < MIN_PAST_RET:
        return False
    if abs(metric_past['mdd']) > MAX_PAST_MDD_ABS:
        return False
    return True


def run_period(src: str, params: tuple, period_key: str):
    sy, ey = PERIODS[period_key]
    patched = patch_script(src, sy, ey, *params)
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8', dir=str(BASE_DIR)) as tf:
        tf.write(patched)
        tmp_path = Path(tf.name)
    try:
        code, out = run_one(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    metric = parse_metrics(out)
    if code != 0 or not metric.get('ok'):
        tail = '\n'.join(out.splitlines()[-20:])
        return False, {'code': code, 'tail': tail}
    return True, metric


def main() -> int:
    if not BASE_FILE.exists():
        print(f'[ERROR] not found: {BASE_FILE}')
        return 1

    src = BASE_FILE.read_text(encoding='utf-8')

    print('=== Constraints ===')
    print(f'MIN_PAST_CAGR={MIN_PAST_CAGR}, MIN_PAST_RET={MIN_PAST_RET}, MAX_PAST_MDD_ABS={MAX_PAST_MDD_ABS}')
    print(f'RECENT_SCORE_MDD_PENALTY={RECENT_SCORE_MDD_PENALTY}')
    print()

    rows = []

    for row in KOSPI_PARAM_GRID:
        label, *params = row
        print(f"[RUN] {label}")

        ok_past, past = run_period(src, tuple(params), 'past')
        ok_recent, recent = run_period(src, tuple(params), 'recent')
        ok_full, full = run_period(src, tuple(params), 'full')

        if not (ok_past and ok_recent and ok_full):
            rows.append({
                'label': label,
                'ok': False,
                'error': {
                    'past': past if not ok_past else None,
                    'recent': recent if not ok_recent else None,
                    'full': full if not ok_full else None,
                }
            })
            continue

        feasible = pass_constraints(past)
        score = recent_score(recent)
        rows.append({
            'label': label,
            'ok': True,
            'feasible': feasible,
            'score': score,
            'past': past,
            'recent': recent,
            'full': full,
        })

    print('\n================ RESULT TABLE ================')
    print('label\tfeasible\trecent_score\trecent_cagr\trecent_mdd\tpast_cagr\tpast_mdd\tfull_cagr\tfull_mdd')
    for r in rows:
        if not r['ok']:
            print(f"{r['label']}\tN/A\t-\t-\t-\t-\t-\t-\t-")
            continue
        print(
            f"{r['label']}\t{'Y' if r['feasible'] else 'N'}\t{r['score']:.2f}\t"
            f"{r['recent']['cagr']:.2f}\t{r['recent']['mdd']:.2f}\t"
            f"{r['past']['cagr']:.2f}\t{r['past']['mdd']:.2f}\t"
            f"{r['full']['cagr']:.2f}\t{r['full']['mdd']:.2f}"
        )

    feasible_rows = [r for r in rows if r.get('ok') and r.get('feasible')]
    feasible_rows.sort(key=lambda x: x['score'], reverse=True)

    print('\n================ FEASIBLE RANK (recent_score) ================')
    if not feasible_rows:
        print('No feasible candidates. 제약 조건을 완화해서 재실행하세요.')
    else:
        for i, r in enumerate(feasible_rows, 1):
            print(
                f"{i}. {r['label']} | score={r['score']:.2f} | "
                f"recent(cagr={r['recent']['cagr']:.2f}, mdd={r['recent']['mdd']:.2f}) | "
                f"past(cagr={r['past']['cagr']:.2f}, mdd={r['past']['mdd']:.2f}) | "
                f"full(cagr={r['full']['cagr']:.2f}, mdd={r['full']['mdd']:.2f})"
            )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
