#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7_best BE_STOP Phase B — cascading 효과 반영한 정식 백테 + walk-forward 검증.

Phase A (사후 시뮬) 의 한계 (cascading 무시) 를 보완:
  - v7_best_BESTOP_run.py: BE_STOP 코드가 통합된 v7_best 백테 사본
  - 본 스크립트: BE_STOP_PCT 환경변수로 0 (baseline) / 5 / 7 / 10 호출
  - cascading 자연 발생: BE_STOP 일찍 매도 → 다음 BUY 신호 자연 처리

각 실행 결과 파싱 후 종합 비교 + Walk-forward fold (출생 buy_date 기준) 분할.
실행 시간: 1 threshold 당 ~10분 → 4 threshold = ~40분 (background 권장).

사용:
    python v7_best_BESTOP_phaseB.py
"""
from __future__ import annotations
import os
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_FILE = ROOT / 'v7_best_BESTOP_run.py'
OUTPUT_DIR = ROOT / 'mnq_backtest_output'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_FILE = OUTPUT_DIR / 'v7_best_BESTOP_phaseB_result.txt'

# 테스트 모드: (label, env_dict)
#   baseline / simple 5/7/10 / stepped (5/10/15 단계별)
MODES = [
    ('baseline',  {'BE_STOP_PCT': '0',  'BE_STOP_STEPPED': '0'}),
    ('simple_5',  {'BE_STOP_PCT': '5',  'BE_STOP_STEPPED': '0'}),
    ('simple_7',  {'BE_STOP_PCT': '7',  'BE_STOP_STEPPED': '0'}),
    ('simple_10', {'BE_STOP_PCT': '10', 'BE_STOP_STEPPED': '0'}),
    ('stepped',   {'BE_STOP_PCT': '0',  'BE_STOP_STEPPED': '1'}),
]

# 결과 파싱용 정규식
_RE_REVENUE = re.compile(r'수익률:\s*([-+]?\d+\.?\d*)\s*%')
_RE_MDD = re.compile(r'MDD:\s*([-+]?\d+\.?\d*)\s*%')
_RE_CAGR = re.compile(r'연복리수익률\(CAGR\):\s*([-+]?[\d,]+\.?\d*)\s*%')
_RE_WIN = re.compile(r'성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([-+]?\d+\.?\d*)\s*%')
_RE_FINAL = re.compile(r'최초 금액:\s*([\d,]+).*?최종 금액:\s*([\d,]+)')
_RE_BE_TRIG = re.compile(r'BE_STOP 트리거\s+\((\d+)\)\s+(\d{4}-\d{2}-\d{2})\s+max_gain=([-+]?\d+\.?\d*)%')


def run_v7best(mode_label: str, env_dict: dict) -> tuple[str, dict]:
    """v7_best_BESTOP_run.py 를 환경변수로 실행. 결과 stdout 과 파싱 dict 반환."""
    env = os.environ.copy()
    env.update(env_dict)
    env['PHASE_B_QUIET'] = '1'
    print(f"\n{'='*70}")
    print(f"[Phase B] mode={mode_label} env={env_dict} 실행 — {datetime.now().isoformat(timespec='seconds')}")
    print(f"{'='*70}")
    result = subprocess.run(
        [sys.executable, str(RUN_FILE)],
        env=env, capture_output=True, text=True, cwd=str(ROOT),
    )
    output = result.stdout + "\n" + result.stderr
    print(f"  종료 코드: {result.returncode}, 길이: {len(output)} chars")

    # 파싱
    parsed = parse_output(output)
    parsed['mode_label'] = mode_label
    parsed['env'] = env_dict
    parsed['returncode'] = result.returncode

    # BE_STOP 트리거 목록 수집
    triggers = []
    for m in _RE_BE_TRIG.finditer(output):
        triggers.append({'code': m.group(1), 'date': m.group(2), 'max_gain': float(m.group(3))})
    parsed['be_triggers'] = triggers

    return output, parsed


def parse_output(text: str) -> dict:
    """v7_best 표준 출력에서 핵심 결과 추출."""
    out = {}
    # 마지막 결과만 (ResultList 가 1개라 가정)
    rev_match = _RE_REVENUE.findall(text)
    mdd_match = _RE_MDD.findall(text)
    cagr_match = _RE_CAGR.findall(text)
    win_match = _RE_WIN.findall(text)
    fin_match = _RE_FINAL.findall(text)

    if rev_match:
        out['revenue_pct'] = float(rev_match[-1])
    if mdd_match:
        out['mdd_pct'] = float(mdd_match[-1])
    if cagr_match:
        out['cagr_pct'] = float(cagr_match[-1].replace(',', ''))
    if win_match:
        s, f, w = win_match[-1]
        out['success'] = int(s)
        out['fail'] = int(f)
        out['win_pct'] = float(w)
        out['total_trades'] = int(s) + int(f)
    if fin_match:
        ori, fin = fin_match[-1]
        out['initial_money'] = int(ori.replace(',', ''))
        out['final_money'] = int(fin.replace(',', ''))
    return out


def write_summary(results: list[dict], logs: dict[str, str]):
    """결과 종합 요약 + 비교 표 텍스트 파일 저장."""
    with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# v7_best BE_STOP Phase B 결과 ({datetime.now().isoformat(timespec='seconds')})\n")
        f.write(f"# 검증 방식: cascading 효과 자연 발생 (정식 v7_best 백테 fork)\n")
        f.write(f"# 사용 파일: v7_best_BESTOP_run.py (BE_STOP_PCT, BE_STOP_STEPPED 환경변수)\n")
        f.write(f"# 모드 설명:\n")
        f.write(f"#   baseline  — BE_STOP 비활성\n")
        f.write(f"#   simple_N  — max_gain >= N% 도달 + today low <= entry → entry 청산 (ROI 0)\n")
        f.write(f"#   stepped   — max_gain 단계별 stop_price 가변:\n")
        f.write(f"#       max_gain >= 15% → stop @ entry × 1.10 (10% 수익 lock)\n")
        f.write(f"#       max_gain >= 10% → stop @ entry × 1.05 (5% 수익 lock)\n")
        f.write(f"#       max_gain >=  5% → stop @ entry × 1.00 (entry break)\n\n")

        # 비교 표
        f.write("="*78 + "\n")
        f.write("[종합 결과 — 전체 기간]\n")
        f.write("="*78 + "\n")
        f.write(f"{'Mode':>10s} {'Revenue%':>11s} {'CAGR%':>8s} {'MDD%':>8s} {'Win%':>6s} "
                f"{'Trades':>7s} {'BE_trig':>8s} {'vs base':>10s}\n")

        baseline = next((r for r in results if r['mode_label'] == 'baseline'), None)
        base_rev = baseline.get('revenue_pct') if baseline else None

        for r in results:
            mode = r['mode_label']
            rev = r.get('revenue_pct') or 0
            cagr = r.get('cagr_pct') or 0
            mdd = r.get('mdd_pct') or 0
            win = r.get('win_pct') or 0
            trades = r.get('total_trades') or 0
            be_trig = len(r.get('be_triggers', []))
            delta = (rev - base_rev) if base_rev is not None else 0
            f.write(f"{mode:>10s} {rev:>+10.2f} {cagr:>+7.2f} {mdd:>+7.2f} {win:>5.1f} "
                    f"{trades:>7d} {be_trig:>8d} {delta:>+8.2f}pp\n")

        f.write("\n")

        # BE_STOP 트리거 상세
        f.write("="*78 + "\n")
        f.write("[BE_STOP 트리거 상세 (모드별)]\n")
        f.write("="*78 + "\n")
        for r in results:
            if r['mode_label'] == 'baseline':
                continue
            f.write(f"\n--- {r['mode_label']} 트리거 목록 ({len(r['be_triggers'])} 건) ---\n")
            for t in r['be_triggers']:
                f.write(f"  {t['date']}  {t['code']}  max_gain={t['max_gain']:+.2f}%\n")

        # Walk-forward fold 분할
        f.write("\n" + "="*78 + "\n")
        f.write("[Walk-forward Fold 분할 — BE_STOP trigger 시기 분포]\n")
        f.write("="*78 + "\n")
        fold_boundaries = [
            ('Fold1 (2018~2022)',     '2018-01-01', '2022-12-31'),
            ('Fold2 (2023~2024/6)',   '2023-01-01', '2024-06-30'),
            ('Fold3 (2024/7~2025/6)', '2024-07-01', '2025-06-30'),
            ('Fold4 (2025/7~ )',      '2025-07-01', '2030-12-31'),
        ]
        for r in results:
            if r['mode_label'] == 'baseline':
                continue
            f.write(f"\n--- {r['mode_label']} ---\n")
            for label, start, end in fold_boundaries:
                count = sum(1 for t in r['be_triggers'] if start <= t['date'] <= end)
                f.write(f"  {label}: {count} trigger\n")

        # 결론 / 권장
        f.write("\n" + "="*78 + "\n")
        f.write("[결론 권장]\n")
        f.write("="*78 + "\n")
        if baseline:
            candidates = [r for r in results if r['mode_label'] != 'baseline']
            best = max(candidates, key=lambda r: (r.get('revenue_pct') or -1e9), default=None)
            if best:
                delta = (best.get('revenue_pct') or 0) - (base_rev or 0)
                win_str = f"{best.get('win_pct'):.1f}%" if best.get('win_pct') is not None else "N/A"
                mdd_str = f"{best.get('mdd_pct'):.2f}%" if best.get('mdd_pct') is not None else "N/A"
                rev_str = f"{best.get('revenue_pct'):.2f}%" if best.get('revenue_pct') is not None else "N/A"
                f.write(f"가장 우위: {best['mode_label']} — Revenue {rev_str}"
                        f" (baseline 대비 {delta:+.2f}pp), Win {win_str}, MDD {mdd_str}\n")
                f.write(f"  BE_STOP 트리거: {len(best['be_triggers'])} 건\n")
                base_mdd = baseline.get('mdd_pct') or 0
                best_mdd = best.get('mdd_pct') or 0
                base_win = baseline.get('win_pct') or 0
                best_win = best.get('win_pct') or 0
                if delta > 0 and best_mdd >= base_mdd and best_win >= base_win - 0.5:
                    f.write(f"  → 적용 권장 (Win 유지 + Revenue 개선 + MDD 악화 없음)\n")
                elif delta > 0:
                    f.write(f"  → 신중 검토 (Revenue 개선됐으나 Win 또는 MDD 검토 필요)\n")
                else:
                    f.write(f"  → 권장 안 함\n")

        # 각 실행 로그 location
        f.write("\n" + "="*78 + "\n")
        f.write("[상세 로그 파일]\n")
        f.write("="*78 + "\n")
        for label, path in logs.items():
            f.write(f"  {label}: {path}\n")


def main():
    results = []
    logs = {}
    for label, env_dict in MODES:
        output, parsed = run_v7best(label, env_dict)
        log_path = OUTPUT_DIR / f"v7_best_BESTOP_run_{label}.log"
        log_path.write_text(output, encoding='utf-8')
        logs[label] = str(log_path.relative_to(ROOT))
        results.append(parsed)
        print(f"  parsed: revenue={parsed.get('revenue_pct')}% MDD={parsed.get('mdd_pct')}% "
              f"trades={parsed.get('total_trades')} BE_trig={len(parsed.get('be_triggers', []))}")

    write_summary(results, logs)
    print(f"\n{'='*70}")
    print(f"=== Phase B 결과 파일: {SUMMARY_FILE}")
    print(f"=== 상세 로그: {OUTPUT_DIR}/v7_best_BESTOP_run_*.log")


if __name__ == '__main__':
    main()
