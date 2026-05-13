# -*- coding: utf-8 -*-

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path("/Users/yonghyuk/newcodex/MNQ_1m_25pct_backtest.py")


def load_module():
    spec = importlib.util.spec_from_file_location("mnq_bt", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_variant(mod, ticks: int, time_mode: str):
    mod.MIN_TARGET_TICKS = ticks
    mod.TIME_FILTER_MODE = time_mode
    trades, eq_df = mod.run_backtest(BASE_DF)
    stats = mod.summarize(trades, eq_df)
    return {
        "label": f"ticks_{ticks}__{time_mode}",
        "ticks": ticks,
        "time_mode": time_mode,
        **stats,
    }


mod = load_module()
BASE_DF = mod.add_indicators(mod.load_mnq_1m())

VARIANTS = [
    (4, "off"),
    (6, "off"),
    (8, "off"),
    (4, "regular"),
    (6, "regular"),
    (8, "regular"),
    (4, "opening"),
    (6, "opening"),
    (8, "opening"),
]


def score(row):
    return row["return_pct"] - abs(row["max_drawdown_pct"]) * 0.35 + max(row["profit_factor"] - 1.0, -1.0) * 10.0


def main():
    rows = []
    print("MNQ 25% 전략 변형 비교 시작")
    print(f"bars: {len(BASE_DF):,}")
    for ticks, time_mode in VARIANTS:
        print(f"[RUN] ticks={ticks}, time_mode={time_mode}")
        row = run_variant(mod, ticks, time_mode)
        row["score"] = score(row)
        rows.append(row)

    result_df = pd.DataFrame(rows)
    result_df = result_df.sort_values(by=["score", "profit_factor", "return_pct"], ascending=False)

    out_csv = Path("/Users/yonghyuk/newcodex/mnq_backtest_output/mnq_25pct_variant_compare.csv")
    result_df.to_csv(out_csv, index=False)

    print("\n================ VARIANT SUMMARY ================")
    print("label\tscore\ttrades\twin_rate\treturn\tpf\tmdd\tavg_trade")
    for _, r in result_df.iterrows():
        print(
            f"{r['label']}\t{r['score']:.2f}\t{int(r['trades'])}\t{r['win_rate']:.2f}\t"
            f"{r['return_pct']:.2f}\t{r['profit_factor']:.2f}\t{r['max_drawdown_pct']:.2f}\t{r['avg_trade_pnl']:.2f}"
        )

    print("\nBest candidate:")
    best = result_df.iloc[0]
    print(
        f"{best['label']} | trades={int(best['trades'])}, win_rate={best['win_rate']:.2f}%, "
        f"return={best['return_pct']:.2f}%, pf={best['profit_factor']:.2f}, "
        f"mdd={best['max_drawdown_pct']:.2f}%, avg_trade=${best['avg_trade_pnl']:.2f}"
    )
    print(f"\nCSV saved: {out_csv}")


if __name__ == "__main__":
    main()
