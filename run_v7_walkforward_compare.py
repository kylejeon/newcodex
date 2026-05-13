#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BEST_FILE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_best.py')
DEFENSE_FILE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_defense.py')
BASE_DIR = BEST_FILE.parent

# Walk-forward windows: 5년 학습 + 2년 검증을 1년씩 이동
WINDOWS = [
    ('wf_2017_2021__2022_2023', 2017, 2021, 2022, 2023),
    ('wf_2018_2022__2023_2024', 2018, 2022, 2023, 2024),
    ('wf_2019_2023__2024_2025', 2019, 2023, 2024, 2025),
    ('wf_2020_2024__2025_2026', 2020, 2024, 2025, 2026),
]

EXTRA_PERIODS = {
    'recent_2022_2026': (2022, 2026),
    'full': (2017, 2099),
}

RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)')
RE_RETURN_MDD = re.compile(r'수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%')
RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%')
RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%')


def patch_period(src: str, start_year: int, end_year: int) -> str:
    out = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {start_year}', src)
    if 'EndYear =' in out:
        out = re.sub(r'EndYear\s*=\s*\d+', f'EndYear = {end_year}', out)
    else:
        out = out.replace(f'StartYear = {start_year}', f'StartYear = {start_year}\nEndYear = {end_year}')

    out = out.replace(
        'int(date_object.strftime("%Y")) >= StartYear',
        'int(date_object.strftime("%Y")) >= StartYear and int(date_object.strftime("%Y")) <= EndYear',
    )
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


def run_script(py_path: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env['MPLBACKEND'] = 'Agg'
    old_pp = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f'{BASE_DIR}:{old_pp}' if old_pp else str(BASE_DIR)
    proc = subprocess.run(
        [sys.executable, str(py_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(BASE_DIR),
        env=env,
        timeout=1800,
    )
    return proc.returncode, proc.stdout


def run_period(src: str, sy: int, ey: int) -> tuple[bool, dict]:
    patched = patch_period(src, sy, ey)
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8', dir=str(BASE_DIR)) as tf:
        tf.write(patched)
        tmp_path = Path(tf.name)
    try:
        code, out = run_script(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    metric = parse_metrics(out)
    if code != 0 or not metric.get('ok'):
        return False, {
            'code': code,
            'tail': '\n'.join(out.splitlines()[-20:]),
        }
    return True, metric


def score_test(metric: dict) -> float:
    return metric['cagr'] - abs(metric['mdd']) * 0.35


def train_test_gap(train: dict, test: dict) -> float:
    return train['cagr'] - test['cagr']


def robustness_score(window_rows: list[dict], recent_metric: dict, full_metric: dict) -> float:
    avg_test_score = sum(score_test(r['test']) for r in window_rows) / len(window_rows)
    avg_gap = sum(train_test_gap(r['train'], r['test']) for r in window_rows) / len(window_rows)
    fail_count = sum(1 for r in window_rows if r['test']['ret'] < 0)
    return (
        avg_test_score * 0.55
        + (recent_metric['cagr'] - abs(recent_metric['mdd']) * 0.25) * 0.25
        + (full_metric['cagr'] - abs(full_metric['mdd']) * 0.15) * 0.20
        - fail_count * 2.0
        - max(avg_gap, 0) * 0.08
    )


def evaluate_variant(label: str, file_path: Path) -> dict:
    src = file_path.read_text(encoding='utf-8')
    rows = []
    for win_label, tr_sy, tr_ey, te_sy, te_ey in WINDOWS:
        print(f'[RUN] {label} {win_label}')
        ok_train, train_metric = run_period(src, tr_sy, tr_ey)
        if not ok_train:
            return {'ok': False, 'label': label, 'error': f'{win_label} train failed\n{train_metric["tail"]}'}

        ok_test, test_metric = run_period(src, te_sy, te_ey)
        if not ok_test:
            return {'ok': False, 'label': label, 'error': f'{win_label} test failed\n{test_metric["tail"]}'}

        rows.append({
            'label': win_label,
            'train': train_metric,
            'test': test_metric,
        })

    extra = {}
    for name, (sy, ey) in EXTRA_PERIODS.items():
        print(f'[RUN] {label} {name}')
        ok, metric = run_period(src, sy, ey)
        if not ok:
            return {'ok': False, 'label': label, 'error': f'{name} failed\n{metric["tail"]}'}
        extra[name] = metric

    avg_test_cagr = sum(r['test']['cagr'] for r in rows) / len(rows)
    avg_test_mdd = sum(abs(r['test']['mdd']) for r in rows) / len(rows)
    avg_gap = sum(train_test_gap(r['train'], r['test']) for r in rows) / len(rows)
    fail_count = sum(1 for r in rows if r['test']['ret'] < 0)

    return {
        'ok': True,
        'label': label,
        'windows': rows,
        'recent': extra['recent_2022_2026'],
        'full': extra['full'],
        'avg_test_cagr': avg_test_cagr,
        'avg_test_mdd_abs': avg_test_mdd,
        'avg_gap': avg_gap,
        'fail_count': fail_count,
        'score': robustness_score(rows, extra['recent_2022_2026'], extra['full']),
    }


def print_window_table(result: dict) -> None:
    print(f"\n[{result['label']} windows]")
    print('window\ttrain_cagr\ttrain_mdd\ttest_cagr\ttest_mdd\ttest_ret\tgap')
    for row in result['windows']:
        gap = train_test_gap(row['train'], row['test'])
        print(
            f"{row['label']}\t"
            f"{row['train']['cagr']:.2f}\t{row['train']['mdd']:.2f}\t"
            f"{row['test']['cagr']:.2f}\t{row['test']['mdd']:.2f}\t"
            f"{row['test']['ret']:.2f}\t{gap:.2f}"
        )


def main() -> int:
    missing = [str(p) for p in (BEST_FILE, DEFENSE_FILE) if not p.exists()]
    if missing:
        print('[ERROR] missing files:')
        for p in missing:
            print(p)
        return 1

    best = evaluate_variant('best', BEST_FILE)
    defense = evaluate_variant('defense', DEFENSE_FILE)

    for result in (best, defense):
        if not result['ok']:
            print(f"[ERROR] {result['label']} failed")
            print(result['error'])
            return 1

    print('\n================ WALK-FORWARD SUMMARY ================')
    print('label\tscore\tavg_test_cagr\tavg_test_mdd\tavg_gap\tfail_windows\trecent_cagr\trecent_mdd\tfull_cagr\tfull_mdd')
    for result in sorted([best, defense], key=lambda x: x['score'], reverse=True):
        print(
            f"{result['label']}\t{result['score']:.2f}\t{result['avg_test_cagr']:.2f}\t"
            f"-{result['avg_test_mdd_abs']:.2f}\t{result['avg_gap']:.2f}\t{result['fail_count']}\t"
            f"{result['recent']['cagr']:.2f}\t{result['recent']['mdd']:.2f}\t"
            f"{result['full']['cagr']:.2f}\t{result['full']['mdd']:.2f}"
        )

    print_window_table(best)
    print_window_table(defense)

    winner = max([best, defense], key=lambda x: x['score'])
    print('\n================ INTERPRETATION ================')
    print(
        f"more robust candidate: {winner['label']} | "
        f"score={winner['score']:.2f}, avg_test_cagr={winner['avg_test_cagr']:.2f}, "
        f"avg_test_mdd=-{winner['avg_test_mdd_abs']:.2f}, avg_gap={winner['avg_gap']:.2f}, "
        f"fail_windows={winner['fail_count']}"
    )
    print('Guide: avg_gap이 클수록 학습구간 대비 검증구간 성과가 많이 빠진 것이고, fail_windows가 많을수록 과최적화 가능성이 큽니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
