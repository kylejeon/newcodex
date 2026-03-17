#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_FILE = Path("/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v6b_233740_adaptive_stop.py")
BASE_DIR = BASE_FILE.parent

# (라벨, CLOSE_BASED_CUT_CODES)
VARIANTS = [
    ("v6b_base_233740_only", {"233740"}),
    ("v6b_add_251340", {"233740", "251340"}),
    ("v6b_add_122630", {"122630", "233740", "251340"}),
    ("v6b_all4", {"122630", "252670", "233740", "251340"}),
]

# (라벨, StartYear, EndYear)
PERIODS = [
    ("full", 2017, 2099),
    ("train_2017_2021", 2017, 2021),
    ("test_2022_2026", 2022, 2026),
]

RE_FINAL = re.compile(r"최초 금액:\s*([\d,]+)\s*최종 금액:\s*([\d,]+)")
RE_RETURN_MDD = re.compile(r"수익률:\s*([\-\d\.]+)\s*%\s*MDD:\s*([\-\d\.]+)\s*%")
RE_WIN = re.compile(r"성공:\s*(\d+)\s*실패:\s*(\d+)\s*->\s*승률:\s*([\d\.]+)\s*%")
RE_CAGR = re.compile(r"연복리수익률\(CAGR\):\s*([\-\d\.]+)\s*%")


def patch_script(src: str, close_codes: set[str], start_year: int, end_year: int) -> str:
    out = src

    # Close-based set
    out = re.sub(
        r"CLOSE_BASED_CUT_CODES\s*=\s*\{[^\n]*\}",
        f"CLOSE_BASED_CUT_CODES = {repr(set(sorted(close_codes)))}",
        out,
    )

    # StartYear
    out = re.sub(r"StartYear\s*=\s*\d+", f"StartYear = {start_year}", out)

    # EndYear 삽입(없으면 StartYear 아래 추가)
    if "EndYear =" in out:
        out = re.sub(r"EndYear\s*=\s*\d+", f"EndYear = {end_year}", out)
    else:
        out = out.replace(f"StartYear = {start_year}", f"StartYear = {start_year}\nEndYear = {end_year}")

    # 진입 조건의 연도 필터에 EndYear 추가
    out = out.replace(
        'int(date_object.strftime("%Y")) >= StartYear',
        'int(date_object.strftime("%Y")) >= StartYear and int(date_object.strftime("%Y")) <= EndYear',
    )

    # plt.show() 무력화(헤드리스)
    out = out.replace("plt.show()", "print('[INFO] plot skipped')")

    return out


def parse_metrics(text: str) -> dict:
    m1 = RE_FINAL.search(text)
    m2 = RE_RETURN_MDD.search(text)
    m3 = RE_WIN.search(text)
    m4 = RE_CAGR.search(text)

    if not (m1 and m2 and m3 and m4):
        return {"ok": False, "error": "parse_failed"}

    return {
        "ok": True,
        "ori": int(m1.group(1).replace(",", "")),
        "final": int(m1.group(2).replace(",", "")),
        "ret": float(m2.group(1)),
        "mdd": float(m2.group(2)),
        "success": int(m3.group(1)),
        "fail": int(m3.group(2)),
        "win": float(m3.group(3)),
        "cagr": float(m4.group(1)),
    }


def run_one(py_path: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    # 로컬 모듈(KIS_Common 등) import 보장
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{BASE_DIR}:{old_pp}" if old_pp else str(BASE_DIR)
    p = subprocess.run(
        [sys.executable, str(py_path)],
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
        print(f"[ERROR] base file not found: {BASE_FILE}")
        return 1

    src = BASE_FILE.read_text(encoding="utf-8")
    results = []

    for vlabel, close_codes in VARIANTS:
        for plabel, start_year, end_year in PERIODS:
            patched = patch_script(src, close_codes, start_year, end_year)
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8", dir=str(BASE_DIR)) as tf:
                tf.write(patched)
                tmp_path = Path(tf.name)

            print(f"[RUN] variant={vlabel} period={plabel} close_codes={sorted(close_codes)} start={start_year} end={end_year}")
            try:
                code, out = run_one(tmp_path)
            except subprocess.TimeoutExpired:
                results.append((vlabel, plabel, False, "timeout", None))
                tmp_path.unlink(missing_ok=True)
                continue

            metric = parse_metrics(out)
            if code != 0 or not metric.get("ok"):
                # 마지막 일부 로그만 출력
                tail = "\n".join(out.splitlines()[-20:])
                results.append((vlabel, plabel, False, f"code={code}", tail))
            else:
                results.append((vlabel, plabel, True, metric, None))

            tmp_path.unlink(missing_ok=True)

    print("\n================ SUMMARY ================")
    print("variant\tperiod\tok\tret%\tmdd%\tcagr%\twin%\tfinal")
    for vlabel, plabel, ok, info, extra in results:
        if ok:
            m = info
            print(f"{vlabel}\t{plabel}\tY\t{m['ret']:.2f}\t{m['mdd']:.2f}\t{m['cagr']:.2f}\t{m['win']:.2f}\t{m['final']:,}")
        else:
            print(f"{vlabel}\t{plabel}\tN\t-\t-\t-\t-\t-")
            if extra:
                print("--- tail ---")
                print(extra)
                print("------------")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
