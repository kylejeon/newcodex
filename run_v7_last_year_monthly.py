# -*- coding: utf-8 -*-
'''
Kosdaqpi_Test_upgrade_v7_best.py 를 최근 1년 구간으로 백테스트.
- StartYear=2025 로 패치 (2025-01-01 부터 트레이딩 시작, 약 16개월치)
- result_df 를 CSV로 덤프하도록 injection
- 월별 수익, 최근 1년(365일) 수익, MDD 등 재집계
- 특히 2026-03 월 수익에 주목
'''
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


BASE_FILE = Path('/Users/yonghyuk/newcodex/Kosdaqpi_Test_upgrade_v7_best.py')
OUT_DIR = Path('/Users/yonghyuk/newcodex/mnq_backtest_output')
OUT_DIR.mkdir(exist_ok=True)
EQUITY_CSV = OUT_DIR / 'v7_last_year_daily_equity.csv'
TRADES_CSV = OUT_DIR / 'v7_last_year_trades.csv'


def patch_source(src: str, start_year: int, trades_csv: Path, equity_csv: Path) -> str:
    # 시작 연도 변경
    src = re.sub(r'StartYear\s*=\s*\d+', f'StartYear = {start_year}', src)

    # plt.show 블로킹 방지
    src = src.replace('plt.show()', "print('[skip plot]')")

    # ==== 거래 로그 캡처 인젝션 ====
    # "매도!" 라인 직전·직후에 거래 로그 파일 append
    # 매도 분기가 2개 있음: 코스닥 블록 + 코스피 블록
    # print(..., "매도! 매수일:",investData['Date']...) 구문
    trade_write_code = (
        "                        try:\n"
        "                            with open(" + repr(str(trades_csv)) + ", 'a') as __tf:\n"
        "                                __tf.write(f'{str(date)},{stock_code},{GetStockName(stock_code, StockDataList)},"
        "{investData[\"Date\"]},{investData[\"BuyPrice\"]},{investData[\"FirstMoney\"]},{SellPrice},"
        "{RevenueRate},{ReturnMoney}\\n')\n"
        "                        except Exception as __e:\n"
        "                            pass\n"
    )
    # 매도 print 라인 2곳 모두 바로 뒤에 로그 추가
    # 실제 소스: `, " 매도가", SellPrice * (1.0 - fee))` -- 콤마 아닌 "공백 매도가"
    marker = '" 매도가", SellPrice * (1.0 - fee))'
    if marker not in src:
        raise RuntimeError("trade log marker not found in source")
    src = src.replace(marker, marker + "\n" + trade_write_code)

    # ==== result_df CSV 덤프 인젝션 ====
    dump_code = (
        "    # ==== INJECTED: dump result_df to CSV ====\n"
        f"    result_df.to_csv({str(equity_csv)!r})\n"
        "    print('[INJECTED] daily equity CSV saved ->', " + repr(str(equity_csv)) + ")\n"
        "\n"
    )
    src = src.replace(
        "    resultData['DateStr']",
        dump_code + "    resultData['DateStr']",
        1,
    )

    return src


def run_backtest(start_year: int) -> None:
    # 거래 로그 파일 초기화
    with open(TRADES_CSV, 'w') as f:
        f.write('date,code,name,buy_date,buy_price,first_money,sell_price,revenue_rate,return_money\n')

    src = BASE_FILE.read_text()
    patched = patch_source(src, start_year, TRADES_CSV, EQUITY_CSV)

    # 같은 디렉토리에 임시 파일 (상대 import 유지)
    with tempfile.NamedTemporaryFile(
        suffix='.py', dir=str(BASE_FILE.parent), mode='w', delete=False
    ) as f:
        tmp_path = Path(f.name)
        f.write(patched)

    print(f"[run] subprocess starting, tmp={tmp_path.name}")
    try:
        proc = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True, text=True,
            timeout=900,
            cwd=str(BASE_FILE.parent),
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    # stdout 마지막 일부만 출력 (노이즈 줄임)
    tail = "\n".join(proc.stdout.splitlines()[-25:])
    print("[run] --- stdout tail ---")
    print(tail)
    if proc.stderr:
        print("[run] --- stderr ---")
        print(proc.stderr[-1500:])


def analyze():
    if not EQUITY_CSV.exists():
        raise RuntimeError(f"{EQUITY_CSV} not found — backtest may have failed")
    df = pd.read_csv(EQUITY_CSV, index_col=0, parse_dates=[0])
    df = df.sort_index()
    df['Total_Money'] = df['Total_Money'].astype(float)
    print(f"\n[analyze] rows={len(df)}  range={df.index[0].date()} ~ {df.index[-1].date()}")

    # 트레이드 시작점 (equity가 초기값에서 변동을 시작한 첫 날) 찾기
    init = df['Total_Money'].iloc[0]
    first_change_idx = (df['Total_Money'] != init).idxmax() if (df['Total_Money'] != init).any() else df.index[0]
    print(f"[analyze] first equity change at: {first_change_idx.date()}  (initial ${init:,.0f})")

    # 최근 1년 (365일) 슬라이스
    end_date = df.index[-1]
    one_year_ago = end_date - pd.Timedelta(days=365)
    one_year_df = df[df.index >= one_year_ago].copy()
    if len(one_year_df) == 0:
        print("[analyze] no data in last 365d range")
        return
    base_1y = one_year_df['Total_Money'].iloc[0]
    final = float(df['Total_Money'].iloc[-1])
    one_year_return = (final / base_1y - 1.0) * 100.0

    # MDD (1년 구간)
    cummax = one_year_df['Total_Money'].cummax()
    dd = (one_year_df['Total_Money'] / cummax - 1.0) * 100.0
    mdd_1y = float(dd.min())

    print("\n================ 최근 1년 (365일) ================")
    print(f"기간: {one_year_df.index[0].date()} ~ {end_date.date()}")
    print(f"시작 잔고: {base_1y:,.0f}원")
    print(f"종료 잔고: {final:,.0f}원")
    print(f"순수익:     {final - base_1y:+,.0f}원")
    print(f"수익률:     {one_year_return:+.2f}%")
    print(f"MDD:        {mdd_1y:.2f}%")

    # 전체 구간 (백테스트 시작 ~ 오늘)
    # StartYear=2025 이므로 2025-01-01 이후 중 첫 거래일부터 계산
    trading_start = df.index[df.index.year >= 2025].min()
    if pd.notna(trading_start):
        tdf = df[df.index >= trading_start]
        base_all = tdf['Total_Money'].iloc[0]
        total_return = (final / base_all - 1.0) * 100.0
        cummax_a = tdf['Total_Money'].cummax()
        dd_a = (tdf['Total_Money'] / cummax_a - 1.0) * 100.0
        print("\n================ 전체 (2025 시작) ================")
        print(f"기간: {tdf.index[0].date()} ~ {end_date.date()}")
        print(f"시작 잔고: {base_all:,.0f}원")
        print(f"종료 잔고: {final:,.0f}원")
        print(f"순수익:     {final - base_all:+,.0f}원")
        print(f"수익률:     {total_return:+.2f}%")
        print(f"MDD:        {float(dd_a.min()):.2f}%")

    # 월별 수익 (StartYear=2025 이후만)
    month_df = df[df.index.year >= 2025].copy()
    month_df['month'] = month_df.index.to_period('M').astype(str)
    monthly_last = month_df.groupby('month')['Total_Money'].agg(['first', 'last', 'min', 'max'])
    monthly_last['net_pnl'] = monthly_last['last'] - monthly_last['first']
    monthly_last['ret_pct'] = (monthly_last['last'] / monthly_last['first'] - 1) * 100
    print("\n================ 월별 수익 (2025-01 ~) ================")
    print(monthly_last.round(2).to_string())
    monthly_last.to_csv(OUT_DIR / 'v7_last_year_monthly.csv')

    # 2026-03 집중 분석
    mar_2026 = df[(df.index.year == 2026) & (df.index.month == 3)].copy()
    if len(mar_2026) > 0:
        start_eq = mar_2026['Total_Money'].iloc[0]
        end_eq = mar_2026['Total_Money'].iloc[-1]
        ret = (end_eq / start_eq - 1) * 100
        peak = mar_2026['Total_Money'].max()
        trough = mar_2026['Total_Money'].min()
        cummax_m = mar_2026['Total_Money'].cummax()
        dd_m = (mar_2026['Total_Money'] / cummax_m - 1) * 100
        print("\n================ 2026년 3월 집중 ================")
        print(f"거래일수:    {len(mar_2026)}일")
        print(f"시작일 잔고: {start_eq:,.0f}원 ({mar_2026.index[0].date()})")
        print(f"종료일 잔고: {end_eq:,.0f}원 ({mar_2026.index[-1].date()})")
        print(f"월 순수익:   {end_eq - start_eq:+,.0f}원")
        print(f"월 수익률:   {ret:+.2f}%")
        print(f"월중 최고:   {peak:,.0f}원")
        print(f"월중 최저:   {trough:,.0f}원")
        print(f"월중 MDD:    {float(dd_m.min()):.2f}%")

        # 해당 월 거래 건수
        if TRADES_CSV.exists():
            tdf = pd.read_csv(TRADES_CSV)
            tdf['date'] = pd.to_datetime(tdf['date'])
            mar_trades = tdf[(tdf['date'].dt.year == 2026) & (tdf['date'].dt.month == 3)]
            if len(mar_trades) > 0:
                wins = mar_trades[mar_trades['revenue_rate'] > 0]
                losses = mar_trades[mar_trades['revenue_rate'] <= 0]
                print(f"월 매도 건수: {len(mar_trades)}건  "
                      f"(승 {len(wins)} / 패 {len(losses)}, "
                      f"승률 {len(wins) / len(mar_trades) * 100:.1f}%)")
                print(f"평균 수익률/거래: {mar_trades['revenue_rate'].mean():+.2f}%")
                print("\n[2026-03 매도 로그]")
                print(mar_trades[['date', 'name', 'buy_date', 'revenue_rate', 'return_money']]
                      .to_string(index=False))
    else:
        print("\n[경고] 2026-03 데이터 없음")

    print(f"\n[saved] 일봉 잔고 -> {EQUITY_CSV}")
    print(f"[saved] 월별 -> {OUT_DIR / 'v7_last_year_monthly.csv'}")
    print(f"[saved] 매도 로그 -> {TRADES_CSV}")


def main():
    run_backtest(start_year=2025)
    analyze()


if __name__ == "__main__":
    main()
