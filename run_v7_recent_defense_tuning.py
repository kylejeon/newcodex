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

PERIODS = {
    'march_2026': (2026, 2026),
    'recent': (2022, 2026),
    'full': (2017, 2099),
}

# 122630 방어 후보
KOSPI_DEFENSE_PROFILES = [
    {
        'label': 'kp_base',
        'KOSPI_122630_BUY_DISPARITY_LOW': 97,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 107,
        'KOSPI_122630_BUY_RSI_MAX': 80,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 0,
    },
    {
        'label': 'kp_tight_buy',
        'KOSPI_122630_BUY_DISPARITY_LOW': 98,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 106,
        'KOSPI_122630_BUY_RSI_MAX': 76,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 0,
    },
    {
        'label': 'kp_tight_sell',
        'KOSPI_122630_BUY_DISPARITY_LOW': 97,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 107,
        'KOSPI_122630_BUY_RSI_MAX': 80,
        'KOSPI_122630_DISPARITY_LOW': 99,
        'KOSPI_122630_DISPARITY_HIGH': 104,
        'KOSPI_MIN_HOLD_DAYS': 0,
    },
    {
        'label': 'kp_hold1',
        'KOSPI_122630_BUY_DISPARITY_LOW': 97,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 107,
        'KOSPI_122630_BUY_RSI_MAX': 80,
        'KOSPI_122630_DISPARITY_LOW': 98,
        'KOSPI_122630_DISPARITY_HIGH': 105,
        'KOSPI_MIN_HOLD_DAYS': 1,
    },
    {
        'label': 'kp_balance',
        'KOSPI_122630_BUY_DISPARITY_LOW': 98,
        'KOSPI_122630_BUY_DISPARITY_HIGH': 106,
        'KOSPI_122630_BUY_RSI_MAX': 78,
        'KOSPI_122630_DISPARITY_LOW': 99,
        'KOSPI_122630_DISPARITY_HIGH': 104,
        'KOSPI_MIN_HOLD_DAYS': 1,
    },
]

# 233740 방어 후보
KOSDAQ_233740_PROFILES = [
    {
        'label': 'kq_base',
        'KOSDAQ_233740_CUT_RATE_BULL': 0.35,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.25,
        'HARD_STOP_233740_PCT_TIGHT': 0.085,
        'HARD_STOP_233740_PCT_BASE': 0.125,
        'filter_gap': 4.5,
        'filter_rsi': 78,
        'filter_dolpa': 4.0,
    },
    {
        'label': 'kq_tight_cut',
        'KOSDAQ_233740_CUT_RATE_BULL': 0.33,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.23,
        'HARD_STOP_233740_PCT_TIGHT': 0.080,
        'HARD_STOP_233740_PCT_BASE': 0.120,
        'filter_gap': 4.5,
        'filter_rsi': 78,
        'filter_dolpa': 4.0,
    },
    {
        'label': 'kq_strict_entry',
        'KOSDAQ_233740_CUT_RATE_BULL': 0.35,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.25,
        'HARD_STOP_233740_PCT_TIGHT': 0.085,
        'HARD_STOP_233740_PCT_BASE': 0.125,
        'filter_gap': 3.5,
        'filter_rsi': 74,
        'filter_dolpa': 3.0,
    },
    {
        'label': 'kq_strict_both',
        'KOSDAQ_233740_CUT_RATE_BULL': 0.33,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.23,
        'HARD_STOP_233740_PCT_TIGHT': 0.080,
        'HARD_STOP_233740_PCT_BASE': 0.120,
        'filter_gap': 3.5,
        'filter_rsi': 74,
        'filter_dolpa': 3.0,
    },
    {
        'label': 'kq_loose_stop',
        'KOSDAQ_233740_CUT_RATE_BULL': 0.36,
        'KOSDAQ_233740_CUT_RATE_BEAR': 0.26,
        'HARD_STOP_233740_PCT_TIGHT': 0.090,
        'HARD_STOP_233740_PCT_BASE': 0.130,
        'filter_gap': 4.5,
        'filter_rsi': 78,
        'filter_dolpa': 4.0,
    },
]

RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)')
RE_RETURN_MDD = re.compile(r'수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%')
RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%')
RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%')
RE_STOCK_BLOCK = re.compile(r'^(.*?)\s+\(\s*(\d+)\s*\)\s*$')
RE_STOCK_WIN = re.compile(r'^성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)')
RE_STOCK_AVG = re.compile(r'^매매당 평균 수익률:\s*([\-\d\.]+)')


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


def patch_233740_filters(src: str, profile: dict) -> str:
    pattern = (
        r'if Gap >= 4\.5 and stock_data\[\'prevRSI\'\]\.values\[0\] >= 78 and DolPaRate >= 4\.0:\n'
        r'\s+IsBuyGo = False'
    )
    repl = (
        f'if Gap >= {profile["filter_gap"]} and stock_data[\'prevRSI\'].values[0] >= {profile["filter_rsi"]} '
        f'and DolPaRate >= {profile["filter_dolpa"]}:\n'
        f'                                    IsBuyGo = False'
    )
    return re.sub(pattern, repl, src)


def patch_script(src: str, sy: int, ey: int, kp: dict, kq: dict) -> str:
    out = patch_for_period(src, sy, ey)
    for key in ['KOSPI_122630_BUY_DISPARITY_LOW', 'KOSPI_122630_BUY_DISPARITY_HIGH', 'KOSPI_122630_BUY_RSI_MAX', 'KOSPI_122630_DISPARITY_LOW', 'KOSPI_122630_DISPARITY_HIGH', 'KOSPI_MIN_HOLD_DAYS']:
        out = patch_simple_assignment(out, key, kp[key])
    out = patch_simple_assignment(out, 'HARD_STOP_233740_PCT_TIGHT', kq['HARD_STOP_233740_PCT_TIGHT'])
    out = patch_simple_assignment(out, 'HARD_STOP_233740_PCT_BASE', kq['HARD_STOP_233740_PCT_BASE'])
    out = re.sub(
        r'if PrevClosePrice > stock_data\[\'ma60_before\'\]\.values\[0\]:\n\s+CutRate = 0\.35\n\s+else:\n\s+CutRate = 0\.25',
        (
            f'if PrevClosePrice > stock_data[\'ma60_before\'].values[0]:\n'
            f'                            CutRate = {kq["KOSDAQ_233740_CUT_RATE_BULL"]}\n'
            f'                        else:\n'
            f'                            CutRate = {kq["KOSDAQ_233740_CUT_RATE_BEAR"]}'
        ),
        out,
    )
    out = patch_233740_filters(out, kq)
    out = out.replace('plt.show()', "print('[INFO] plot skipped')")
    return out


def parse_metrics(text: str) -> dict:
    m1 = RE_FINAL.search(text)
    m2 = RE_RETURN_MDD.search(text)
    m3 = RE_WIN.search(text)
    m4 = RE_CAGR.search(text)
    if not (m1 and m2 and m3 and m4):
        return {'ok': False}
    stock_stats = {}
    current_code = None
    for line in text.splitlines():
        line = line.strip()
        sb = RE_STOCK_BLOCK.match(line)
        if sb:
            current_code = sb.group(2)
            stock_stats[current_code] = {}
            continue
        if current_code is None:
            continue
        sw = RE_STOCK_WIN.match(line)
        if sw:
            stock_stats[current_code]['win'] = float(sw.group(3))
            stock_stats[current_code]['try'] = int(sw.group(1)) + int(sw.group(2))
            continue
        sa = RE_STOCK_AVG.match(line)
        if sa:
            stock_stats[current_code]['avg'] = float(sa.group(1))
            current_code = None
    return {
        'ok': True,
        'final': int(m1.group(2).replace(',', '')),
        'ret': float(m2.group(1)),
        'mdd': float(m2.group(2)),
        'win': float(m3.group(3)),
        'cagr': float(m4.group(1)),
        'stocks': stock_stats,
    }


def run_one(py_path: Path):
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


def run_period(src: str, sy: int, ey: int, kp: dict, kq: dict):
    patched = patch_script(src, sy, ey, kp, kq)
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8', dir=str(BASE_DIR)) as tf:
        tf.write(patched)
        tmp_path = Path(tf.name)
    try:
        code, out = run_one(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    metric = parse_metrics(out)
    if code != 0 or not metric.get('ok'):
        return False, {'code': code, 'tail': '\n'.join(out.splitlines()[-20:])}
    return True, metric


def defense_score(metrics):
    march = metrics['march_2026']
    recent = metrics['recent']
    full_ = metrics['full']
    s122630 = march['stocks'].get('122630', {})
    s233740 = march['stocks'].get('233740', {})
    score = 0.0
    score += recent['cagr'] * 0.35
    score += full_['cagr'] * 0.15
    score -= abs(recent['mdd']) * 0.30
    score -= abs(march['mdd']) * 0.10
    score += s122630.get('avg', -10.0) * 1.2
    score += s233740.get('avg', -10.0) * 1.5
    score += s122630.get('win', 0.0) * 0.05
    score += s233740.get('win', 0.0) * 0.08
    return round(score, 2)


def main() -> int:
    src = BASE_FILE.read_text(encoding='utf-8')
    print('=== Recent Defense Tuning ===')
    rows = []
    for kp, kq in itertools.product(KOSPI_DEFENSE_PROFILES, KOSDAQ_233740_PROFILES):
        label = f"{kp['label']}__{kq['label']}"
        period_metrics = {}
        ok_all = True
        for period, (sy, ey) in PERIODS.items():
            print(f'[RUN] {label} | {period}')
            ok, data = run_period(src, sy, ey, kp, kq)
            if not ok:
                ok_all = False
                period_metrics[period] = data
                break
            period_metrics[period] = data
        if ok_all:
            row = {
                'label': label,
                'score': defense_score(period_metrics),
                'march_ret': period_metrics['march_2026']['ret'],
                'march_mdd': period_metrics['march_2026']['mdd'],
                'march_122630_avg': period_metrics['march_2026']['stocks'].get('122630', {}).get('avg', None),
                'march_233740_avg': period_metrics['march_2026']['stocks'].get('233740', {}).get('avg', None),
                'recent_cagr': period_metrics['recent']['cagr'],
                'recent_mdd': period_metrics['recent']['mdd'],
                'full_cagr': period_metrics['full']['cagr'],
                'full_mdd': period_metrics['full']['mdd'],
            }
            rows.append(row)
        else:
            rows.append({'label': label, 'score': None, 'error': period_metrics.get('march_2026', {}).get('tail', 'failed')})

    print('\n================ DEFENSE TABLE ================')
    print('label\tscore\tmarch_ret\tmarch_mdd\t122630_avg\t233740_avg\trecent_cagr\trecent_mdd\tfull_cagr\tfull_mdd')
    good_rows = []
    for r in rows:
        if r.get('score') is None:
            print(f"{r['label']}\tFAIL\t{r.get('error','')}")
            continue
        good_rows.append(r)
        print(
            f"{r['label']}\t{r['score']}\t{r['march_ret']}\t{r['march_mdd']}\t{r['march_122630_avg']}\t{r['march_233740_avg']}\t"
            f"{r['recent_cagr']}\t{r['recent_mdd']}\t{r['full_cagr']}\t{r['full_mdd']}"
        )

    good_rows.sort(key=lambda x: x['score'], reverse=True)
    print('\n================ TOP RANK ================')
    for i, r in enumerate(good_rows[:10], start=1):
        print(
            f"{i}. {r['label']} | score={r['score']} | march(ret={r['march_ret']}, mdd={r['march_mdd']}, 122630_avg={r['march_122630_avg']}, 233740_avg={r['march_233740_avg']}) | "
            f"recent(cagr={r['recent_cagr']}, mdd={r['recent_mdd']}) | full(cagr={r['full_cagr']}, mdd={r['full_mdd']})"
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
