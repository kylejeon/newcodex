# -*- coding: utf-8 -*-
'''
Kosdaqpi daily-mode bot

- 백테스트(v7_best)에 더 가깝게 맞추기 위한 일봉형 실행 구조
- 장중 1분 재판단 없이 하루 1회만 판단
- 코스피: 시가형 판단 후 즉시 매수/매도
- 코스닥: 장 시작 후 돌파가/손절가를 계산해서 Stop 주문만 등록

주의:
- 코스닥 Stop 주문이 실제로 체결되려면 KIS_KR_StopTrader_System 이 별도로 실행 중이어야 합니다.
- CLOSE 기반 컷매도는 실시간 장중에서 완벽히 재현할 수 없으므로, 일봉형 운영에서는 StopLoss 근사로 처리합니다.
'''

import json
import os
import pprint
import time
from datetime import datetime

import numpy as np
import pandas as pd

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR
import KIS_KR_StopTrader
import telegram_alert


Common.SetChangeMode("REAL")

InvestStockList = ["122630", "252670", "233740", "251340"]
InvestRate = 0.95  # KIS API의 실제 주문가능금액 기준으로 자동 조정 (StopTrader_System 의 adjustAmt=True 보호)
BOT_NAME = Common.GetNowDist() + "_MyKospidaq_Bot_Daily"
PortfolioName = "게만아 코스피닥 매매 전략!"

ENABLE_BOT_TRAILING_STOP = False
ENABLE_233740_HARD_STOP = True
HARD_STOP_233740_PCT_TIGHT = 0.085
HARD_STOP_233740_PCT_BASE = 0.125
HARD_STOP_VOL_TH = 0.045
ENABLE_122630_HARD_STOP = True
HARD_STOP_122630_PCT_TIGHT = 0.09
HARD_STOP_122630_PCT_BASE = 0.12
CLOSE_BASED_CUT_CODES = {"233740", "251340"}
KOSPI_252670_DISPARITY11_TH = 106
KOSPI_122630_DISPARITY_LOW = 98
KOSPI_122630_DISPARITY_HIGH = 105
KOSPI_252670_BUY_RSI_MAX = 70
KOSPI_122630_BUY_DISPARITY_LOW = 97
KOSPI_122630_BUY_DISPARITY_HIGH = 107
KOSPI_122630_BUY_RSI_MAX = 80

AUTOBOT_DATA_DIR = os.environ.get("AUTOBOT_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "autobot_data"))
os.makedirs(AUTOBOT_DATA_DIR, exist_ok=True)

state_file_path = os.path.join(AUTOBOT_DATA_DIR, "KrStock_" + BOT_NAME + "_State.json")
date_file_path = os.path.join(AUTOBOT_DATA_DIR, "KrStock_" + BOT_NAME + "_Date.json")
sold_today_file_path = os.path.join(AUTOBOT_DATA_DIR, "KrStock_" + BOT_NAME + "_SoldToday.json")


def get_strategy_data(stock_code, strategy_list):
    for data in strategy_list:
        if data['StockCode'] == stock_code:
            return data
    return None


def get_holding_info(my_stock_list, stock_code):
    for my_stock in my_stock_list:
        if my_stock.get('StockCode') == stock_code:
            return {
                'amt': int(my_stock.get('StockAmt', 0)),
                'avg': float(my_stock.get('StockAvgPrice', 0)),
                'revenue_rate': float(my_stock.get('StockRevenueRate', 0)),
                'revenue_money': float(my_stock.get('StockRevenueMoney', 0)),
                'name': my_stock.get('StockName', stock_code),
            }
    return {'amt': 0, 'avg': 0.0, 'revenue_rate': 0.0, 'revenue_money': 0.0, 'name': stock_code}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def calc_hold_days(curr_date, buy_date_str):
    try:
        buy_dt = pd.to_datetime(buy_date_str)
        cur_dt = pd.to_datetime(curr_date)
        return max(0, (cur_dt.normalize() - buy_dt.normalize()).days)
    except Exception:
        return 0


def is_order_accepted(order_data):
    return isinstance(order_data, dict) and order_data.get('OrderNum2') not in [None, "", "0"]


def parse_date(date):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(date), fmt)
        except Exception:
            pass
    raise ValueError(f"Unsupported date format: {date}")


def load_state():
    try:
        with open(state_file_path, 'r') as f:
            return json.load(f)
    except Exception:
        state = []
        for stock_code in InvestStockList:
            state.append({
                'StockCode': stock_code,
                'StockName': KisKR.GetStockName(stock_code),
                'Status': 'REST',
                'DayStatus': 'NONE',
                'TargetPrice': 0,
                'TryBuyCnt': 0,
                'BuyDate': '',
                'BuyPrice': 0,
            })
        return state


def _json_safe_value(value):
    if isinstance(value, dict):
        return {k: _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe_value(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def save_state(state):
    with open(state_file_path, 'w') as f:
        json.dump(_json_safe_value(state), f, ensure_ascii=False)


def load_date():
    try:
        with open(date_file_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {'Date': '00'}


def save_date(date_data):
    with open(date_file_path, 'w') as f:
        json.dump(_json_safe_value(date_data), f, ensure_ascii=False)


def load_sold_today():
    try:
        with open(sold_today_file_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {'Date': '', 'Tickers': []}


def save_sold_today(data):
    with open(sold_today_file_path, 'w') as f:
        json.dump(_json_safe_value(data), f, ensure_ascii=False)


def calc_regime_exposure(date_df, is_no_way):
    return 1.0, "OFF"


def build_daily_df(stock_code):
    df = Common.GetOhlcv("KR", stock_code, 220)
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
    gugan_lenth = 7
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


def main():
    time_info = time.gmtime()
    day_str = str(time_info.tm_mon) + "-" + str(time_info.tm_mday)
    print(day_str)

    if KisKR.IsMarketOpen() is not True:
        print("Market closed")
        return

    Balance = KisKR.GetBalance()
    MyStockList = KisKR.GetMyStockList()

    pprint.pprint(Balance)
    pprint.pprint(MyStockList)

    strategy_list = load_state()
    date_data = load_date()
    sold_today_data = load_sold_today()
    if sold_today_data.get('Date') != day_str:
        sold_today_data = {'Date': day_str, 'Tickers': []}
        save_sold_today(sold_today_data)

    stock_df_list = []
    for stock_code in InvestStockList:
        df = build_daily_df(stock_code)
        stock_df_list.append({stock_code: df})
        print("---stock_code---", stock_code, " len ", len(df))

    combined_df = pd.concat([list(data.values())[0].assign(stock_code=code) for data in stock_df_list for code in data])
    combined_df.sort_index(inplace=True)
    print(" len(combined_df) ", len(combined_df))

    date = combined_df.iloc[-1].name
    date_object = parse_date(date)
    if date_object.weekday() != time_info.tm_wday:
        print("latest daily bar weekday mismatch, skip")
        return

    if date_data.get('Date') == day_str:
        print("already evaluated today")
        return

    telegram_alert.SendMessage(PortfolioName + "  장이 열려서 매매 가능!!")

    # stale stop orders reset
    for stock_code in InvestStockList:
        try:
            KIS_KR_StopTrader.CancelOrderByTicker(stock_code, "StopBuy", with_limit_orders=False)
        except Exception:
            pass
        try:
            KIS_KR_StopTrader.CancelOrderByTicker(stock_code, "StopLoss", with_limit_orders=False)
        except Exception:
            pass

    all_stocks = combined_df.loc[combined_df.index == date].groupby('stock_code')['close'].max().nlargest(len(InvestStockList))
    day_df = combined_df.loc[combined_df.index == date]
    kq_long = day_df[day_df['stock_code'] == "233740"]
    kq_short = day_df[day_df['stock_code'] == "251340"]
    kp_long = day_df[day_df['stock_code'] == "122630"]
    kp_short = day_df[day_df['stock_code'] == "252670"]

    is_no_way = False
    if (
        (kp_long['prevChangeMa_S'].values[0] > 0 and kp_short['prevChangeMa_S'].values[0] > 0)
        or (kp_long['prevChangeMa_S'].values[0] < 0 and kp_short['prevChangeMa_S'].values[0] < 0)
        or (kq_long['prevChangeMa_S'].values[0] > 0 and kq_short['prevChangeMa_S'].values[0] > 0)
        or (kq_long['prevChangeMa_S'].values[0] < 0 and kq_short['prevChangeMa_S'].values[0] < 0)
    ):
        is_no_way = True

    total_exposure, _ = calc_regime_exposure(day_df, is_no_way)

    total_money = float(Balance['TotalMoney']) * InvestRate
    now_invest_money = 0.0
    for stock_code in InvestStockList:
        info = get_holding_info(MyStockList, stock_code)
        now_invest_money += info['amt'] * info['avg']
    remain_invest_money = total_money - now_invest_money

    # sync holdings
    for stock_code in InvestStockList:
        data = get_strategy_data(stock_code, strategy_list)
        hold = get_holding_info(MyStockList, stock_code)
        data['DayStatus'] = "NONE"
        if hold['amt'] > 0:
            data['Status'] = "INVESTING"
            data['DayStatus'] = "SELL_DAY"
            msg = data['StockName'] + "  투자중 상태에요! 조건을 만족하면 매도로 트레이딩 종료 합니다.!!"
            print(msg)
            telegram_alert.SendMessage(msg)
        else:
            data['Status'] = "REST"
            data['TryBuyCnt'] = 0
            data['TargetPrice'] = 0

    today_sell_code = []
    kosdaq_sell_cnt = 0
    sold_today_set = set(sold_today_data.get('Tickers', []))

    # sell pass
    for stock_code in InvestStockList:
        row = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
        data = get_strategy_data(stock_code, strategy_list)
        hold = get_holding_info(MyStockList, stock_code)
        if hold['amt'] <= 0:
            continue

        if stock_code in ["233740", "251340"]:
            prev_close = row['prevClose'].values[0]
            cut_rate = 0.35 if stock_code == "251340" else (0.35 if prev_close > row['ma60_before'].values[0] else 0.25)
            cut_price = row['open'].values[0] - ((row['prevHigh'].values[0] - row['prevLow'].values[0]) * cut_rate)

            hard_stop_price = 0.0
            if ENABLE_233740_HARD_STOP and stock_code == "233740":
                prev_range_ratio = (row['prevHigh'].values[0] - row['prevLow'].values[0]) / row['prevClose'].values[0]
                weak_trend = row['prevClose'].values[0] <= row['ma20_before'].values[0]
                is_high_vol = prev_range_ratio >= HARD_STOP_VOL_TH
                hard_stop_pct = HARD_STOP_233740_PCT_TIGHT if (weak_trend and is_high_vol) else HARD_STOP_233740_PCT_BASE
                hard_stop_price = hold['avg'] * (1.0 - hard_stop_pct)

            stop_price = max(cut_price, hard_stop_price)
            if stop_price > 0:
                try:
                    KIS_KR_StopTrader.MakeStopLoss(stock_code, stop_price, Exclusive=True)
                    msg = data['StockName'] + " 일봉형 손절 주문 등록 완료. 기준가: " + str(round(stop_price, 2))
                    print(msg)
                    telegram_alert.SendMessage(msg)
                except Exception as e:
                    msg = data['StockName'] + " 일봉형 손절 주문 등록 실패: " + str(e)
                    print(msg)
                    telegram_alert.SendMessage(msg)
            continue

        # kospi daily sell at open
        prev_close = row['prevClose'].values[0]
        is_sell_go = False
        if stock_code == "252670":
            if row['Disparity11'].values[0] > KOSPI_252670_DISPARITY11_TH:
                if prev_close < row['ma3_before'].values[0]:
                    is_sell_go = True
            else:
                if prev_close < row['ma6_before'].values[0] and prev_close < row['ma19_before'].values[0]:
                    is_sell_go = True
        else:
            total_volume = (row['prevVolume'].values[0] + row['prevVolume2'].values[0] + row['prevVolume3'].values[0]) / 3.0
            disparity = row['Disparity20'].values[0]
            if not ((row['prevLow2'].values[0] < row['prevLow'].values[0] or row['prevVolume'].values[0] < total_volume) and (disparity < KOSPI_122630_DISPARITY_LOW or disparity > KOSPI_122630_DISPARITY_HIGH)):
                is_sell_go = True

        if is_sell_go:
            pprint.pprint(KisKR.MakeSellMarketOrder(stock_code, hold['amt']))
            data['Status'] = "SELL_DONE_CHECK"
            today_sell_code.append(stock_code)
            sold_today_set.add(stock_code)
            try:
                KIS_KR_StopTrader.CancelOrderByTicker(stock_code, "StopBuy", with_limit_orders=False)
            except Exception:
                pass
            msg = data['StockName'] + " 일봉형 매도조건 충족! 시가 매도 주문 전송."
            print(msg)
            telegram_alert.SendMessage(msg)
            kosdaq_sell_cnt += 1
        else:
            # 122630 하드스탑: 보류 시 장중 하드스탑을 StopTrader 에 등록
            if ENABLE_122630_HARD_STOP and stock_code == "122630" and hold['avg'] > 0:
                prev_range_ratio = (row['prevHigh'].values[0] - row['prevLow'].values[0]) / row['prevClose'].values[0]
                weak_trend = row['prevClose'].values[0] <= row['ma20_before'].values[0]
                is_high_vol = prev_range_ratio >= HARD_STOP_VOL_TH
                hard_stop_pct = HARD_STOP_122630_PCT_TIGHT if (weak_trend and is_high_vol) else HARD_STOP_122630_PCT_BASE
                hard_stop_price = hold['avg'] * (1.0 - hard_stop_pct)
                try:
                    KIS_KR_StopTrader.MakeStopLoss(stock_code, hard_stop_price, Exclusive=True)
                    msg = data['StockName'] + " 일봉형 하드스탑 등록 완료. 기준가: " + str(round(hard_stop_price, 2))
                    print(msg)
                    telegram_alert.SendMessage(msg)
                except Exception as e:
                    msg = data['StockName'] + " 일봉형 하드스탑 등록 실패: " + str(e)
                    print(msg)
                    telegram_alert.SendMessage(msg)
            msg = data['StockName'] + " 매도 보류(코스피): 홀드조건 충족"
            print(msg)
            telegram_alert.SendMessage(msg)

    # buy pass
    invest_cnt = sum(1 for code in InvestStockList if get_holding_info(MyStockList, code)['amt'] > 0)

    for stock_code in all_stocks.index:
        if invest_cnt >= 2:
            break
        if stock_code in today_sell_code:
            continue
        if stock_code in sold_today_set:
            data = get_strategy_data(stock_code, strategy_list)
            msg = data['StockName'] + " 금일 매도 이력이 있어 재진입을 금지합니다."
            print(msg)
            telegram_alert.SendMessage(msg)
            continue

        row = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
        data = get_strategy_data(stock_code, strategy_list)
        hold = get_holding_info(MyStockList, stock_code)
        if hold['amt'] > 0:
            continue

        if stock_code in ["122630", "252670"]:
            is_buy_go = False
            if stock_code == "252670":
                prev_close = row['prevClose'].values[0]
                if prev_close > row['ma3_before'].values[0] and prev_close > row['ma6_before'].values[0] and prev_close > row['ma19_before'].values[0] and row['prevRSI'].values[0] < KOSPI_252670_BUY_RSI_MAX and row['prevRSI2'].values[0] < row['prevRSI'].values[0]:
                    if row['prevVolume2'].values[0] < row['prevVolume'].values[0] and row['prevLow2'].values[0] < row['prevLow'].values[0] and prev_close > row['ma60_before'].values[0] and row['ma60_before2'].values[0] < row['ma60_before'].values[0] and row['ma3_before'].values[0] > row['ma6_before'].values[0] > row['ma19_before'].values[0]:
                        is_buy_go = True
            else:
                disparity = row['Disparity20'].values[0]
                if row['prevLow2'].values[0] < row['prevLow'].values[0] and (disparity < KOSPI_122630_BUY_DISPARITY_LOW or disparity > KOSPI_122630_BUY_DISPARITY_HIGH) and row['prevRSI'].values[0] < KOSPI_122630_BUY_RSI_MAX:
                    is_buy_go = True

            if is_buy_go:
                invest_go_money = (remain_invest_money * 0.5 * total_exposure) if invest_cnt == 0 else (remain_invest_money * total_exposure)
                buy_price = row['open'].values[0]
                buy_amt = int(invest_go_money / buy_price)
                while buy_amt > 0 and remain_invest_money < (buy_amt * buy_price * 1.0015):
                    buy_amt -= 1
                if buy_amt > 0:
                    order_data = KisKR.MakeBuyMarketOrder(stock_code, buy_amt, True)
                    pprint.pprint(order_data)
                    if is_order_accepted(order_data):
                        data['Status'] = "INVESTING_TRY"
                        data['DayStatus'] = "BUY_DAY"
                        data['TryBuyCnt'] = buy_amt
                        data['BuyDate'] = str(date)
                        data['BuyPrice'] = buy_price
                        msg = data['StockName'] + " 일봉형 시가매수 주문 전송 완료."
                        print(msg)
                        telegram_alert.SendMessage(msg)
                        invest_cnt += 1
                        remain_invest_money -= buy_amt * buy_price * 1.0015
                    else:
                        msg = data['StockName'] + " 일봉형 시가매수 주문 실패."
                        print(msg)
                        telegram_alert.SendMessage(msg)
            else:
                msg = data['StockName'] + "  조건을 불만족하여 오늘 시가매수는 쉽니다!!!"
                print(msg)
                telegram_alert.SendMessage(msg)

        else:
            prev_close = row['prevClose'].values[0]
            dolpa_rate = 0.4 if stock_code == "251340" else (0.3 if prev_close > row['ma60_before'].values[0] else 0.4)
            gap = (abs(row['open'].values[0] - prev_close) / prev_close) * 100.0
            gap_st = clamp(gap * 0.025, 0.1, 1.0)
            if prev_close > row['open'].values[0] and gap >= 3.0:
                dolpa_rate *= (1.0 + gap_st)
            if prev_close < row['open'].values[0] and gap >= 3.0:
                dolpa_rate *= (1.0 - gap_st)
            target_price = row['open'].values[0] + ((row['prevHigh'].values[0] - row['prevLow'].values[0]) * dolpa_rate)

            is_buy_ready = True
            if stock_code == "251340":
                if row['prevClose'].values[0] <= row['ma20_before'].values[0]:
                    is_buy_ready = False
            else:
                if row['prevLow'].values[0] > row['open'].values[0] and row['prevClose'].values[0] < row['ma10_before'].values[0]:
                    is_buy_ready = False
                dolpa_rate_pct = (target_price - row['open'].values[0]) / row['open'].values[0] * 100.0
                if gap >= 4.5 and row['prevRSI'].values[0] >= 78 and dolpa_rate_pct >= 4.0:
                    is_buy_ready = False

            is_jung = row['ma10_before'].values[0] > row['ma20_before'].values[0] > row['ma60_before'].values[0] > row['ma120_before'].values[0]
            if not is_jung:
                high_price = row['high_7_max'].values[0]
                low_price = row['low_7_min'].values[0]
                max_price = low_price + ((high_price - low_price) / 4.0) * 3.0
                if row['open'].values[0] > max_price:
                    is_buy_ready = False

            if is_buy_ready and row['prev_obv_ma2'].values[0] > row['prev_obv_ma'].values[0] and row['prev_obv'].values[0] < row['prev_obv_ma'].values[0]:
                is_buy_ready = False

            if is_buy_ready:
                rate = 1.0
                if kq_long['Average_Momentum'].values[0] > kq_short['Average_Momentum'].values[0] and kq_long['prevChangeMa'].values[0] > kq_short['prevChangeMa'].values[0]:
                    rate = 1.3 if stock_code == "233740" else 0.7
                elif kq_long['Average_Momentum'].values[0] <= kq_short['Average_Momentum'].values[0] and kq_long['prevChangeMa'].values[0] <= kq_short['prevChangeMa'].values[0]:
                    rate = 0.7 if stock_code == "233740" else 1.3

                adjust_rate = 1.0
                invest_go_money = ((remain_invest_money / len(InvestStockList)) if is_no_way else ((remain_invest_money * 0.5) if invest_cnt == 0 else remain_invest_money)) * rate * adjust_rate * total_exposure
                buy_amt = int(invest_go_money / target_price)
                while buy_amt > 0 and remain_invest_money < (buy_amt * target_price * 1.0015):
                    buy_amt -= 1
                if buy_amt > 0:
                    KIS_KR_StopTrader.MakeStopBuyOrder(stock_code, buy_amt, target_price, Exclusive=True)
                    data['Status'] = "READY"
                    data['DayStatus'] = "BUY_DAY"
                    data['TargetPrice'] = float(target_price)
                    data['TryBuyCnt'] = buy_amt
                    msg = data['StockName'] + " 일봉형 돌파매수 주문 등록 완료. 목표가: " + str(round(target_price, 2))
                    print(msg)
                    telegram_alert.SendMessage(msg)
                else:
                    msg = data['StockName'] + " 일봉형 돌파매수 수량이 0주라 주문하지 않습니다."
                    print(msg)
                    telegram_alert.SendMessage(msg)
            else:
                data['Status'] = "REST"
                data['DayStatus'] = "NONE"
                msg = data['StockName'] + "  조건을 불만족하여 오늘 돌파매수는 쉽니다!!!"
                print(msg)
                telegram_alert.SendMessage(msg)

    date_data['Date'] = day_str
    sold_today_data['Date'] = day_str
    sold_today_data['Tickers'] = sorted(sold_today_set)
    save_state(strategy_list)
    save_date(date_data)
    save_sold_today(sold_today_data)
    pprint.pprint(strategy_list)


if __name__ == "__main__":
    main()
