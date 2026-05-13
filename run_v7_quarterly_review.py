#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib.util
from pathlib import Path

MODULE_PATH = Path('/Users/yonghyuk/newcodex/run_v7_walkforward_compare.py')


def load_walkforward_module():
    spec = importlib.util.spec_from_file_location('run_v7_walkforward_compare', MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Failed to load module from {MODULE_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decide(best: dict, defense: dict) -> tuple[str, list[str]]:
    reasons = []

    score_diff = defense['score'] - best['score']
    better_gap = defense['avg_gap'] <= best['avg_gap'] - 0.5
    better_fail = defense['fail_count'] <= best['fail_count']
    better_recent_mdd = abs(defense['recent']['mdd']) <= abs(best['recent']['mdd']) - 3.0
    acceptable_recent_cagr = defense['recent']['cagr'] >= best['recent']['cagr'] - 1.0
    acceptable_full_cagr = defense['full']['cagr'] >= best['full']['cagr'] - 3.0
    acceptable_avg_test = defense['avg_test_cagr'] >= best['avg_test_cagr'] - 0.5

    if (
        score_diff >= 0.5
        and better_gap
        and better_fail
        and better_recent_mdd
        and acceptable_recent_cagr
        and acceptable_full_cagr
        and acceptable_avg_test
    ):
        reasons.append('defense가 walk-forward 강건성, recent MDD, 최근/전체 수익률 조건을 모두 통과했습니다.')
        return 'SWITCH_TO_DEFENSE', reasons

    if better_recent_mdd and acceptable_recent_cagr and acceptable_full_cagr:
        reasons.append('defense가 최근장 방어에는 의미가 있지만, 강건성 점수나 gap 개선이 교체 기준까지는 아닙니다.')
        return 'KEEP_BEST_REVIEW_DEFENSE', reasons

    reasons.append('기준 전략 best를 유지하는 편이 더 안전합니다.')
    return 'KEEP_BEST', reasons


def print_variant(result: dict) -> None:
    print(
        f"{result['label']}: score={result['score']:.2f}, "
        f"avg_test_cagr={result['avg_test_cagr']:.2f}, avg_test_mdd=-{result['avg_test_mdd_abs']:.2f}, "
        f"avg_gap={result['avg_gap']:.2f}, fail_windows={result['fail_count']}, "
        f"recent(cagr={result['recent']['cagr']:.2f}, mdd={result['recent']['mdd']:.2f}), "
        f"full(cagr={result['full']['cagr']:.2f}, mdd={result['full']['mdd']:.2f})"
    )


def main() -> int:
    wf = load_walkforward_module()
    best = wf.evaluate_variant('best', wf.BEST_FILE)
    defense = wf.evaluate_variant('defense', wf.DEFENSE_FILE)

    for result in (best, defense):
        if not result['ok']:
            print(f"[ERROR] {result['label']} failed")
            print(result['error'])
            return 1

    action, reasons = decide(best, defense)

    print('================ QUARTERLY REVIEW ================')
    print_variant(best)
    print_variant(defense)

    print('\nRecommended action:')
    print(action)
    print('\nWhy:')
    for reason in reasons:
        print(f'- {reason}')

    print('\nRule summary:')
    print('- SWITCH_TO_DEFENSE: defense가 score/gap/recent MDD 조건을 모두 개선하면서 recent/full CAGR 훼손이 제한적일 때만')
    print('- KEEP_BEST_REVIEW_DEFENSE: defense가 방어력은 좋아졌지만 교체 기준까지는 아니어서 보조 후보로 유지')
    print('- KEEP_BEST: best 유지')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
