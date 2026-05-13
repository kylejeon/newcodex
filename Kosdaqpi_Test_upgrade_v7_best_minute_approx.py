# -*- coding: utf-8 -*-
'''
Kosdaqpi v7 best - 1분봉 근사 백테스트

- 일봉 지표/신호는 기존 v7_best와 동일하게 계산
- 실제 체결은 일봉 OHLC를 이용해 장중 1분 가격 경로를 근사 생성하여 처리
- 코스피: 시가 진입/시가 청산 유지
- 코스닥: 돌파 시점/하드스탑을 분 단위 경로에서 체결

주의:
- 실제 1분봉 데이터가 아니라 OHLC 기반 synthetic minute path 이므로 "근사 백테스트"입니다.
- 특히 고가/저가 발생 순서는 캔들 방향에 따라 추정합니다.
'''

import math
from datetime import datetime

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pprint

Common.SetChangeMode("REAL")

InvestStockList = ["122630", "252670", "233740", "251340"]
TotalMoney = 10000000
fee = 0.0015
StartYear = 2017
EndYear = 2099

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

ENABLE_REGIME_OVERLAY = False
ENABLE_DD_GUARD = False
SPREAD_CHOP_TH = 0.0045
EXPOSURE_BULL = 1.00
EXPOSURE_NEUTRAL = 1.00
EXPOSURE_BEAR = 1.00
EXPOSURE_CHOP = 1.00
DD_GUARD_1 = -0.12
DD_GUARD_2 = -0.20
DD_GUARD_3 = -0.26
DD_EXPO_1 = 0.94
DD_EXPO_2 = 0.84
DD_EXPO_3 = 0.74
MIN_TOTAL_EXPOSURE = 1.00
MAX_TOTAL_EXPOSURE = 1.00

print("테스트하는 총 금액: ", format(round(TotalMoney), ','))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def calc_hold_days(curr_date, buy_date_str):
    try:
        buy_dt = pd.to_datetime(buy_date_str)
        cur_dt = pd.to_datetime(curr_date)
        return max(0, (cur_dt.normalize() - buy_dt.normalize()).days)
    except Exception:
        return 0


def get_row(date_df, code):
    row = date_df[date_df['stock_code'] == code]
    if len(row) != 1:
        return None
    return row.iloc[0]


def calc_regime_exposure(date_df, is_no_way):
    if ENABLE_REGIME_OVERLAY is False:
        return 1.0, "OFF"

    kospi_l = get_row(date_df, "122630")
    kospi_s = get_row(date_df, "252670")
    kosdaq_l = get_row(date_df, "233740")
    kosdaq_s = get_row(date_df, "251340")
    if any(x is None for x in [kospi_l, kospi_s, kosdaq_l, kosdaq_s]):
        return 1.0, "NA"

    spread_kospi = float(kospi_l['prevChangeMa']) - float(kospi_s['prevChangeMa'])
    spread_kosdaq = float(kosdaq_l['prevChangeMa']) - float(kosdaq_s['prevChangeMa'])
    kospi_bull = float(kospi_l['prevClose']) > float(kospi_l['ma60_before'])
    kosdaq_bull = float(kosdaq_l['prevClose']) > float(kosdaq_l['ma60_before'])
    kospi_bear = float(kospi_l['prevClose']) < float(kospi_l['ma60_before'])
    kosdaq_bear = float(kosdaq_l['prevClose']) < float(kosdaq_l['ma60_before'])

    is_chop = is_no_way or (abs(spread_kospi) < SPREAD_CHOP_TH and abs(spread_kosdaq) < SPREAD_CHOP_TH)
    if is_chop:
        return EXPOSURE_CHOP, "CHOP"
    if spread_kospi > 0 and spread_kosdaq > 0 and kospi_bull and kosdaq_bull:
        return EXPOSURE_BULL, "BULL"
    if spread_kospi < 0 and spread_kosdaq < 0 and kospi_bear and kosdaq_bear:
        return EXPOSURE_BEAR, "BEAR"
    return EXPOSURE_NEUTRAL, "NEUTRAL"


def build_intraday_path(row, minutes=390):
    o = float(row['open'])
    h = float(row['high'])
    l = float(row['low'])
    c = float(row['close'])
    if c >= o:
        anchors = [(0, o), (80, l), (250, h), (minutes - 1, c)]
    else:
        anchors = [(0, o), (80, h), (250, l), (minutes - 1, c)]

    path = np.zeros(minutes, dtype=float)
    for (m1, p1), (m2, p2) in zip(anchors[:-1], anchors[1:]):
        if m2 == m1:
            path[m1] = p1
            continue
        for m in range(m1, m2 + 1):
            t = (m - m1) / (m2 - m1)
            path[m] = p1 + (p2 - p1) * t
    path[0] = o
    path[-1] = c
    path = np.clip(path, l, h)
    return path


def first_cross_up(path, target):
    idx = np.where(path >= target)[0]
    if len(idx) == 0:
        return None
    return int(idx[0])


def first_cross_down(path, target):
    idx = np.where(path <= target)[0]
    if len(idx) == 0:
        return None
    return int(idx[0])


def load_stock_df(stock_code):
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


stock_df_list = []
StockDataList = []
for stock_code in InvestStockList:
    StockDataList.append({
        'stock_code': stock_code,
        'stock_name': KisKR.GetStockName(stock_code),
        'try': 0,
        'success': 0,
        'fail': 0,
        'accRev': 0.0,
    })
    df = load_stock_df(stock_code)
    stock_df_list.append({stock_code: df})
    print("---stock_code---", stock_code, " len ", len(df))

combined_df = pd.concat([list(data.values())[0].assign(stock_code=code) for data in stock_df_list for code in data])
combined_df.sort_index(inplace=True)
print(" len(combined_df) ", len(combined_df))


def stock_name(code):
    for row in StockDataList:
        if row['stock_code'] == code:
            return row['stock_name']
    return code


cash = TotalMoney
positions = []
TotalMoneyList = []
TryCnt = SuccesCnt = FailCnt = 0
IsCut = False
IsCutCnt = 0
PeakEquity = TotalMoney
FirstDateStr = ""
FirstDateSet = False
DivNum = len(InvestStockList)


def portfolio_value(day_rows):
    total = cash
    for pos in positions:
        row = get_row(day_rows, pos['stock_code'])
        if row is not None:
            total += pos['qty'] * float(row['close'])
    return total


for i, date in enumerate(combined_df.index.unique(), start=1):
    date_object = pd.to_datetime(date)
    year = int(date_object.strftime("%Y"))
    if year < StartYear or year > EndYear:
        continue

    day_df = combined_df.loc[combined_df.index == date]
    all_stocks = day_df.groupby('stock_code')['close'].max().nlargest(DivNum)
    paths = {code: build_intraday_path(get_row(day_df, code)) for code in InvestStockList}

    kq_long = get_row(day_df, "233740")
    kq_short = get_row(day_df, "251340")
    kp_long = get_row(day_df, "122630")
    kp_short = get_row(day_df, "252670")
    IsNoWay = False
    if all(x is not None for x in [kp_long, kp_short, kq_long, kq_short]):
        if (
            (kp_long['prevChangeMa_S'] > 0 and kp_short['prevChangeMa_S'] > 0)
            or (kp_long['prevChangeMa_S'] < 0 and kp_short['prevChangeMa_S'] < 0)
            or (kq_long['prevChangeMa_S'] > 0 and kq_short['prevChangeMa_S'] > 0)
            or (kq_long['prevChangeMa_S'] < 0 and kq_short['prevChangeMa_S'] < 0)
        ):
            IsNoWay = True
    regime_exposure, _ = calc_regime_exposure(day_df, IsNoWay)

    equity = cash + sum(pos['qty'] * float(get_row(day_df, pos['stock_code'])['open']) for pos in positions)
    PeakEquity = max(PeakEquity, equity)
    cur_dd = (equity / PeakEquity) - 1.0 if PeakEquity > 0 else 0.0
    dd_exposure = 1.0
    if ENABLE_DD_GUARD:
        if cur_dd <= DD_GUARD_3:
            dd_exposure = DD_EXPO_3
        elif cur_dd <= DD_GUARD_2:
            dd_exposure = DD_EXPO_2
        elif cur_dd <= DD_GUARD_1:
            dd_exposure = DD_EXPO_1
    total_exposure = clamp(regime_exposure * dd_exposure, MIN_TOTAL_EXPOSURE, MAX_TOTAL_EXPOSURE)

    today_sell_code = []
    kosdaq_sell_cnt = 0
    kosdaq_sell_money_future = 0.0

    remaining_positions = []
    for pos in positions:
        code = pos['stock_code']
        row = get_row(day_df, code)
        path = paths[code]
        sell_price = None
        is_sell = False

        if code in ["233740", "251340"]:
            prev_close = float(row['prevClose'])
            cut_rate = 0.35 if code == "251340" else (0.35 if prev_close > float(row['ma60_before']) else 0.25)
            cut_price = float(row['open']) - ((float(row['prevHigh']) - float(row['prevLow'])) * cut_rate)

            if code in CLOSE_BASED_CUT_CODES:
                if float(row['close']) <= cut_price:
                    is_sell = True
                    sell_price = float(row['close'])
            else:
                down_idx = first_cross_down(path, cut_price)
                if down_idx is not None:
                    is_sell = True
                    sell_price = cut_price

            if ENABLE_233740_HARD_STOP and code == "233740":
                prev_range_ratio = (float(row['prevHigh']) - float(row['prevLow'])) / float(row['prevClose'])
                weak_trend = float(row['prevClose']) <= float(row['ma20_before'])
                is_high_vol = prev_range_ratio >= HARD_STOP_VOL_TH
                hard_stop_pct = HARD_STOP_233740_PCT_TIGHT if (weak_trend and is_high_vol) else HARD_STOP_233740_PCT_BASE
                hard_stop_price = pos['buy_price'] * (1.0 - hard_stop_pct)
                down_idx = first_cross_down(path, hard_stop_price)
                if down_idx is not None:
                    is_sell = True
                    sell_price = hard_stop_price

            if is_sell:
                kosdaq_sell_cnt += 1
                gross = pos['qty'] * sell_price
                net = gross * (1.0 - fee)
                cash += net
                revenue_rate = ((sell_price * (1.0 - fee) - pos['buy_price']) / pos['buy_price'] - fee) * 100.0
                TryCnt += 1
                if revenue_rate > 0:
                    SuccesCnt += 1
                else:
                    FailCnt += 1
                    IsCut = True
                    IsCutCnt += 1
                for sd in StockDataList:
                    if sd['stock_code'] == code:
                        sd['try'] += 1
                        sd['success'] += 1 if revenue_rate > 0 else 0
                        sd['fail'] += 0 if revenue_rate > 0 else 1
                        sd['accRev'] += revenue_rate
                today_sell_code.append(code)
                print(stock_name(code), "(", code, ")", str(date), i, ">>>>>>>>>>>>>>> 매도!", "수익률:", round(revenue_rate, 2), "%", "매도가", round(sell_price * (1.0 - fee), 2))
            else:
                remaining_positions.append(pos)

        else:
            prev_close = float(row['prevClose'])
            hold_days = calc_hold_days(date, pos['date'])
            is_sell_go = False
            if code == "252670":
                if float(row['Disparity11']) > KOSPI_252670_DISPARITY11_TH:
                    if prev_close < float(row['ma3_before']):
                        is_sell_go = True
                else:
                    if prev_close < float(row['ma6_before']) and prev_close < float(row['ma19_before']):
                        is_sell_go = True
            else:
                total_volume = (float(row['prevVolume']) + float(row['prevVolume2']) + float(row['prevVolume3'])) / 3.0
                disparity = float(row['Disparity20'])
                if not ((float(row['prevLow2']) < float(row['prevLow']) or float(row['prevVolume']) < total_volume) and (disparity < KOSPI_122630_DISPARITY_LOW or disparity > KOSPI_122630_DISPARITY_HIGH)):
                    is_sell_go = True
            if KOSPI_MIN_HOLD_DAYS > 0 and hold_days < KOSPI_MIN_HOLD_DAYS:
                is_sell_go = False

            if is_sell_go:
                sell_price = float(row['open'])
                gross = pos['qty'] * sell_price
                net = gross * (1.0 - fee)
                cash += net
                revenue_rate = ((sell_price * (1.0 - fee) - pos['buy_price']) / pos['buy_price'] - fee) * 100.0
                TryCnt += 1
                if revenue_rate > 0:
                    SuccesCnt += 1
                else:
                    FailCnt += 1
                for sd in StockDataList:
                    if sd['stock_code'] == code:
                        sd['try'] += 1
                        sd['success'] += 1 if revenue_rate > 0 else 0
                        sd['fail'] += 0 if revenue_rate > 0 else 1
                        sd['accRev'] += revenue_rate
                today_sell_code.append(code)
                print(stock_name(code), "(", code, ")", str(date), i, ">>>>>>>>>>>>>>> 매도!", "수익률:", round(revenue_rate, 2), "%", "매도가", round(sell_price * (1.0 - fee), 2))
            else:
                remaining_positions.append(pos)

    positions = remaining_positions

    if len(positions) < int(DivNum) / 2 and year >= StartYear:
        if not FirstDateSet:
            FirstDateStr = str(date)
            FirstDateSet = True

        for code in all_stocks.index:
            if len(positions) >= int(DivNum) / 2:
                break
            if code in today_sell_code or any(p['stock_code'] == code for p in positions):
                continue
            row = get_row(day_df, code)
            if code not in ["122630", "252670"]:
                continue

            is_buy_go = False
            buy_price = float(row['open'])
            prev_close = float(row['prevClose'])

            if code == "252670":
                if (
                    prev_close > float(row['ma3_before'])
                    and prev_close > float(row['ma6_before'])
                    and prev_close > float(row['ma19_before'])
                    and float(row['prevRSI']) < KOSPI_252670_BUY_RSI_MAX
                    and float(row['prevRSI2']) < float(row['prevRSI'])
                ):
                    if (
                        float(row['prevVolume2']) < float(row['prevVolume'])
                        and float(row['prevLow2']) < float(row['prevLow'])
                        and prev_close > float(row['ma60_before'])
                        and float(row['ma60_before2']) < float(row['ma60_before'])
                        and float(row['ma3_before']) > float(row['ma6_before']) > float(row['ma19_before'])
                    ):
                        is_buy_go = True
            else:
                disparity = float(row['Disparity20'])
                if float(row['prevLow2']) < float(row['prevLow']) and (disparity < KOSPI_122630_BUY_DISPARITY_LOW or disparity > KOSPI_122630_BUY_DISPARITY_HIGH) and float(row['prevRSI']) < KOSPI_122630_BUY_RSI_MAX:
                    is_buy_go = True

            if is_buy_go:
                if IsNoWay:
                    invest_go_money = (cash / len(InvestStockList)) * total_exposure
                else:
                    invest_go_money = (cash * 0.5 * total_exposure) if len(positions) == 0 else (cash * total_exposure)
                qty = int(invest_go_money / buy_price)
                while qty > 0 and cash < qty * buy_price * (1.0 + fee):
                    qty -= 1
                if qty > 0:
                    real_buy = qty * buy_price
                    cash -= real_buy * (1.0 + fee)
                    positions.append({'stock_code': code, 'qty': qty, 'buy_price': buy_price, 'date': str(date)})
                    print(stock_name(code), "(", code, ")", str(date), i, ">>>>>>>>>>>>>>> 매수!", "매수금액:", round(real_buy, 2), "매수가:", buy_price)

    if len(positions) < int(DivNum) / 2 and year >= StartYear:
        for code in all_stocks.index:
            if len(positions) >= int(DivNum) / 2:
                break
            if code in today_sell_code or any(p['stock_code'] == code for p in positions):
                continue
            if code not in ["233740", "251340"]:
                continue

            row = get_row(day_df, code)
            path = paths[code]
            prev_close = float(row['prevClose'])
            dolpa_rate = 0.4 if code == "251340" else (0.3 if prev_close > float(row['ma60_before']) else 0.4)
            gap = (abs(float(row['open']) - prev_close) / prev_close) * 100.0
            gap_st = min(max(gap * 0.025, 0.1), 1.0)
            if prev_close > float(row['open']) and gap >= 3.0:
                dolpa_rate *= (1.0 + gap_st)
            if prev_close < float(row['open']) and gap >= 3.0:
                dolpa_rate *= (1.0 - gap_st)
            dolpa_price = float(row['open']) + ((float(row['prevHigh']) - float(row['prevLow'])) * dolpa_rate)
            dolpa_idx = first_cross_up(path, dolpa_price)
            if dolpa_idx is None:
                continue

            is_buy_go = True
            dolpa_rate_pct = (dolpa_price - float(row['open'])) / float(row['open']) * 100.0
            if code == "251340":
                if float(row['prevClose']) <= float(row['ma20_before']):
                    is_buy_go = False
            else:
                if float(row['prevLow']) > float(row['open']) and float(row['prevClose']) < float(row['ma10_before']):
                    is_buy_go = False
                if gap >= 4.5 and float(row['prevRSI']) >= 78 and dolpa_rate_pct >= 4.0:
                    is_buy_go = False

            is_jung = float(row['ma10_before']) > float(row['ma20_before']) > float(row['ma60_before']) > float(row['ma120_before'])
            if not is_jung:
                high_price = float(row['high_7_max'])
                low_price = float(row['low_7_min'])
                max_price = low_price + ((high_price - low_price) / 4.0) * 3.0
                if float(row['open']) > max_price:
                    is_buy_go = False
            if is_buy_go and float(row['prev_obv_ma2']) > float(row['prev_obv_ma']) and float(row['prev_obv']) < float(row['prev_obv_ma']):
                is_buy_go = False
            if not is_buy_go:
                continue

            rate = 1.0
            if float(kq_long['Average_Momentum']) > float(kq_short['Average_Momentum']) and float(kq_long['prevChangeMa']) > float(kq_short['prevChangeMa']):
                rate = 1.3 if code == "233740" else 0.7
            elif float(kq_long['Average_Momentum']) <= float(kq_short['Average_Momentum']) and float(kq_long['prevChangeMa']) <= float(kq_short['prevChangeMa']):
                rate = 0.7 if code == "233740" else 1.3

            adjust_rate = 1.0
            if IsCut and IsCutCnt >= 2:
                if float(row['prevOpen']) > float(row['prevClose']) and float(row['prevHigh2']) > float(row['prevHigh']):
                    adjust_rate = float(row['Average_Momentum3']) * (0.5 if IsCutCnt >= 4 else 1.0)

            if IsNoWay:
                invest_go_money = (cash / len(InvestStockList)) * rate * adjust_rate * total_exposure
            else:
                invest_go_money = (cash * 0.5 * rate * adjust_rate * total_exposure) if len(positions) == 0 else (cash * rate * adjust_rate * total_exposure)

            qty = int(invest_go_money / dolpa_price)
            while qty > 0 and cash < qty * dolpa_price * (1.0 + fee):
                qty -= 1
            if qty > 0 and rate > 0 and adjust_rate > 0:
                real_buy = qty * dolpa_price
                cash -= real_buy * (1.0 + fee)
                positions.append({'stock_code': code, 'qty': qty, 'buy_price': dolpa_price, 'date': str(date)})
                print(stock_name(code), "(", code, ")", str(date), i, ">>>>>>>>>>>>>>> 매수!", "매수금액:", round(real_buy, 2), "돌파가격", round(dolpa_price, 2), "체결분:", dolpa_idx)

    invest_money = portfolio_value(day_df)
    TotalMoneyList.append(invest_money)
    invest_list_str = " ".join([stock_name(p['stock_code']) for p in positions])
    print("\n\n>>>>>>>>>>>>", invest_list_str, "---> 투자개수 : ", len(positions))
    pprint.pprint(positions)
    print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>--))", str(date), " 잔고:", str(invest_money), "=", str(cash), "+", str(invest_money - cash), "\n\n")


if TotalMoneyList:
    result_df = pd.DataFrame({"Total_Money": TotalMoneyList}, index=combined_df.index.unique()[-len(TotalMoneyList):])
    result_df['Ror'] = np.nan_to_num(result_df['Total_Money'].pct_change()) + 1
    result_df['Cum_Ror'] = result_df['Ror'].cumprod()
    result_df['Highwatermark'] = result_df['Cum_Ror'].cummax()
    result_df['Drawdown'] = (result_df['Cum_Ror'] / result_df['Highwatermark']) - 1
    result_df['MaxDrawdown'] = result_df['Drawdown'].cummin()

    final_money = result_df['Total_Money'].iloc[-1]
    revenue_rate = (result_df['Cum_Ror'].iloc[-1] - 1.0) * 100.0
    mdd = result_df['MaxDrawdown'].min() * 100.0
    years = max((pd.to_datetime(result_df.index[-1]) - pd.to_datetime(result_df.index[0])).days / 365.25, 1e-9)
    cagr = ((final_money / TotalMoney) ** (1 / years) - 1.0) * 100.0

    fig, axs = plt.subplots(2, 1, figsize=(10, 10))
    axs[0].plot(pd.to_datetime(result_df.index), result_df['Cum_Ror'] * 100, label='Strategy')
    axs[0].set_title('Return Comparison Chart')
    axs[0].legend()
    axs[1].plot(pd.to_datetime(result_df.index), result_df['MaxDrawdown'] * 100, label='MDD')
    axs[1].plot(pd.to_datetime(result_df.index), result_df['Drawdown'] * 100, label='Drawdown')
    axs[1].set_title('Drawdown Comparison Chart')
    axs[1].legend()
    plt.tight_layout()
    plt.show()

    print("\n\n--------------------")
    print("--->>>", str(FirstDateStr).replace("00:00:00", ""), "~", str(result_df.iloc[-1].name).replace("00:00:00", ""), "<<<---")
    for s in StockDataList:
        print(s['stock_name'], "(", s['stock_code'], ")")
        if s['try'] > 0:
            print("성공:", s['success'], "실패:", s['fail'], "-> 승률:", round(s['success'] / s['try'] * 100.0, 2), "%")
            print("매매당 평균 수익률:", round(s['accRev'] / s['try'], 2))
        print()
    print("---------- 총 결과 ----------")
    print("최초 금액:", format(int(round(TotalMoney, 0)), ','), " 최종 금액:", format(int(round(final_money, 0)), ','))
    print("수익률:", round(((final_money - TotalMoney) / TotalMoney) * 100, 2), "% MDD:", round(mdd, 2), "%")
    if TryCnt > 0:
        print("성공:", SuccesCnt, "실패:", FailCnt, "-> 승률:", round(SuccesCnt / TryCnt * 100.0, 2), "%")
    print("연복리수익률(CAGR):", format(round(cagr, 2), ','), "%")
    print("------------------------------")
    print("####################################")
