# -*- coding: utf-8 -*-
"""V31 — V_FINAL walk-forward validation.

Train fold 에서 grid 로 best params 찾고, 다음 test fold 에서 그 params 사용.

Folds:
  Fold 1: train 2020-01 ~ 2022-12 → test 2023-01 ~ 2024-06
  Fold 2: train 2020-01 ~ 2023-12 → test 2024-01 ~ 2024-12
  Fold 3: train 2020-01 ~ 2024-12 → test 2025-01 ~ 2026-05

Train CAGR ≈ Test CAGR 이면 robust. Train CAGR >> Test CAGR 이면 overfit.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from KOSDAQ_rocket_v8_improve import (
    load_universe_data, load_investor_data, compute_indicators,
    stats, trade_stats, cfg as v8_cfg,
    UNIVERSE_CSV, INIT_CAPITAL,
)
from KOSDAQ_rocket_v11_exit import ExitCfg
from KOSDAQ_rocket_v13_finalize import unique_100pct_count
from KOSDAQ_rocket_v17_market_filter import fetch_kosdaq_index
from KOSDAQ_rocket_v20_robustness import make_lowvol_filter
from KOSDAQ_rocket_v23_entry_quality import simulate_v23
from KOSDAQ_rocket_v25_extra import V25Cfg, V23CfgWrap
import KOSDAQ_rocket_v9_ensemble as v9


def make_screen_with_ma(vm_local, md_local, investor_data):
    from KOSDAQ_rocket_v9_ensemble import has_foreign_buy
    def screen(date, data_ind, data, _, dummy_cfg):
        cands = []
        for ticker, df in data.items():
            df_ind = data_ind[ticker]
            if date not in df_ind.index: continue
            row = df_ind.loc[date]
            if any(pd.isna(row[c]) for c in ['MA60','MA60_slope','High52w','VolAvg50',
                                              'VolAvg10','ATR10','ATR50','Ret_252d','MA200']):
                continue
            if row['MA60'] <= 0 or row['High52w'] <= 0: continue
            if not (row['Close'] > row['MA60']): continue
            if not (row['MA60_slope'] > 0): continue
            if row['Ret_252d'] < 0.20 or row['Ret_252d'] > 3.00: continue
            dist = (row['High52w'] - row['Close']) / row['High52w']
            if dist > 0.60: continue
            if (row['ATR10'] / row['ATR50']) > 1.20: continue
            if (row['VolAvg10'] / row['VolAvg50']) > 1.50: continue
            high_b_prev = df['Close'].rolling(20).max().shift(1).loc[date]
            if pd.isna(high_b_prev): continue
            if not (row['Close'] > high_b_prev): continue
            if not (row['Volume'] > vm_local * row['VolAvg50']): continue
            if (row['Close'] / row['MA200']) > md_local: continue
            if not has_foreign_buy(investor_data, ticker, date, 20): continue
            cands.append({'ticker': ticker, 'close': row['Close'], 'signals': 'A'})
        return cands
    return screen


def run_one(data, data_ind, investor_data, check_market, sim_s, sim_e, vm, md):
    """Run simulate_v23 on [sim_s, sim_e] with given vol_mult, ma200_dist."""
    all_dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    all_scan = all_dates[(all_dates >= sim_s) & (all_dates <= sim_e)]
    all_scan = all_scan[all_scan.weekday == 4]

    vc = V25Cfg(name=f'vol{vm}_ma{md}', ma200_max_dist=md,
                early_be_days=0, early_be_thresh=0.0,
                foreign_5d_min_days=0, atr_close_max=0.0,
                turn_min=0.0, par=0.12, lowvol_th=0.07, max_pos=6)
    vc_wrap = V23CfgWrap(vc)

    class D:
        sig_A = True; sig_B = False; sig_C = False; sig_D = False
    cfg = D()
    exit_cfg = v8_cfg('exit', vol=2.0)
    ec = ExitCfg('e', False, 0.12, 5, False, 3.0)

    v9.screen_v9 = make_screen_with_ma(vm, md, investor_data)
    eq, tr = simulate_v23(data, data_ind, all_scan, investor_data, cfg,
                            sim_s, sim_e, exit_cfg, ec, 6, check_market, vc_wrap)
    cagr, mdd, _ = stats(eq, INIT_CAPITAL)
    ts = trade_stats(tr)
    return {'cagr': cagr, 'mdd': mdd, 'n': ts['n'] if ts else 0,
            'win': ts['win'] if ts else 0, 'gt100': ts['gt100'] if ts else 0,
            'u100': unique_100pct_count(tr), 'eq': eq, 'tr': tr}


def main():
    print("="*78)
    print("V31 — Walk-forward validation of V_FINAL")
    print("="*78)
    udf = pd.read_csv(UNIVERSE_CSV, dtype={'ticker': str})
    data = load_universe_data(udf)
    investor_data = load_investor_data()
    print(f"[data] {len(data)} OHLCV, {len(investor_data)} investor cache")
    print("[indicators] computing...")
    data_ind = {t: compute_indicators(df) for t, df in data.items()}

    kqd = fetch_kosdaq_index()
    check = make_lowvol_filter(kqd, 0.07)

    # Grid for train fold (smaller than V30B, focus on neighborhood of V_FINAL)
    vol_grid = [1.9, 2.0, 2.1, 2.2]
    ma_grid = [1.40, 1.45, 1.50, 1.55]

    folds = [
        # (name, train_s, train_e, test_s, test_e)
        ('Fold1', pd.Timestamp('2021-01-04'), pd.Timestamp('2022-12-31'),
                  pd.Timestamp('2023-01-01'), pd.Timestamp('2024-06-30')),
        ('Fold2', pd.Timestamp('2021-01-04'), pd.Timestamp('2023-12-31'),
                  pd.Timestamp('2024-01-01'), pd.Timestamp('2024-12-31')),
        ('Fold3', pd.Timestamp('2021-01-04'), pd.Timestamp('2024-12-31'),
                  pd.Timestamp('2025-01-01'), pd.Timestamp('2026-05-31')),
    ]

    fold_results = []
    for fname, tr_s, tr_e, te_s, te_e in folds:
        print(f"\n{'='*78}")
        print(f"[{fname}] Train {tr_s.date()} ~ {tr_e.date()} → Test {te_s.date()} ~ {te_e.date()}")
        print('='*78)

        # Train: grid search
        print(f"\n  [{fname} Train] grid:")
        train_grid = {}
        for vm in vol_grid:
            for md in ma_grid:
                r = run_one(data, data_ind, investor_data, check, tr_s, tr_e, vm, md)
                train_grid[(vm, md)] = r
                print(f"    vol={vm:.2f} ma={md:.2f}: CAGR {r['cagr']:+.1f}% MDD {r['mdd']:+.1f}% n={r['n']}")

        # Pick best by CAGR (qualified: CAGR >= 50 and gt100 >= 1)
        qualified = [(k, r) for k, r in train_grid.items()
                     if r['cagr'] >= 50 and r['gt100'] >= 1]
        if not qualified:
            print(f"\n  [{fname}] no qualified config in train → skip")
            continue
        # Best by CAGR / |MDD|
        best_k, best_train = max(qualified, key=lambda x: x[1]['cagr']/abs(x[1]['mdd']))
        print(f"\n  [{fname} Train winner] vol={best_k[0]} ma={best_k[1]} "
              f"CAGR {best_train['cagr']:+.1f}% MDD {best_train['mdd']:+.1f}% n={best_train['n']}")

        # Also V_FINAL fixed
        v_final_train = train_grid[(2.0, 1.45)]
        print(f"  [{fname} V_FINAL on train] CAGR {v_final_train['cagr']:+.1f}% MDD {v_final_train['mdd']:+.1f}%")

        # Test: apply winner params and V_FINAL
        print(f"\n  [{fname} Test] applying params from train...")
        test_winner = run_one(data, data_ind, investor_data, check, te_s, te_e, best_k[0], best_k[1])
        test_vfinal = run_one(data, data_ind, investor_data, check, te_s, te_e, 2.0, 1.45)

        print(f"    Train winner (vol={best_k[0]}, ma={best_k[1]}):")
        print(f"      Train  CAGR {best_train['cagr']:+.1f}% MDD {best_train['mdd']:+.1f}% n={best_train['n']}")
        print(f"      Test   CAGR {test_winner['cagr']:+.1f}% MDD {test_winner['mdd']:+.1f}% n={test_winner['n']}")
        print(f"    V_FINAL (vol=2.0, ma=1.45):")
        print(f"      Train  CAGR {v_final_train['cagr']:+.1f}% MDD {v_final_train['mdd']:+.1f}% n={v_final_train['n']}")
        print(f"      Test   CAGR {test_vfinal['cagr']:+.1f}% MDD {test_vfinal['mdd']:+.1f}% n={test_vfinal['n']}")

        fold_results.append({
            'fold': fname, 'best_params': best_k,
            'train_best': best_train, 'test_best': test_winner,
            'train_vfinal': v_final_train, 'test_vfinal': test_vfinal,
        })

    # Final summary
    print(f"\n{'='*78}")
    print("[Walk-forward Summary]")
    print('='*78)
    print(f"\n  V_FINAL (fixed vol=2.0, ma=1.45):")
    print(f"  {'Fold':>6s} {'Train CAGR':>11s} {'Test CAGR':>10s} {'Δ':>7s} {'Train MDD':>10s} {'Test MDD':>9s}")
    for r in fold_results:
        d = r['test_vfinal']['cagr'] - r['train_vfinal']['cagr']
        print(f"  {r['fold']:>6s} {r['train_vfinal']['cagr']:>+10.1f}% "
              f"{r['test_vfinal']['cagr']:>+9.1f}% {d:>+6.1f}pp "
              f"{r['train_vfinal']['mdd']:>+9.1f}% {r['test_vfinal']['mdd']:>+8.1f}%")

    print(f"\n  Train-optimized winner (different params per fold):")
    print(f"  {'Fold':>6s} {'Params':>13s} {'Train CAGR':>11s} {'Test CAGR':>10s} {'Δ':>7s}")
    for r in fold_results:
        d = r['test_best']['cagr'] - r['train_best']['cagr']
        p = f"vol{r['best_params'][0]} ma{r['best_params'][1]}"
        print(f"  {r['fold']:>6s} {p:>13s} {r['train_best']['cagr']:>+10.1f}% "
              f"{r['test_best']['cagr']:>+9.1f}% {d:>+6.1f}pp")

    # Robustness verdict
    print(f"\n[Verdict]")
    vfinal_test_cagrs = [r['test_vfinal']['cagr'] for r in fold_results]
    vfinal_train_cagrs = [r['train_vfinal']['cagr'] for r in fold_results]
    avg_drop = sum(t - te for t, te in zip(vfinal_train_cagrs, vfinal_test_cagrs)) / len(fold_results)
    print(f"  V_FINAL avg train CAGR: {sum(vfinal_train_cagrs)/len(vfinal_train_cagrs):+.1f}%")
    print(f"  V_FINAL avg test  CAGR: {sum(vfinal_test_cagrs)/len(vfinal_test_cagrs):+.1f}%")
    print(f"  Average drop (train → test): {avg_drop:+.1f}pp")
    if avg_drop > 50:
        print(f"  → SEVERE overfit: test CAGR drops by >50pp on average")
    elif avg_drop > 20:
        print(f"  → Moderate overfit: test CAGR drops by 20-50pp")
    elif avg_drop > -20:
        print(f"  → Robust: train/test CAGR similar (drop < 20pp)")
    else:
        print(f"  → Test > Train (unusual, may indicate fold size effect)")


if __name__ == '__main__':
    main()
