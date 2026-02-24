#!/usr/bin/env python3
import itertools
import os
import random
import re
import subprocess


PYTHON_BIN = os.environ.get("PYTHON_BIN", "/Users/yonghyuk/newcodex/newcodex/bin/python")
TARGET = "/Users/yonghyuk/newcodex/Kosdaqpi_Ensemble_Test.py"
MAX_RUNS = int(os.environ.get("MAX_RUNS", "200"))
SEED = int(os.environ.get("RANDOM_SEED", "42"))
TOP_N = int(os.environ.get("TOP_N", "10"))


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


def score(x):
    return x["revenue"] + (x["cagr"] * 7.0) - (abs(x["mdd"]) * 10.0)


def main():
    grid = {
        "TARGET_VOL": [0.16, 0.18, 0.20, 0.22],
        "MAX_WEIGHT": [0.30, 0.35, 0.40],
        "MAX_LEVERAGE": [1.0, 1.1, 1.2],
        "REBALANCE_DAYS": [2, 3, 5],
        "MIN_TURNOVER": [0.04, 0.07, 0.10],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    if 0 < MAX_RUNS < len(combos):
        random.seed(SEED)
        combos = random.sample(combos, MAX_RUNS)

    print(f"[INFO] runs: {len(combos)}")
    rows = []
    for i, combo in enumerate(combos, start=1):
        params = {k: v for k, v in zip(keys, combo)}
        env = os.environ.copy()
        env["ENABLE_PLOT"] = "0"
        env["MPLBACKEND"] = "Agg"
        env["ACCOUNT_MODE"] = env.get("ACCOUNT_MODE", "REAL")
        for k, v in params.items():
            env[k] = str(v)
        p = subprocess.run([PYTHON_BIN, TARGET], capture_output=True, text=True, env=env)
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        met = parse_metrics(out)
        if met is None:
            print(f"[RUN {i}/{len(combos)}] parse failed params={params}")
            continue
        met["params"] = params
        met["score"] = score(met)
        rows.append(met)
        print(
            f"[RUN {i}/{len(combos)}] rev={met['revenue']:.2f} mdd={met['mdd']:.2f} "
            f"cagr={met['cagr']:.2f} score={met['score']:.2f}"
        )

    if not rows:
        print("[ERROR] no valid result")
        return 1

    rows.sort(key=lambda x: x["score"], reverse=True)
    print("\n=== TOP RESULTS ===")
    for i, r in enumerate(rows[:TOP_N], start=1):
        print(
            f"{i}. rev={r['revenue']:.2f}% mdd={r['mdd']:.2f}% cagr={r['cagr']:.2f}% "
            f"score={r['score']:.2f} params={r['params']}"
        )

    best = rows[0]
    print("\n=== BEST PARAMS ===")
    for k, v in best["params"].items():
        print(f"export {k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
