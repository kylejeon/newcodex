#!/usr/bin/env python3
import itertools
import os
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


TARGET_SCRIPT = Path("/Users/yonghyuk/newcodex/Kosdaqpi_Test_new.py")
PYTHON_BIN = os.environ.get("PYTHON_BIN", "/Users/yonghyuk/newcodex/newcodex/bin/python")

# 원본 기준치(사용자가 공유한 값)
BASE_REVENUE = float(os.environ.get("BASE_REVENUE", "3078.99"))
BASE_MDD = float(os.environ.get("BASE_MDD", "-19.74"))
BASE_CAGR = float(os.environ.get("BASE_CAGR", "50.28"))

TOP_N = int(os.environ.get("TOP_N", "10"))
MAX_RUNS = int(os.environ.get("MAX_RUNS", "300"))
RANDOM_SEED = int(os.environ.get("RANDOM_SEED", "42"))
TUNE_WORKERS = int(os.environ.get("TUNE_WORKERS", "1"))
RETRY_COUNT = int(os.environ.get("RETRY_COUNT", "2"))


def parse_result(text):
    m = re.search(r"수익률:\s*([-\d.,]+)\s*% MDD:\s*([-\d.,]+)\s*%", text)
    c = re.search(r"연복리수익률\(CAGR\):\s*([-\d.,]+)", text)
    if not m or not c:
        return None
    return {
        "revenue": float(m.group(1).replace(",", "")),
        "mdd": float(m.group(2).replace(",", "")),
        "cagr": float(c.group(1).replace(",", "")),
    }


def score(r):
    # 높은 수익률/CAGR, 낮은 MDD 절대값 선호
    return (r["revenue"] * 1.0) + (r["cagr"] * 8.0) - (abs(r["mdd"]) * 12.0)


def run_one(idx, total, params):
    env = os.environ.copy()
    for k, v in params.items():
        env[k] = str(v)
    env["ENABLE_PLOT"] = "0"
    env["MPLBACKEND"] = "Agg"

    out = ""
    proc = None
    parsed = None
    for _ in range(RETRY_COUNT + 1):
        proc = subprocess.run(
            [PYTHON_BIN, str(TARGET_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        parsed = parse_result(out)
        if parsed is not None:
            break

    if parsed is None:
        reason = "unknown"
        if "유효한 OHLCV 데이터를 가져오지 못했습니다" in out:
            reason = "ohlcv_load_failed"
        elif "Get Authentification token fail" in out:
            reason = "auth_failed"
        elif "NameResolutionError" in out:
            reason = "dns_failed"
        tail = "\n".join(out.strip().splitlines()[-4:])
        return {
            "idx": idx,
            "total": total,
            "params": params,
            "ok": False,
            "reason": reason,
            "returncode": proc.returncode if proc else -1,
            "tail": tail,
        }

    parsed["params"] = params
    parsed["score"] = score(parsed)
    parsed["beats_base"] = (
        parsed["revenue"] >= BASE_REVENUE
        and parsed["cagr"] >= BASE_CAGR
        and parsed["mdd"] >= BASE_MDD
    )
    parsed["idx"] = idx
    parsed["total"] = total
    parsed["ok"] = True
    return parsed


def main():
    if not TARGET_SCRIPT.exists():
        print(f"[ERROR] target script not found: {TARGET_SCRIPT}")
        sys.exit(1)

    grid = {
        "RISK_OFF_DD_ON": [-0.11, -0.13, -0.15],
        "RISK_OFF_DD_OFF": [-0.04, -0.06, -0.08],
        "STOP_ARM_PROFIT_PCT": [8.0, 10.0, 12.0],
        "STOP_MIN_HOLD_DAYS": [5, 7, 9],
        "TRAIL_ATR_MULTIPLIER": [3.2, 3.6, 4.0],
        "HARD_STOP_ATR_MULTIPLIER": [4.0, 4.6, 5.2],
        "MIN_POSITION_FLOOR_RATE": [0.85, 0.95, 1.0],
        "RISK_PER_TRADE": [0.02, 0.03],
        "ENABLE_REGIME_OVERLAY": [1],
        "ENABLE_RISK_PARITY": [0, 1],
        "EXPOSURE_NEUTRAL": [0.80, 0.90],
        "EXPOSURE_RISK_OFF": [0.55, 0.70],
    }

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"[INFO] total combos: {len(combos)}")
    if MAX_RUNS > 0 and MAX_RUNS < len(combos):
        random.seed(RANDOM_SEED)
        combos = random.sample(combos, MAX_RUNS)
        print(f"[INFO] sampled combos: {len(combos)} (seed={RANDOM_SEED})")

    results = []
    fail_reasons = {}
    with ThreadPoolExecutor(max_workers=max(1, TUNE_WORKERS)) as ex:
        future_map = {}
        for i, combo in enumerate(combos, start=1):
            params = {k: v for k, v in zip(keys, combo)}
            fut = ex.submit(run_one, i, len(combos), params)
            future_map[fut] = params

        for fut in as_completed(future_map):
            res = fut.result()
            if not res["ok"]:
                reason = res.get("reason", "unknown")
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
                print(
                    f"[RUN {res['idx']}/{res['total']}] failed reason={reason} rc={res.get('returncode')} "
                    f"params={res['params']}"
                )
                continue
            results.append(res)
            print(
                f"[RUN {res['idx']}/{res['total']}] rev={res['revenue']:.2f} mdd={res['mdd']:.2f} "
                f"cagr={res['cagr']:.2f} score={res['score']:.2f} beats_base={res['beats_base']}"
            )

    if not results:
        if fail_reasons:
            print(f"[ERROR] fail summary: {fail_reasons}")
        print("[ERROR] no valid result parsed")
        sys.exit(2)

    results.sort(key=lambda x: x["score"], reverse=True)
    print("\n=== TOP RESULTS ===")
    for idx, r in enumerate(results[:TOP_N], start=1):
        print(
            f"{idx}. rev={r['revenue']:.2f}% mdd={r['mdd']:.2f}% cagr={r['cagr']:.2f}% "
            f"score={r['score']:.2f} beats_base={r['beats_base']} params={r['params']}"
        )

    best = results[0]
    print("\n=== BEST PARAMS (apply as env vars) ===")
    for k, v in best["params"].items():
        print(f"export {k}={v}")


if __name__ == "__main__":
    main()
