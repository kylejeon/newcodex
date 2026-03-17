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

# (label, start_year, end_year)
PERIODS = [
    ('full', 2017, 2099),
    ('2017_2021', 2017, 2021),
    ('2022_2026', 2022, 2026),
    ('2017_2019', 2017, 2019),
    ('2020_2022', 2020, 2022),
    ('2023_2026', 2023, 2026),
]

RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)')
RE_RETURN_MDD = re.compile(r'수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%')
RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%')
RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%')


def patch_for_period(src: str, start_year: int, end_year: int) -> str:
    out = src
    out = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {start_year}', out)

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
        'ori': int(m1.group(1).replace(',', '')),
        'final': int(m1.group(2).replace(',', '')),
        'ret': float(m2.group(1)),
        'mdd': float(m2.group(2)),
        'success': int(m3.group(1)),
        'fail': int(m3.group(2)),
        'win': float(m3.group(3)),
        'cagr': float(m4.group(1)),
    }


def run_script(tmp_path: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env['MPLBACKEND'] = 'Agg'
    old_pp = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f'{BASE_DIR}:{old_pp}' if old_pp else str(BASE_DIR)

    p = subprocess.run(
        [sys.executable, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=str(BASE_DIR),
        timeout=1800,
    )
    return p.returncode, p.stdout


def main() -> int:
    if not BASE_FILE.exists():
        print(f'[ERROR] not found: {BASE_FILE}')
        return 1

    src = BASE_FILE.read_text(encoding='utf-8')
    rows = []

    for label, sy, ey in PERIODS:
        print(f'[RUN] period={label} start={sy} end={ey}')
        patched = patch_for_period(src, sy, ey)

        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8', dir=str(BASE_DIR)) as tf:
            tf.write(patched)
            tmp_path = Path(tf.name)

        try:
            code, out = run_script(tmp_path)
        except subprocess.TimeoutExpired:
            rows.append((label, False, 'timeout', None))
            tmp_path.unlink(missing_ok=True)
            continue

        metric = parse_metrics(out)
        if code != 0 or not metric.get('ok'):
            tail = '\n'.join(out.splitlines()[-20:])
            rows.append((label, False, f'code={code}', tail))
        else:
            rows.append((label, True, metric, None))

        tmp_path.unlink(missing_ok=True)

    print('\n================ V7 PERIOD SUMMARY ================')
    print('period\tok\tret%\tmdd%\tcagr%\twin%\tfinal')
    for label, ok, info, tail in rows:
        if ok:
            m = info
            print(f"{label}\tY\t{m['ret']:.2f}\t{m['mdd']:.2f}\t{m['cagr']:.2f}\t{m['win']:.2f}\t{m['final']:,}")
        else:
            print(f'{label}\tN\t-\t-\t-\t-\t-')
            if tail:
                print('--- tail ---')
                print(tail)
                print('------------')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
