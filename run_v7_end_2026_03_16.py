# -*- coding: utf-8 -*-
"""
사용자가 2026-03-16에 실행했던 결과(11208.14%, MDD -23.6%, CAGR 74.42%)와
동일 조건으로 재현 가능한지 확인.

차이점:
 - KIS GetOhlcv(N=2200)는 호출 시점 기준 2200영업일을 줌
   이전(2026-03-16) → 2017-09-14 부터
   현재(2026-05-13) → 2017-11-17 부터  (시작점 자체는 재현 불가)
 - 종료일은 2026-03-16 으로 컷오프 가능 → 이걸로 실행
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_best.py')
START_DATE = "2017-09-14"
END_DATE = "2026-03-16"


def main() -> int:
    src = BASE.read_text()

    # 1) GetOhlcv 2200 → 2400 (2017-09-14 데이터까지 확보)
    if 'Common.GetOhlcv("KR", stock_code,2200)' not in src:
        print("[err] couldn't locate GetOhlcv call")
        return 1
    src = src.replace(
        'Common.GetOhlcv("KR", stock_code,2200)',
        'Common.GetOhlcv("KR", stock_code,2400)',
        1)

    # 2) combined_df 정렬 직후 시작/종료 날짜 필터
    sort_line = "combined_df.sort_index(inplace=True)"
    if sort_line not in src:
        print("[err] couldn't locate combined_df.sort_index")
        return 1
    src = src.replace(
        sort_line,
        sort_line +
        "\n# INJECTED: window filter for reproducibility\n"
        f"combined_df = combined_df[(combined_df.index >= '{START_DATE}') & "
        f"(combined_df.index <= '{END_DATE}')]\n"
        f"print('[window]', '{START_DATE}', '~', '{END_DATE}', 'rows=', len(combined_df))\n",
        1)

    src = src.replace('plt.show()', "print('[skip plot]')")

    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE.parent),
                                     mode='w', delete=False) as f:
        tmp = Path(f.name)
        f.write(src)

    print(f"[run] cutoff <= 2026-03-16, tmp={tmp.name}")
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              capture_output=True, text=True,
                              cwd=str(BASE.parent), timeout=1800)
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print("[err] non-zero exit")
        print(proc.stderr[-2000:])
        return 1

    out = proc.stdout
    # 최종 결과만 추출
    m = re.search(r"--->>>.*?연복리수익률\(CAGR\):.*", out, re.DOTALL)
    if m:
        print("\n========== 결과 (종료일 2026-03-16) ==========")
        print(m.group(0))
    else:
        print(out[-3000:])

    print("\n========== 사용자 이전 실행 (2026-03-16) ==========")
    print("최초 금액: 10,000,000  최종 금액: 1,130,814,038")
    print("수익률: 11208.14 % MDD: -23.6 %  CAGR: 74.42 %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
