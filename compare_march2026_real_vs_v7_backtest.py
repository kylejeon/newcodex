import math
from datetime import datetime

import pandas as pd

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR

Common.SetChangeMode("REAL")

InvestStockList = ["122630", "252670", "233740", "251340"]
TotalMoney = 10000000
fee = 0.0015
StartYear = 2017

ENABLE_233740_HARD_STOP = True
HARD_STOP_233740_PCT_TIGHT = 0.085
HARD_STOP_233740_PCT_BASE = 0.125
HARD_STOP_VOL_TH = 0.045
CLOSE_BASED_CUT_CODES = {"233740", "251340"}
KOSPI_252670_DISPARITY11_TH = 106
KOSPI_122630_DISPARITY_LOW = 98
KOSPI_122630_DISPARITY_HIGH = 105
KOSPI_MIN_HOLD_DAYS = 0
KOSPI_252670_BUY_RSI_MAX = 70
KOSPI_122630_BUY_DISPARITY_LOW = 97
KOSPI_122630_BUY_DISPARITY_HIGH = 107
KOSPI_122630_BUY_RSI_MAX = 80

gugan_lenth = 7

ACTUAL_TRADES = [
    {"date": "2026-03-03", "code": "233740", "action": "SELL", "ret": -5.40},
    {"date": "2026-03-10", "code": "233740", "action": "SELL", "ret": -6.70},
    {"date": "2026-03-11", "code": "122630", "action": "BUY"},
    {"date": "2026-03-12", "code": "233740", "action": "BUY"},
    {"date": "2026-03-16", "code": "122630", "action": "SELL", "ret": -7.10},
    {"date": "2026-03-16", "code": "233740", "action": "SELL", "ret": -1.34},
    {"date": "2026-03-18", "code": "122630", "action": "BUY"},
    {"date": "2026-03-18", "code": "233740", "action": "BUY"},
    {"date": "2026-03-20", "code": "122630", "action": "SELL", "ret": -0.29},
    {"date": "2026-03-20", "code": "233740", "action": "SELL", "ret": -2.80},
    {"date": "2026-03-23", "code": "233740", "action": "SELL", "ret": -7.56},
    {"date": "2026-03-24", "code": "251340", "action": "BUY"},
    {"date": "2026-03-25", "code": "122630", "action": "BUY"},
    {"date": "2026-03-25", "code": "251340", "action": "SELL", "ret": -3.14},
    {"date": "2026-03-30", "code": "122630", "action": "SELL", "ret": -19.60},
]


STOCK_NAME_CACHE = {}

def stock_name(code):
    if code in STOCK_NAME_CACHE:
        return STOCK_NAME_CACHE[code]
    try:
        name = KisKR.GetStockName(code)
    except Exception:
        name = code
    STOCK_NAME_CACHE[code] = name
    return name


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def calc_hold_days(curr_date, buy_date_str):
    try:
        buy_dt = pd.to_datetime(buy_date_str)
        cur_dt = pd.to_datetime(curr_date)
        return max(0, (cur_dt.normalize() - buy_dt.normalize()).days)
    except Exception:
        return 0


def build_daily_df(stock_code):
    df = Common.GetOhlcv("KR", stock_code, 2200)

    period = 14
    delta = df["close"].diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    gain = up.ewm(com=(period - 1), min_periods=period).mean()
    loss = down.abs().ewm(com=(period - 1), min_periods=period).mean()
    rs = gain / loss
    df['RSI'] = pd.Series(100 - (100 / (1 + rs)), name="RSI")
    df['prevRSI'] = df['RSI'].shift(1)
    df['prevRSI2'] = df['RSI'].shift(2)
    df['high_7_max'] = df['high'].rolling(window=gugan_lenth).max().shift(1)
    df['low_7_min'] = df['low'].rolling(window=gugan_lenth).min().shift(1)

    df['direction'] = 0
    df.loc[df['close'] > df['close'].shift(1), 'direction'] = 1
    df.loc[df['close'] < df['close'].shift(1), 'direction'] = -1
    df['obv'] = (df['direction'] * df['volume']).cumsum()
    df['obv_ma'] = df['obv'].rolling(window=10).mean()
    df['prev_obv_ma'] = df['obv_ma'].shift(1)
    df['prev_obv_ma2'] = df['obv_ma'].shift(2)
    df['prev_obv'] = df['obv'].shift(1)

    df['prevVolume'] = df['volume'].shift(1)
    df['prevVolume2'] = df['volume'].shift(2)
    df['prevVolume3'] = df['volume'].shift(3)
    df['prevClose'] = df['close'].shift(1)
    df['prevOpen'] = df['open'].shift(1)
    df['prevHigh'] = df['high'].shift(1)
    df['prevHigh2'] = df['high'].shift(2)
    df['prevLow'] = df['low'].shift(1)
    df['prevLow2'] = df['low'].shift(2)
    df['Disparity20'] = df['prevClose'] / df['prevClose'].rolling(window=20).mean() * 100.0
    df['Disparity11'] = df['prevClose'] / df['prevClose'].rolling(window=11).mean() * 100.0
    df['ma3_before'] = df['close'].rolling(3).mean().shift(1)
    df['ma6_before'] = df['close'].rolling(6).mean().shift(1)
    df['ma19_before'] = df['close'].rolling(19).mean().shift(1)
    df['ma10_before'] = df['close'].rolling(10).mean().shift(1)
    df['ma20_before'] = df['close'].rolling(20).mean().shift(1)
    df['ma20_before2'] = df['close'].rolling(20).mean().shift(2)
    df['ma60_before'] = df['close'].rolling(60).mean().shift(1)
    df['ma60_before2'] = df['close'].rolling(60).mean().shift(2)
    df['ma120_before'] = df['close'].rolling(120).mean().shift(1)
    df['prevChangeMa'] = df['change'].shift(1).rolling(window=20).mean()
    df['prevChangeMa_S'] = df['change'].shift(1).rolling(window=10).mean()

    specific_days = [i * 10 for i in range(1, 11)]
    for day in specific_days:
        df[f'Momentum_{day}'] = (df['prevClose'] > df['close'].shift(day)).astype(int)
    df['Average_Momentum'] = df[[f'Momentum_{day}' for day in specific_days]].sum(axis=1) / 10

    specific_days = [i * 3 for i in range(1, 11)]
    for day in specific_days:
        df[f'Momentum_{day}'] = (df['prevClose'] > df['close'].shift(day)).astype(int)
    df['Average_Momentum3'] = df[[f'Momentum_{day}' for day in specific_days]].sum(axis=1) / 10
    df.dropna(inplace=True)
    return df


def get_row(date_df, code):
    row = date_df[date_df['stock_code'] == code]
    if len(row) != 1:
        return None
    return row.iloc[0]


def simulate_trades():
    stock_df_list = []
    for code in InvestStockList:
        df = build_daily_df(code)
        stock_df_list.append({code: df})

    combined_df = pd.concat([list(d.values())[0].assign(stock_code=code) for d in stock_df_list for code in d])
    combined_df.sort_index(inplace=True)

    remain_invest_money = TotalMoney
    invest_money = TotalMoney
    now_invest_list = []
    is_cut = False
    is_cut_cnt = 0
    trades = []

    all_dates = list(combined_df.index.unique())
    for idx_date, date in enumerate(all_dates, start=1):
        if idx_date % 250 == 0:
            print(f"[SIM] {idx_date}/{len(all_dates)} {pd.to_datetime(date).date()}")
        date_object = pd.to_datetime(date)
        if int(date_object.strftime("%Y")) < StartYear:
            continue

        all_stocks = combined_df.loc[combined_df.index == date].groupby('stock_code')['close'].max().nlargest(len(InvestStockList))
        kq_long = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "233740")]
        kq_short = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "251340")]
        kp_long = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "122630")]
        kp_short = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "252670")]

        is_no_way = False
        if len(kq_long) == 1 and len(kq_short) == 1 and len(kp_long) == 1 and len(kp_short) == 1:
            if ((kp_long['prevChangeMa_S'].values[0] > 0 and kp_short['prevChangeMa_S'].values[0] > 0)
                or (kp_long['prevChangeMa_S'].values[0] < 0 and kp_short['prevChangeMa_S'].values[0] < 0)
                or (kq_long['prevChangeMa_S'].values[0] > 0 and kq_short['prevChangeMa_S'].values[0] > 0)
                or (kq_long['prevChangeMa_S'].values[0] < 0 and kq_short['prevChangeMa_S'].values[0] < 0)):
                is_no_way = True

        today_sell_code = []
        items_to_remove = []
        kosdaq_sell_cnt = 0
        kosdaq_sell_money_future = 0.0

        for invest_data in now_invest_list:
            stock_code = invest_data['stock_code']
            if invest_data['InvestMoney'] <= 0:
                continue
            stock_data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
            if len(stock_data) != 1:
                continue
            row = stock_data.iloc[0]

            if stock_code in ["233740", "251340"]:
                now_open = row['open']
                prev_open = row['prevOpen']
                prev_close = row['prevClose']
                cut_rate = 0.35 if stock_code == "251340" else (0.35 if prev_close > row['ma60_before'] else 0.25)
                cut_price = row['open'] - ((row['prevHigh'] - row['prevLow']) * cut_rate)
                sell_price = now_open
                is_sell_go = False
                if stock_code in CLOSE_BASED_CUT_CODES:
                    if cut_price >= row['close']:
                        is_sell_go = True
                        sell_price = cut_price
                else:
                    if cut_price >= row['low']:
                        is_sell_go = True
                        sell_price = cut_price
                if ENABLE_233740_HARD_STOP and stock_code == "233740":
                    prev_range_ratio = (row['prevHigh'] - row['prevLow']) / row['prevClose']
                    weak_trend = row['prevClose'] <= row['ma20_before']
                    is_high_vol = prev_range_ratio >= HARD_STOP_VOL_TH
                    hard_stop_pct = HARD_STOP_233740_PCT_TIGHT if (weak_trend and is_high_vol) else HARD_STOP_233740_PCT_BASE
                    hard_stop_price = invest_data['BuyPrice'] * (1.0 - hard_stop_pct)
                    if row['low'] <= hard_stop_price:
                        is_sell_go = True
                        sell_price = now_open if now_open <= hard_stop_price else hard_stop_price

                if not invest_data['DolPaCheck']:
                    invest_data['DolPaCheck'] = True
                    invest_data['InvestMoney'] *= (1.0 + ((sell_price - invest_data['BuyPrice']) / invest_data['BuyPrice']))
                else:
                    invest_data['InvestMoney'] *= (1.0 + ((sell_price - prev_open) / prev_open))

                rate = (sell_price * (1.0 - fee) - invest_data['BuyPrice']) / invest_data['BuyPrice']
                revenue_rate = (rate - fee) * 100.0
                if is_sell_go:
                    if revenue_rate < 0:
                        is_cut = True
                        is_cut_cnt += 1
                    else:
                        is_cut = False
                        is_cut_cnt = max(0, is_cut_cnt - 1)
                    return_money = invest_data['InvestMoney'] * (1.0 - fee)
                    if now_open > cut_price:
                        kosdaq_sell_money_future += return_money
                    remain_invest_money += return_money
                    invest_data['InvestMoney'] = 0
                    trades.append({
                        'date': str(date_object.date()),
                        'code': stock_code,
                        'name': stock_name(stock_code),
                        'action': 'SELL',
                        'buy_date': invest_data['Date'],
                        'buy_price': invest_data['BuyPrice'],
                        'sell_price': sell_price,
                        'ret': round(revenue_rate, 2),
                    })
                    items_to_remove.append(invest_data)
                    today_sell_code.append(stock_code)
                    kosdaq_sell_cnt += 1
            else:
                now_open = row['open']
                prev_open = row['prevOpen']
                prev_close = row['prevClose']
                sell_price = now_open
                is_sell_go = False
                hold_days = calc_hold_days(date, invest_data.get('Date', str(date)))
                if not invest_data['DolPaCheck']:
                    invest_data['DolPaCheck'] = True
                    invest_data['InvestMoney'] *= (1.0 + ((sell_price - invest_data['BuyPrice']) / invest_data['BuyPrice']))
                else:
                    invest_data['InvestMoney'] *= (1.0 + ((sell_price - prev_open) / prev_open))
                rate = (sell_price * (1.0 - fee) - invest_data['BuyPrice']) / invest_data['BuyPrice']
                revenue_rate = (rate - fee) * 100.0
                if stock_code == "252670":
                    if row['Disparity11'] > KOSPI_252670_DISPARITY11_TH:
                        if prev_close < row['ma3_before']:
                            is_sell_go = True
                    else:
                        if prev_close < row['ma6_before'] and prev_close < row['ma19_before']:
                            is_sell_go = True
                else:
                    total_volume = (row['prevVolume'] + row['prevVolume2'] + row['prevVolume3']) / 3.0
                    disparity = row['Disparity20']
                    if not ((row['prevLow2'] < row['prevLow'] or row['prevVolume'] < total_volume) and (disparity < KOSPI_122630_DISPARITY_LOW or disparity > KOSPI_122630_DISPARITY_HIGH)):
                        is_sell_go = True
                if KOSPI_MIN_HOLD_DAYS > 0 and hold_days < KOSPI_MIN_HOLD_DAYS:
                    is_sell_go = False
                if is_sell_go:
                    return_money = invest_data['InvestMoney'] * (1.0 - fee)
                    remain_invest_money += return_money
                    invest_data['InvestMoney'] = 0
                    trades.append({
                        'date': str(date_object.date()),
                        'code': stock_code,
                        'name': stock_name(stock_code),
                        'action': 'SELL',
                        'buy_date': invest_data['Date'],
                        'buy_price': invest_data['BuyPrice'],
                        'sell_price': sell_price,
                        'ret': round(revenue_rate, 2),
                    })
                    items_to_remove.append(invest_data)
                    today_sell_code.append(stock_code)

        for item in items_to_remove:
            now_invest_list.remove(item)

        if len(now_invest_list) < int(len(InvestStockList)) / 2 and int(date_object.strftime("%Y")) >= StartYear:
            for stock_code in all_stocks.index:
                already = any(stock_code == inv['stock_code'] for inv in now_invest_list)
                if stock_code in today_sell_code or already:
                    continue
                stock_data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
                row = stock_data.iloc[0]
                if stock_code in ["122630", "252670"]:
                    prev_close = row['prevClose']
                    buy_price = row['open']
                    is_buy_go = False
                    if stock_code == "252670":
                        if prev_close > row['ma3_before'] and prev_close > row['ma6_before'] and prev_close > row['ma19_before'] and row['prevRSI'] < KOSPI_252670_BUY_RSI_MAX and row['prevRSI2'] < row['prevRSI']:
                            cond = (row['prevVolume2'] < row['prevVolume']) and (row['prevLow2'] < row['prevLow']) and prev_close > row['ma60_before'] and row['ma60_before2'] < row['ma60_before'] and row['ma3_before'] > row['ma6_before'] > row['ma19_before']
                            if cond:
                                is_buy_go = True
                    else:
                        disparity = row['Disparity20']
                        if (row['prevLow2'] < row['prevLow']) and (disparity < KOSPI_122630_BUY_DISPARITY_LOW or disparity > KOSPI_122630_BUY_DISPARITY_HIGH) and row['prevRSI'] < KOSPI_122630_BUY_RSI_MAX:
                            is_buy_go = True
                    if is_buy_go:
                        if is_no_way:
                            invest_go_money = ((remain_invest_money - kosdaq_sell_money_future) / len(InvestStockList))
                        else:
                            invest_go_money = (remain_invest_money - kosdaq_sell_money_future) * 0.5 if len(now_invest_list) + kosdaq_sell_cnt == 0 else (remain_invest_money - kosdaq_sell_money_future)
                        buy_amt = int(invest_go_money / buy_price)
                        now_fee = (buy_amt * buy_price) * fee
                        while (remain_invest_money - kosdaq_sell_money_future) < (buy_amt * buy_price) + now_fee:
                            if (remain_invest_money - kosdaq_sell_money_future) > buy_price:
                                buy_amt -= 1
                                now_fee = (buy_amt * buy_price) * fee
                            else:
                                break
                        if buy_amt > 0:
                            real_money = buy_amt * buy_price
                            remain_invest_money -= real_money
                            remain_invest_money -= now_fee
                            now_invest_list.append({'stock_code': stock_code, 'InvestMoney': real_money, 'FirstMoney': real_money, 'BuyPrice': buy_price, 'DolPaCheck': False, 'Date': str(date_object.date())})
                            trades.append({
                                'date': str(date_object.date()),
                                'code': stock_code,
                                'name': stock_name(stock_code),
                                'action': 'BUY',
                                'buy_price': buy_price,
                                'amount_est': buy_amt,
                            })

        if len(now_invest_list) < int(len(InvestStockList)) / 2 and int(date_object.strftime("%Y")) >= StartYear:
            for stock_code in all_stocks.index:
                already = any(stock_code == inv['stock_code'] for inv in now_invest_list)
                if stock_code in today_sell_code or already:
                    continue
                stock_data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
                row = stock_data.iloc[0]
                if stock_code not in ["233740", "251340"]:
                    continue
                prev_close = row['prevClose']
                dolpa_rate = 0.4 if stock_code == "251340" else (0.3 if prev_close > row['ma60_before'] else 0.4)
                gap = (abs(row['open'] - prev_close) / prev_close) * 100.0
                gap_st = clamp(gap * 0.025, 0.1, 1.0)
                if prev_close > row['open'] and gap >= 3.0:
                    dolpa_rate *= (1.0 + gap_st)
                if prev_close < row['open'] and gap >= 3.0:
                    dolpa_rate *= (1.0 - gap_st)
                dolpa_price = row['open'] + ((row['prevHigh'] - row['prevLow']) * dolpa_rate)
                is_buy_go = False
                dolpa_rate_pct = (dolpa_price - row['open']) / row['open'] * 100
                if dolpa_price <= row['high']:
                    is_buy_go = True
                    if stock_code == "251340":
                        if row['prevClose'] <= row['ma20_before']:
                            is_buy_go = False
                    else:
                        if row['prevLow'] > row['open'] and row['prevClose'] < row['ma10_before']:
                            is_buy_go = False
                        if gap >= 4.5 and row['prevRSI'] >= 78 and dolpa_rate_pct >= 4.0:
                            is_buy_go = False
                    is_jung = row['ma10_before'] > row['ma20_before'] > row['ma60_before'] > row['ma120_before']
                    if not is_jung:
                        max_price = row['low_7_min'] + ((row['high_7_max'] - row['low_7_min']) / 4.0) * 3.0
                        if row['open'] > max_price:
                            is_buy_go = False
                if is_buy_go:
                    if row['prev_obv_ma2'] > row['prev_obv_ma'] and row['prev_obv'] < row['prev_obv_ma']:
                        is_buy_go = False
                if is_buy_go:
                    rate = 1.0
                    if len(kq_long) == 1 and len(kq_short) == 1:
                        long_strong = kq_long['Average_Momentum'].values[0] > kq_short['Average_Momentum'].values[0]
                        long_strong2 = kq_long['prevChangeMa'].values[0] > kq_short['prevChangeMa'].values[0]
                        if long_strong and long_strong2:
                            rate = 1.3 if stock_code == '233740' else 0.7
                        elif (not long_strong) and (not long_strong2):
                            rate = 0.7 if stock_code == '233740' else 1.3
                    adjust_rate = 1.0
                    if is_cut and is_cut_cnt >= 2:
                        if row['prevOpen'] > row['prevClose'] and row['prevHigh2'] > row['prevHigh']:
                            adjust_rate = row['Average_Momentum3'] * (0.5 if is_cut_cnt >= 4 else 1.0)
                    if is_no_way:
                        invest_go_money = ((remain_invest_money - kosdaq_sell_money_future) / len(InvestStockList)) * rate * adjust_rate
                    else:
                        invest_go_money = ((remain_invest_money - kosdaq_sell_money_future) * 0.5 if len(now_invest_list) + kosdaq_sell_cnt == 0 else (remain_invest_money - kosdaq_sell_money_future)) * rate * adjust_rate
                    if rate > 0 and adjust_rate > 0:
                        buy_amt = int(invest_go_money / dolpa_price)
                        now_fee = (buy_amt * dolpa_price) * fee
                        while (remain_invest_money - kosdaq_sell_money_future) < (buy_amt * dolpa_price) + now_fee:
                            if (remain_invest_money - kosdaq_sell_money_future) > dolpa_price:
                                buy_amt -= 1
                                now_fee = (buy_amt * dolpa_price) * fee
                            else:
                                break
                        if buy_amt > 0:
                            real_money = buy_amt * dolpa_price
                            remain_invest_money -= real_money
                            remain_invest_money -= now_fee
                            now_invest_list.append({'stock_code': stock_code, 'InvestMoney': real_money, 'FirstMoney': real_money, 'BuyPrice': dolpa_price, 'DolPaCheck': False, 'Date': str(date_object.date())})
                            trades.append({
                                'date': str(date_object.date()),
                                'code': stock_code,
                                'name': stock_name(stock_code),
                                'action': 'BUY',
                                'buy_price': round(float(dolpa_price), 2),
                                'amount_est': buy_amt,
                            })

        now_invest_money = sum(i['InvestMoney'] for i in now_invest_list)
        invest_money = remain_invest_money + now_invest_money

    return trades


def compare(actual_trades, bt_trades):
    print("최근 실거래 vs v7_best 백테스트 비교 (2026-03)\n")
    bt_march = [t for t in bt_trades if t['date'].startswith('2026-03')]

    print("[백테스트 이벤트]")
    for t in bt_march:
        if t['action'] == 'SELL':
            print(f"{t['date']} {t['code']} {t['action']} ret={t['ret']}% buy_date={t['buy_date']} buy_price={t['buy_price']} sell_price={round(float(t['sell_price']),2)}")
        else:
            print(f"{t['date']} {t['code']} {t['action']} buy_price={t['buy_price']} amount_est={t['amount_est']}")

    print("\n[실거래 이벤트]")
    for t in actual_trades:
        suffix = f" ret={t['ret']}%" if 'ret' in t else ""
        print(f"{t['date']} {t['code']} {t['action']}{suffix}")

    print("\n[매칭 요약]")
    used = set()
    for at in actual_trades:
        candidates = []
        for idx, bt in enumerate(bt_march):
            if idx in used:
                continue
            if bt['date'] == at['date'] and bt['code'] == at['code'] and bt['action'] == at['action']:
                candidates.append((idx, bt))
        if candidates:
            idx, bt = candidates[0]
            used.add(idx)
            if at['action'] == 'SELL':
                delta = None
                if 'ret' in at and 'ret' in bt:
                    delta = round(at['ret'] - bt['ret'], 2)
                print(f"MATCH {at['date']} {at['code']} {at['action']} | actual={at.get('ret')}% bt={bt.get('ret')}% delta={delta}")
            else:
                print(f"MATCH {at['date']} {at['code']} {at['action']} | bt_buy_price={bt.get('buy_price')}")
        else:
            print(f"MISS  {at['date']} {at['code']} {at['action']} | 백테스트 동일 이벤트 없음")

    print("\n[백테스트에만 있는 이벤트]")
    for idx, bt in enumerate(bt_march):
        if idx in used:
            continue
        if bt['action'] == 'SELL':
            print(f"BT_ONLY {bt['date']} {bt['code']} SELL ret={bt['ret']}% buy_date={bt['buy_date']}")
        else:
            print(f"BT_ONLY {bt['date']} {bt['code']} BUY buy_price={bt['buy_price']}")


if __name__ == '__main__':
    trades = simulate_trades()
    compare(ACTUAL_TRADES, trades)
