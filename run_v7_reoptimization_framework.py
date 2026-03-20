#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import itertools
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_FILE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_best.py')
BASE_DIR = BASE_FILE.parent

# 기간별 검증 세트
PERIODS = {
    'past': (2017, 2021),
    'recent': (2022, 2026),
    'full': (2017, 2099),
    'recent_short': (2024, 2026),
}

# 코스피 후보
KOSPI_PROFILES = [
    {
        'label': 'kospi_base',
        'KOSPI_252670_DISPARITY11_TH': 106,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 0,
        'KOSPI_252670_BUY_RSI_MAX': 70,
        'KOSPI_122630_BUY_DISPARITY_LOW': 97,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 107,
        'KOSPI_122630_BUY_RSI_MAX': 80,
    },
    {
        'label': 'kospi_buy_wide_disp',
        'KOSPI_252670_DISPARITY11_TH': 106,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 0,
        'KOSPI_252670_BUY_RSI_MAX': 70,
        'KOSPI_122630_BUY_DISPARITY_LOW': 97,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 107,
        'KOSPI_122630_BUY_RSI_MAX': 80,
    },
    {
        'label': 'kospi_combo_balance',
        'KOSPI_252670_DISPARITY11_TH': 106,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 1,
        'KOSPI_252670_BUY_RSI_MAX': 71,
        'KOSPI_122630_BUY_DISPARITY_LOW': 98,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 106,
        'KOSPI_122630_BUY_RSI_MAX': 80,
    },
    {
        'label': 'kospi_sell_d11_107',
        'KOSPI_252670_DISPARITY11_TH': 107,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 0,
        'KOSPI_252670_BUY_RSI_MAX': 70,
        'KOSPI_122630_BUY_DISPARITY_LOW': 98,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 106,
        'KOSPI_122630_BUY_RSI_MAX': 80,
    },
]

# 코스닥 후보
KOSDAQ_PROFILES = [
    {
        'label': 'kosdaq_v7_current',
        'KOSDAQ_251340_CUT_RATE': 0.35,
        'KOSDAQ_233740_CUT_RATE_BULL': 0.35,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.25,
        'HARD_STOP_233740_PCT_TIGHT': 0.085,
        'HARD_STOP_233740_PCT_BASE': 0.125,
    },
    {
        'label': 'kosdaq_mild_loose',
        'KOSDAQ_251340_CUT_RATE': 0.36,
        'KOSDAQ_233740_CUT_RATE_BULL': 0.36,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.26,
        'HARD_STOP_233740_PCT_TIGHT': 0.085,
        'HARD_STOP_233740_PCT_BASE': 0.125,
    },
    {
        'label': 'kosdaq_loose_251340',
        'KOSDAQ_251340_CUT_RATE': 0.37,
        'KOSDAQ_233740_CUT_RATE_BULL': 0.35,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.25,
        'HARD_STOP_233740_PCT_TIGHT': 0.085,
        'HARD_STOP_233740_PCT_BASE': 0.125,
    },
    {
        'label': 'kosdaq_loose_233740',
        'KOSDAQ_251340_CUT_RATE': 0.35,
        'KOSDAQ_233740_CUT_RATE_BULL': 0.36,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.26,
        'HARD_STOP_233740_PCT_TIGHT': 0.085,
        'HARD_STOP_233740_PCT_BASE': 0.125,
    },
    {
        'label': 'kosdaq_loose_hardstop',
        'KOSDAQ_251340_CUT_RATE': 0.35,
        'KOSDAQ_233740_CUT_RATE_BULL': 0.35,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.25,
        'HARD_STOP_233740_PCT_TIGHT': 0.090,
        'HARD_STOP_233740_PCT_BASE': 0.130,
    },
]

# 최근장 적합도 + 과최적화 방지 제약
MIN_PAST_CAGR = float(os.getenv('MIN_PAST_CAGR', '30.0'))
MIN_PAST_RET = float(os.getenv('MIN_PAST_RET', '800.0'))
MAX_PAST_MDD_ABS = float(os.getenv('MAX_PAST_MDD_ABS', '15.0'))
RECENT_SCORE_MDD_PENALTY = float(os.getenv('RECENT_SCORE_MDD_PENALTY', '0.35'))

RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)')
RE_RETURN_MDD = re.compile(r'수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%')
RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%')
RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%')


def patch_for_period(src: str, start_year: int, end_year: int) -> str:
    out = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {start_year}', src)
    if 'EndYear =' in out:
        out = re.sub(r'EndYear\s*=\s*\d+', f'EndYear = {end_year}', out)
    else:
        out = out.replace(f'StartYear = {start_year}', f'StartYear = {start_year}\nEndYear = {end_year}')

    out = out.replace(
        'int(date_object.strftime("%Y")) >= StartYear',
        'int(date_object.strftime("%Y")) >= StartYear and int(date_object.strftime("%Y")) <= EndYear',
    )
    return out


def patch_simple_assignment(src: str, name: str, value) -> str:
    if isinstance(value, float):
        repl = f'{name} = {value:.6f}'.rstrip('0').rstrip('.')
    else:
        repl = f'{name} = {value}'
    return re.sub(rf'{name}\s*=\s*([^\n#]+)', repl, src)


def patch_kosdaq_logic(src: str, profile: dict) -> str:
    out = src
    out = patch_simple_assignment(out, 'HARD_STOP_233740_PCT_TIGHT', profile['HARD_STOP_233740_PCT_TIGHT'])
    out = patch_simple_assignment(out, 'HARD_STOP_233740_PCT_BASE', profile['HARD_STOP_233740_PCT_BASE'])

    out = re.sub(
        r'if stock_code == "251340":\n\s+CutRate = [0-9.]+',
        f'if stock_code == "251340":\n                        CutRate = {profile["KOSDAQ_251340_CUT_RATE"]}',
        out,
    )
    out = re.sub(
        r'if PrevClosePrice > stock_data\[\'ma60_before\'\]\.values\[0\]:\n\s+CutRate = [0-9.]+\n\s+else:\n\s+CutRate = [0-9.]+',
        (
            f'if PrevClosePrice > stock_data[\'ma60_before\'].values[0]:\n'
            f'                            CutRate = {profile["KOSDAQ_233740_CUT_RATE_BULL"]}\n'
            f'                        else:\n'
            f'                            CutRate = {profile["KOSDAQ_233740_CUT_RATE_BEAR"]}'
        ),
        out,
    )
    return out


def patch_script(src: str, sy: int, ey: int, kospi: dict, kosdaq: dict) -> str:
    out = patch_for_period(src, sy, ey)
    for key, value in kospi.items():
        if key == 'label':
            continue
        out = patch_simple_assignment(out, key, value)
    out = patch_kosdaq_logic(out, kosdaq)
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


def run_period(src: str, sy: int, ey: int, kospi: dict, kosdaq: dict):
    patched = patch_script(src, sy, ey, kospi, kosdaq)
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


def pass_constraints(metric_past: dict) -> bool:
    if metric_past['cagr'] < MIN_PAST_CAGR:
        return False
    if metric_past['ret'] < MIN_PAST_RET:
        return False
    if abs(metric_past['mdd']) > MAX_PAST_MDD_ABS:
        return False
    return True


def score_recent(metric_recent: dict) -> float:
    return metric_recent['cagr'] - abs(metric_recent['mdd']) * RECENT_SCORE_MDD_PENALTY


def score_stability(metric_past: dict, metric_recent: dict, metric_full: dict) -> float:
    return (
        score_recent(metric_recent) * 0.5
        + (metric_past['cagr'] - abs(metric_past['mdd']) * 0.2) * 0.3
        + (metric_full['cagr'] - abs(metric_full['mdd']) * 0.15) * 0.2
    )


def main() -> int:
    if not BASE_FILE.exists():
        print(f'[ERROR] not found: {BASE_FILE}')
        return 1

    src = BASE_FILE.read_text(encoding='utf-8')
    rows = []

    print('=== Reoptimization Constraints ===')
    print(f'MIN_PAST_CAGR={MIN_PAST_CAGR}, MIN_PAST_RET={MIN_PAST_RET}, MAX_PAST_MDD_ABS={MAX_PAST_MDD_ABS}')
    print(f'RECENT_SCORE_MDD_PENALTY={RECENT_SCORE_MDD_PENALTY}')
    print()

    for kospi, kosdaq in itertools.product(KOSPI_PROFILES, KOSDAQ_PROFILES):
        label = f"{kospi['label']}__{kosdaq['label']}"
        print(f'[RUN] {label}')

        results = {}
        ok_all = True
        for period_name, (sy, ey) in PERIODS.items():
            ok, metric = run_period(src, sy, ey, kospi, kosdaq)
            if not ok:
                rows.append({
                    'label': label,
                    'ok': False,
                    'period': period_name,
                    'error': metric,
                })
                ok_all = False
                break
            results[period_name] = metric

        if not ok_all:
            continue

        feasible = pass_constraints(results['past'])
        rows.append({
            'label': label,
            'ok': True,
            'feasible': feasible,
            'recent_score': score_recent(results['recent']),
            'stability_score': score_stability(results['past'], results['recent'], results['full']),
            'past': results['past'],
            'recent': results['recent'],
            'recent_short': results['recent_short'],
            'full': results['full'],
        })

    print('\n================ RESULT TABLE ================')
    print('label\tfeasible\trecent_score\tstability\tpast_cagr\tpast_mdd\trecent_cagr\trecent_mdd\tshort_cagr\tshort_mdd\tfull_cagr\tfull_mdd')
    for row in rows:
        if not row['ok']:
            print(f"{row['label']}\tN/A\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-")
            print('--- tail ---')
            print(row['error']['tail'])
            print('------------')
            continue
        print(
            f"{row['label']}\t{'Y' if row['feasible'] else 'N'}\t"
            f"{row['recent_score']:.2f}\t{row['stability_score']:.2f}\t"
            f"{row['past']['cagr']:.2f}\t{row['past']['mdd']:.2f}\t"
            f"{row['recent']['cagr']:.2f}\t{row['recent']['mdd']:.2f}\t"
            f"{row['recent_short']['cagr']:.2f}\t{row['recent_short']['mdd']:.2f}\t"
            f"{row['full']['cagr']:.2f}\t{row['full']['mdd']:.2f}"
        )

    feasible_rows = [r for r in rows if r.get('ok') and r.get('feasible')]
    feasible_rows.sort(key=lambda x: (x['stability_score'], x['recent_score']), reverse=True)

    print('\n================ FEASIBLE RANK ================')
    for i, row in enumerate(feasible_rows[:15], 1):
        print(
            f"{i}. {row['label']} | stability={row['stability_score']:.2f} | recent={row['recent_score']:.2f} | "
            f"past(cagr={row['past']['cagr']:.2f}, mdd={row['past']['mdd']:.2f}) | "
            f"recent(cagr={row['recent']['cagr']:.2f}, mdd={row['recent']['mdd']:.2f}) | "
            f"recent_short(cagr={row['recent_short']['cagr']:.2f}, mdd={row['recent_short']['mdd']:.2f}) | "
            f"full(cagr={row['full']['cagr']:.2f}, mdd={row['full']['mdd']:.2f})"
        )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
