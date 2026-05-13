#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_real_vs_backtest.py
==========================

KIS 실매매 체결 vs Kosdaqpi_Test_upgrade_v7_best.py 백테스트 비교 도구.

매월 1회 직전 달을 비교하는 cron 용도. 임의 기간도 지원.

전제:
  - WSL 서버에서 실행 (KIS 인증 토큰이 있는 환경)
  - autobot_data/v7_best_trades_cache.csv 에 백테스트 trade 캐싱
  - 캐시 재생성은 v7_best 전체 시뮬레이션 (~10분). v7_best.py 변경 시 --refresh

사용 예:
  python compare_real_vs_backtest.py                                  # 직전 달
  python compare_real_vs_backtest.py --start 2026-04-01 --end 2026-04-30
  python compare_real_vs_backtest.py --refresh                        # 캐시 재생성 후 비교
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

import requests

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import KIS_Common as Common  # noqa: E402

V7_BEST_FILE = BASE_DIR / 'Kosdaqpi_Test_upgrade_v7_best.py'
CACHE_DIR = BASE_DIR / 'autobot_data'
TRADES_CACHE = CACHE_DIR / 'v7_best_trades_cache.csv'

INVEST_STOCK_LIST = ["122630", "252670", "233740", "251340"]
STOCK_NAMES = {
    "122630": "KODEX 레버리지",
    "252670": "KODEX 200선물인버스2X",
    "233740": "KODEX 코스닥150레버리지",
    "251340": "KODEX 코스닥150선물인버스",
}

CHUNK_DAYS = 85           # KIS inquire-daily-ccld 호출 분할 단위
KIS_PAGE_SLEEP = 0.25
KIS_TIMEOUT = 30


# ---------- args ----------
def previous_month_window() -> tuple[date, date]:
    today = date.today()
    end = today.replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    return start, end


def parse_args():
    default_start, default_end = previous_month_window()
    p = argparse.ArgumentParser(description="실매매 vs v7_best 백테스트 비교")
    p.add_argument('--start', default=default_start.isoformat(),
                   help='시작일 YYYY-MM-DD (기본: 직전 달 1일)')
    p.add_argument('--end', default=default_end.isoformat(),
                   help='종료일 YYYY-MM-DD (기본: 직전 달 말일)')
    p.add_argument('--refresh', action='store_true',
                   help='v7_best 시뮬레이션 재실행 후 trades 캐시 갱신 (~10분)')
    args = p.parse_args()
    try:
        s = datetime.strptime(args.start, '%Y-%m-%d').date()
        e = datetime.strptime(args.end, '%Y-%m-%d').date()
    except ValueError as ex:
        sys.exit(f"날짜 포맷 오류 (YYYY-MM-DD): {ex}")
    if s > e:
        sys.exit("--start 가 --end 보다 늦음")
    return args, s, e


# ---------- backtest cache (subprocess patch on v7_best.py) ----------
INJECT_HEAD = '''
# === INJECTED by compare_real_vs_backtest.py ===
import csv as _trade_csv_mod
import os as _trade_os
_TRADE_CSV_PATH = _trade_os.environ.get('TRADE_DUMP_CSV', '/tmp/v7_trades.csv')
_trade_csv_fp = open(_TRADE_CSV_PATH, 'w', newline='', encoding='utf-8')
_trade_writer = _trade_csv_mod.writer(_trade_csv_fp)
_trade_writer.writerow(['date', 'code', 'action', 'buy_price', 'sell_price', 'ret', 'buy_date', 'amount_est'])
# === END INJECT ===
'''.lstrip('\n')

# v7_best.py 에서 SELL/BUY print 직후 trade 한 줄 dump
SELL_MARKER = '" 매도가", SellPrice * (1.0 - fee))'
SELL_INJECT = (
    '" 매도가", SellPrice * (1.0 - fee))\n'
    '                        _trade_writer.writerow([str(date), stock_code, "SELL", '
    'float(investData["BuyPrice"]), float(SellPrice), round(float(RevenueRate), 2), '
    'str(investData["Date"]), 0])\n'
    '                        _trade_csv_fp.flush()'
)

BUY_MARKER = '" 돌파가격", DolPaPrice, " 시가:", stock_data[\'open\'].values[0])'
BUY_INJECT = (
    '" 돌파가격", DolPaPrice, " 시가:", stock_data[\'open\'].values[0])\n'
    '                                _trade_writer.writerow([str(date), stock_code, "BUY", '
    'float(DolPaPrice), 0.0, 0.0, "", int(BuyAmt)])\n'
    '                                _trade_csv_fp.flush()'
)


def regenerate_cache():
    if not V7_BEST_FILE.exists():
        sys.exit(f"v7_best.py 없음: {V7_BEST_FILE}")
    CACHE_DIR.mkdir(exist_ok=True)
    src = V7_BEST_FILE.read_text(encoding='utf-8')

    # Inject head after 'fee = 0.0015' so it's after imports/StockDataList
    head_anchor = 'fee = 0.0015'
    if head_anchor not in src:
        sys.exit(f"v7_best.py 에 '{head_anchor}' 마커 없음. 코드 구조 변경됨?")
    src = src.replace(head_anchor, INJECT_HEAD + head_anchor, 1)

    # SELL print (2 occurrences: KOSPI + KOSDAQ)
    sell_count = src.count(SELL_MARKER)
    if sell_count != 2:
        sys.exit(f"SELL 마커 매칭 {sell_count}개 (기대=2). v7_best.py 구조 변경됨?")
    src = src.replace(SELL_MARKER, SELL_INJECT, 2)

    # BUY print (2 occurrences: KOSPI 시가매수 + KOSDAQ 돌파매수)
    buy_count = src.count(BUY_MARKER)
    if buy_count != 2:
        sys.exit(f"BUY 마커 매칭 {buy_count}개 (기대=2). v7_best.py 구조 변경됨?")
    src = src.replace(BUY_MARKER, BUY_INJECT, 2)

    # 플롯 제거 + CSV close
    src = src.replace('plt.show()', "_trade_csv_fp.close(); print('[trades dumped]')")

    with tempfile.NamedTemporaryFile(suffix='.py', dir=str(BASE_DIR),
                                     mode='w', delete=False, encoding='utf-8') as f:
        tmp = Path(f.name)
        f.write(src)

    print(f"[cache] v7_best 시뮬레이션 실행 중 (~10분) ... → {TRADES_CACHE}", flush=True)
    import os
    env = os.environ.copy()
    env['TRADE_DUMP_CSV'] = str(TRADES_CACHE)
    env['MPLBACKEND'] = 'Agg'
    try:
        proc = subprocess.run([sys.executable, str(tmp)],
                              cwd=str(BASE_DIR), env=env,
                              capture_output=True, text=True, timeout=1800)
    finally:
        tmp.unlink(missing_ok=True)

    if proc.returncode != 0:
        print(proc.stdout[-1500:])
        print(proc.stderr[-1500:], file=sys.stderr)
        sys.exit(f"v7_best 시뮬레이션 실패 (returncode={proc.returncode})")

    if not TRADES_CACHE.exists():
        sys.exit(f"캐시 파일 생성 실패: {TRADES_CACHE}")
    print(f"[cache] saved → {TRADES_CACHE}")


def load_cache() -> list[dict]:
    trades = []
    with open(TRADES_CACHE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k in ('buy_price', 'sell_price', 'ret', 'amount_est'):
                if row.get(k) not in (None, ''):
                    try:
                        row[k] = float(row[k])
                    except ValueError:
                        pass
            # date column comes as 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD'; normalize
            d = (row.get('date') or '').split(' ')[0]
            row['date'] = d
            row['buy_date'] = (row.get('buy_date') or '').split(' ')[0]
            trades.append(row)
    return trades


def get_backtest_trades(refresh: bool) -> list[dict]:
    if refresh or not TRADES_CACHE.exists():
        regenerate_cache()
    return load_cache()


# ---------- real trades fetch (KIS API) ----------
def date_chunks(s: date, e: date, days: int = CHUNK_DAYS):
    cur = s
    while cur <= e:
        chunk_end = min(cur + timedelta(days=days - 1), e)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def fetch_real_orders(start: date, end: date) -> list[dict]:
    raw: list[dict] = []
    for cs, ce in date_chunks(start, end):
        raw.extend(_kis_chunk(cs, ce))
    return raw


def _kis_chunk(s: date, e: date) -> list[dict]:
    out: list[dict] = []
    fk, nk = "", ""
    for page in range(50):
        rows, fk, nk, more = _kis_page(s, e, fk, nk)
        out.extend(rows)
        if not more:
            break
        time.sleep(KIS_PAGE_SLEEP)
    return out


def _kis_page(s: date, e: date, fk: str, nk: str):
    dist = Common.GetNowDist()
    tr_id = "TTTC0081R" if dist == "REAL" else "VTTC8001R"
    url = f"{Common.GetUrlBase(dist)}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
    params = {
        "CANO": Common.GetAccountNo(dist),
        "ACNT_PRDT_CD": Common.GetPrdtNo(dist),
        "INQR_STRT_DT": s.strftime('%Y%m%d'),
        "INQR_END_DT": e.strftime('%Y%m%d'),
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "00",
        "PDNO": "",
        "CCLD_DVSN": "01",            # 체결 완료만
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "INQR_DVSN_2": "",
        "CTX_AREA_FK100": fk,
        "CTX_AREA_NK100": nk,
        "EXCG_ID_DVSN_CD": "KRX",
    }
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {Common.GetToken(dist)}",
        "appKey": Common.GetAppKey(dist),
        "appSecret": Common.GetAppSecret(dist),
        "tr_id": tr_id,
        "tr_cont": "" if fk == "" else "N",
        "custtype": "P",
        "hashkey": Common.GetHashKey(params),
    }
    time.sleep(KIS_PAGE_SLEEP)
    res = requests.get(url, headers=headers, params=params, timeout=KIS_TIMEOUT)
    if res.status_code != 200:
        print(f"[err] KIS HTTP {res.status_code}: {res.text[:300]}", file=sys.stderr)
        return [], "", "", False
    data = res.json()
    if data.get('rt_cd') != '0':
        print(f"[err] KIS rt_cd={data.get('rt_cd')} msg={data.get('msg1')}",
              file=sys.stderr)
        return [], "", "", False

    rows: list[dict] = []
    for o in data.get('output1', []) or []:
        try:
            filled = int(float(o.get('tot_ccld_qty', '0') or '0'))
            avg_price = float(o.get('avg_prvs', '0') or '0')
        except (ValueError, TypeError):
            continue
        rows.append({
            'date': o.get('ord_dt', ''),
            'time': o.get('ord_tmd', ''),
            'code': o.get('pdno', ''),
            'side': 'BUY' if o.get('sll_buy_dvsn_cd') == '02' else 'SELL',
            'avg_price': avg_price,
            'filled_qty': filled,
            'cancelled': o.get('cncl_yn', 'N') == 'Y',
        })
    fk_next = (data.get('ctx_area_fk100') or '').strip()
    nk_next = (data.get('ctx_area_nk100') or '').strip()
    more = (data.get('tr_cont') in ('F', 'M')) and bool(nk_next)
    return rows, fk_next, nk_next, more


def pair_for_returns(orders: list[dict]) -> list[dict]:
    """FIFO BUY→SELL 매칭으로 ret% 계산 (4종목 중심)"""
    orders = [o for o in orders
              if o['code'] in INVEST_STOCK_LIST
              and not o['cancelled']
              and o['filled_qty'] > 0]
    orders.sort(key=lambda x: (x['date'], x['time']))

    open_pos: dict[str, deque] = defaultdict(deque)
    result: list[dict] = []
    for o in orders:
        code = o['code']
        ymd = (f"{o['date'][:4]}-{o['date'][4:6]}-{o['date'][6:8]}"
               if len(o['date']) == 8 else o['date'])
        if o['side'] == 'BUY':
            open_pos[code].append({'date': ymd, 'price': o['avg_price'],
                                   'qty': o['filled_qty']})
            result.append({'date': ymd, 'code': code, 'action': 'BUY',
                           'buy_price': o['avg_price'],
                           'qty': o['filled_qty']})
        else:
            sell_qty = o['filled_qty']
            paired_qty, weighted_buy = 0, 0.0
            buy_date = None
            while sell_qty > 0 and open_pos[code]:
                pos = open_pos[code][0]
                use = min(sell_qty, pos['qty'])
                weighted_buy += pos['price'] * use
                paired_qty += use
                sell_qty -= use
                if buy_date is None:
                    buy_date = pos['date']
                pos['qty'] -= use
                if pos['qty'] == 0:
                    open_pos[code].popleft()
            ret = None
            avg_buy = None
            if paired_qty > 0:
                avg_buy = weighted_buy / paired_qty
                ret = round((o['avg_price'] - avg_buy) / avg_buy * 100, 2)
            result.append({'date': ymd, 'code': code, 'action': 'SELL',
                           'sell_price': o['avg_price'],
                           'qty': o['filled_qty'],
                           'ret': ret, 'avg_buy_price': avg_buy,
                           'buy_date': buy_date})
    return result


# ---------- matching & report ----------
def in_range(d: str, s: date, e: date) -> bool:
    try:
        return s <= datetime.strptime(d, '%Y-%m-%d').date() <= e
    except (ValueError, TypeError):
        return False


def _f(v):
    if v in (None, ''):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def render(start: date, end: date, real: list[dict], bt: list[dict]):
    period = f"{start.isoformat()} ~ {end.isoformat()}"
    print(f"실매매 vs v7_best 백테스트 비교 ({period})\n")

    bt_w = [t for t in bt if in_range(t.get('date', ''), start, end)]
    rl_w = [t for t in real if in_range(t.get('date', ''), start, end)]

    print("[백테스트 이벤트]")
    if not bt_w:
        print("  (없음)")
    for t in bt_w:
        if t.get('action') == 'SELL':
            ret = _f(t.get('ret'))
            sp = _f(t.get('sell_price'))
            print(f"{t['date']} {t['code']} SELL "
                  f"ret={ret}% buy_date={t.get('buy_date')} "
                  f"buy_price={_f(t.get('buy_price'))} "
                  f"sell_price={round(sp, 2) if sp else None}")
        else:
            print(f"{t['date']} {t['code']} BUY "
                  f"buy_price={_f(t.get('buy_price'))} "
                  f"amount_est={int(_f(t.get('amount_est')) or 0)}")

    print("\n[실거래 이벤트]")
    if not rl_w:
        print("  (없음)")
    for t in rl_w:
        if t['action'] == 'SELL':
            ret = t.get('ret')
            ret_s = f"{ret}%" if ret is not None else "?%"
            print(f"{t['date']} {t['code']} SELL ret={ret_s} "
                  f"sell_price={t.get('sell_price')} qty={t.get('qty')}")
        else:
            print(f"{t['date']} {t['code']} BUY "
                  f"buy_price={t.get('buy_price')} qty={t.get('qty')}")

    print("\n[매칭 요약]")
    used = set()
    for at in rl_w:
        match_idx = None
        for idx, bt_t in enumerate(bt_w):
            if idx in used:
                continue
            if (bt_t.get('date') == at['date']
                    and bt_t.get('code') == at['code']
                    and bt_t.get('action') == at['action']):
                match_idx = idx
                break
        if match_idx is not None:
            used.add(match_idx)
            bt_t = bt_w[match_idx]
            if at['action'] == 'SELL':
                ar = at.get('ret')
                br = _f(bt_t.get('ret'))
                delta = (round(ar - br, 2)
                         if (ar is not None and br is not None) else None)
                print(f"MATCH {at['date']} {at['code']} SELL | "
                      f"actual={ar}% bt={br}% delta={delta}")
            else:
                print(f"MATCH {at['date']} {at['code']} BUY | "
                      f"actual={at.get('buy_price')} "
                      f"bt={_f(bt_t.get('buy_price'))}")
        else:
            print(f"MISS  {at['date']} {at['code']} {at['action']} | "
                  f"백테스트에 동일 이벤트 없음")

    print("\n[백테스트에만 있는 이벤트]")
    only = [bt_w[i] for i in range(len(bt_w)) if i not in used]
    if not only:
        print("  (없음)")
    for bt_t in only:
        if bt_t.get('action') == 'SELL':
            print(f"BT_ONLY {bt_t['date']} {bt_t['code']} SELL "
                  f"ret={_f(bt_t.get('ret'))}% buy_date={bt_t.get('buy_date')}")
        else:
            print(f"BT_ONLY {bt_t['date']} {bt_t['code']} BUY "
                  f"buy_price={_f(bt_t.get('buy_price'))}")


# ---------- main ----------
def main():
    args, start, end = parse_args()
    bt_trades = get_backtest_trades(args.refresh)
    real_orders = fetch_real_orders(start, end)
    real_trades = pair_for_returns(real_orders)
    render(start, end, real_trades, bt_trades)


if __name__ == '__main__':
    main()
