#!/usr/bin/env python3
import itertools
import os
import re
import subprocess
import sys
from datetime import datetime


PYTHON_BIN = os.environ.get("PYTHON_BIN", "/Users/yonghyuk/newcodex/newcodex/bin/python")
TARGET_SCRIPT = "/Users/yonghyuk/newcodex/Kosdaqpi_Test_v3.py"

START = int(os.environ.get("WFO_START_YEAR", "2017"))
END = int(os.environ.get("WFO_END_YEAR", "2026"))
TRAIN_YEARS = int(os.environ.get("WFO_TRAIN_YEARS", "4"))
TEST_YEARS = int(os.environ.get("WFO_TEST_YEARS", "1"))
TOP_N = int(os.environ.get("TOP_N", "5"))


def parse_metrics(text):
    m = re.search(r"수익률:\s*([-\d.,]+)\s*% MDD:\s*([-\d.,]+)\s*%", text)
    c = re.search(r"연복리수익률\(CAGR\):\s*([-\d.,]+)", text)
    if not m or not c:
        return None
    return {
        "revenue": float(m.group(1).replace(",", "")),
        "mdd": float(m.group(2).replace(",", "")),
        "cagr": float(c.group(1).replace(",", "")),
    }


def score(m):
    return m["revenue"] + (m["cagr"] * 6.0) - (abs(m["mdd"]) * 10.0)


def run_once(params, start_date, end_date):
    env = os.environ.copy()
    env["ENABLE_PLOT"] = "0"
    env["MPLBACKEND"] = "Agg"
    env["BACKTEST_START"] = start_date
    env["BACKTEST_END"] = end_date
    for k, v in params.items():
        env[k] = str(v)

    p = subprocess.run([PYTHON_BIN, TARGET_SCRIPT], capture_output=True, text=True, env=env)
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    return parse_metrics(out)


def main():
    grid = {
        "MAX_WEIGHT": [0.30, 0.35],
        "MAX_LEVERAGE": [1.0, 1.15, 1.25],
        "RISK_OFF_DD_ON": [-0.10, -0.12, -0.14],
        "RISK_OFF_DD_OFF": [-0.04, -0.06],
        "RISK_ON_TARGET_VOL": [0.22, 0.26],
        "NEUTRAL_TARGET_VOL": [0.14, 0.18],
        "RISK_OFF_TARGET_VOL": [0.08, 0.11],
        "RISK_ON_POS": [3, 4],
        "NEUTRAL_POS": [2, 3],
        "RISK_OFF_POS": [1, 2],
    }

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"[INFO] param combos: {len(combos)}")

    folds = []
    y = START
    while y + TRAIN_YEARS + TEST_YEARS - 1 <= END:
        train_s = f"{y}-01-01"
        train_e = f"{y + TRAIN_YEARS - 1}-12-31"
        test_s = f"{y + TRAIN_YEARS}-01-01"
        test_e = f"{y + TRAIN_YEARS + TEST_YEARS - 1}-12-31"
        folds.append((train_s, train_e, test_s, test_e))
        y += TEST_YEARS

    if not folds:
        print("[ERROR] 워크포워드 폴드 생성 실패")
        return 1

    fold_results = []
    for fi, (train_s, train_e, test_s, test_e) in enumerate(folds, start=1):
        print(f"\n[FOLD {fi}] train={train_s}~{train_e} test={test_s}~{test_e}")
        ranked = []
        for i, combo in enumerate(combos, start=1):
            params = {k: v for k, v in zip(keys, combo)}
            m = run_once(params, train_s, train_e)
            if m is None:
                continue
            ranked.append((score(m), params, m))
            if i % 100 == 0:
                print(f"  train progress: {i}/{len(combos)}")

        if not ranked:
            print("  [WARN] train valid result 없음")
            continue

        ranked.sort(key=lambda x: x[0], reverse=True)
        best_score, best_params, best_train = ranked[0]
        test_m = run_once(best_params, test_s, test_e)
        if test_m is None:
            print("  [WARN] test parse 실패")
            continue

        fold_results.append(
            {
                "fold": fi,
                "best_params": best_params,
                "train": best_train,
                "test": test_m,
                "train_score": best_score,
            }
        )
        print(f"  best train score={round(best_score,2)} params={best_params}")
        print(
            f"  test => revenue={round(test_m['revenue'],2)} mdd={round(test_m['mdd'],2)} "
            f"cagr={round(test_m['cagr'],2)}"
        )

    if not fold_results:
        print("[ERROR] 유효한 워크포워드 결과 없음")
        return 2

    # Aggregate test performance (simple average)
    avg_rev = sum(x["test"]["revenue"] for x in fold_results) / len(fold_results)
    avg_mdd = sum(x["test"]["mdd"] for x in fold_results) / len(fold_results)
    avg_cagr = sum(x["test"]["cagr"] for x in fold_results) / len(fold_results)

    print("\n=== WFO SUMMARY ===")
    print(f"folds: {len(fold_results)}")
    print(f"avg test revenue: {round(avg_rev,2)}%")
    print(f"avg test mdd: {round(avg_mdd,2)}%")
    print(f"avg test cagr: {round(avg_cagr,2)}%")

    # show top folds by test score
    scored = sorted(
        fold_results,
        key=lambda x: score(x["test"]),
        reverse=True,
    )
    print("\n=== TOP FOLDS ===")
    for row in scored[:TOP_N]:
        t = row["test"]
        print(
            f"fold={row['fold']} revenue={round(t['revenue'],2)} mdd={round(t['mdd'],2)} "
            f"cagr={round(t['cagr'],2)} params={row['best_params']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
