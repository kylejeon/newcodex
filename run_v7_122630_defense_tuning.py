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

PERIODS = {
    'march_2026': (2026, 2026),
    'recent': (2022, 2026),
    'full': (2017, 2099),
}

PROFILES = [
    {
        'label': 'base',
        'buy_low': 97,
        'buy_high': 107,
        'buy_rsi': 80,
        'sell_low': 98,
        'sell_high': 105,
        'hold_days': 0,
        'extra_drop_filter': False,
        'extra_ma_filter': False,
    },
    {
        'label': 'tight_buy_rsi',
        'buy_low': 97,
        'buy_high': 107,
        'buy_rsi': 74,
        'sell_low': 98,
        'sell_high': 105,
        'hold_days': 0,
        'extra_drop_filter': False,
        'extra_ma_filter': False,
    },
    {
        'label': 'tight_buy_disp',
        'buy_low': 98,
        'buy_high': 106,
        'buy_rsi': 78,
        'sell_low': 98,
        'sell_high': 105,
        'hold_days': 0,
        'extra_drop_filter': False,
        'extra_ma_filter': False,
    },
    {
        'label': 'tight_sell_disp',
        'buy_low': 97,
        'buy_high': 107,
        'buy_rsi': 80,
        'sell_low': 99,
        'sell_high': 104,
        'hold_days': 0,
        'extra_drop_filter': False,
        'extra_ma_filter': False,
    },
    {
        'label': 'hold1',
        'buy_low': 97,
        'buy_high': 107,
        'buy_rsi': 80,
        'sell_low': 98,
        'sell_high': 105,
        'hold_days': 1,
        'extra_drop_filter': False,
        'extra_ma_filter': False,
    },
    {
        'label': 'drop_filter',
        'buy_low': 97,
        'buy_high': 107,
        'buy_rsi': 80,
        'sell_low': 98,
        'sell_high': 105,
        'hold_days': 0,
        'extra_drop_filter': True,
        'extra_ma_filter': False,
    },
    {
        'label': 'ma_filter',
        'buy_low': 97,
        'buy_high': 107,
        'buy_rsi': 80,
        'sell_low': 98,
        'sell_high': 105,
        'hold_days': 0,
        'extra_drop_filter': False,
        'extra_ma_filter': True,
    },
    {
        'label': 'combo_defense',
        'buy_low': 98,
        'buy_high': 106,
        'buy_rsi': 76,
        'sell_low': 99,
        'sell_high': 104,
        'hold_days': 1,
        'extra_drop_filter': True,
        'extra_ma_filter': True,
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


def patch_122630_buy_logic(src: str, profile: dict) -> str:
    base = (
        "if (stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
        "(Disparity < KOSPI_122630_BUY_DISPARITY_LOW or Disparity > KOSPI_122630_BUY_DISPARITY_HIGH) and "
        "stock_data['prevRSI'].values[0] < KOSPI_122630_BUY_RSI_MAX :\n"
        "                            IsBuyGo = True"
    )
    extra = []
    if profile['extra_drop_filter']:
        extra.append("stock_data['prevOpen'].values[0] <= stock_data['prevClose'].values[0]")
    if profile['extra_ma_filter']:
        extra.append("stock_data['prevClose'].values[0] > stock_data['ma20_before'].values[0]")
    if extra:
        cond = (
            "if (stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and "
            "(Disparity < KOSPI_122630_BUY_DISPARITY_LOW or Disparity > KOSPI_122630_BUY_DISPARITY_HIGH) and "
            "stock_data['prevRSI'].values[0] < KOSPI_122630_BUY_RSI_MAX and " + " and ".join(extra) + " :\n"
            "                            IsBuyGo = True"
        )
        return src.replace(base, cond)
    return src


def patch_script(src: str, sy: int, ey: int, profile: dict) -> str:
    out = patch_for_period(src, sy, ey)
    out = patch_simple_assignment(out, 'KOSPI_122630_BUY_DISPARITY_LOW', profile['buy_low'])
    out = patch_simple_assignment(out, 'KOSPI_122630_BUY_DISPARITY_HIGH', profile['buy_high'])
    out = patch_simple_assignment(out, 'KOSPI_122630_BUY_RSI_MAX', profile['buy_rsi'])
    out = patch_simple_assignment(out, 'KOSPI_122630_DISPARITY_LOW', profile['sell_low'])
    out = patch_simple_assignment(out, 'KOSPI_122630_DISPARITY_HIGH', profile['sell_high'])
    out = patch_simple_assignment(out, 'KOSPI_MIN_HOLD_DAYS', profile['hold_days'])
    out = patch_122630_buy_logic(out, profile)
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


def run_period(src: str, sy: int, ey: int, profile: dict):
    patched = patch_script(src, sy, ey, profile)
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


def score(metrics):
    march = metrics['march_2026']
    recent = metrics['recent']
    full_ = metrics['full']
    s122630 = march['stocks'].get('122630', {})
    value = 0.0
    value += s122630.get('avg', -20.0) * 3.0
    value += s122630.get('win', 0.0) * 0.15
    value += recent['cagr'] * 0.35
    value += full_['cagr'] * 0.10
    value -= abs(march['mdd']) * 0.25
    value -= abs(recent['mdd']) * 0.20
    return round(value, 2)


def main() -> int:
    src = BASE_FILE.read_text(encoding='utf-8')
    print('=== 122630 Defense Tuning ===')
    rows = []
    for profile in PROFILES:
        label = profile['label']
        period_metrics = {}
        ok_all = True
        for period, (sy, ey) in PERIODS.items():
            print(f'[RUN] {label} | {period}')
            ok, data = run_period(src, sy, ey, profile)
            if not ok:
                ok_all = False
                period_metrics[period] = data
                break
            period_metrics[period] = data
        if ok_all:
            rows.append({
                'label': label,
                'score': score(period_metrics),
                'march_ret': period_metrics['march_2026']['ret'],
                'march_mdd': period_metrics['march_2026']['mdd'],
                'march_122630_avg': period_metrics['march_2026']['stocks'].get('122630', {}).get('avg', None),
                'march_122630_win': period_metrics['march_2026']['stocks'].get('122630', {}).get('win', None),
                'recent_cagr': period_metrics['recent']['cagr'],
                'recent_mdd': period_metrics['recent']['mdd'],
                'full_cagr': period_metrics['full']['cagr'],
                'full_mdd': period_metrics['full']['mdd'],
            })
        else:
            rows.append({'label': label, 'score': None, 'error': period_metrics.get('march_2026', {}).get('tail', 'failed')})

    print('\n================ 122630 DEFENSE TABLE ================')
    print('label\tscore\tmarch_ret\tmarch_mdd\t122630_avg\t122630_win\trecent_cagr\trecent_mdd\tfull_cagr\tfull_mdd')
    good = []
    for r in rows:
        if r.get('score') is None:
            print(f"{r['label']}\tFAIL\t{r.get('error','')}")
            continue
        good.append(r)
        print(f"{r['label']}\t{r['score']}\t{r['march_ret']}\t{r['march_mdd']}\t{r['march_122630_avg']}\t{r['march_122630_win']}\t{r['recent_cagr']}\t{r['recent_mdd']}\t{r['full_cagr']}\t{r['full_mdd']}")

    good.sort(key=lambda x: x['score'], reverse=True)
    print('\n================ TOP RANK ================')
    for i, r in enumerate(good, start=1):
        print(f"{i}. {r['label']} | score={r['score']} | march(ret={r['march_ret']}, mdd={r['march_mdd']}, 122630_avg={r['march_122630_avg']}, 122630_win={r['march_122630_win']}) | recent(cagr={r['recent_cagr']}, mdd={r['recent_mdd']}) | full(cagr={r['full_cagr']}, mdd={r['full_mdd']})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
