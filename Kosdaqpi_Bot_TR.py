#-*-coding:utf-8 -*-
'''

$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
코드 참고 영상!
https://youtu.be/YdEdM-oC0kc
$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$



$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$

게만아 추가 개선 전략들..
https://blog.naver.com/zacra/223196497504

관심 있으신 분은 위 포스팅을 참고하세요!

$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$


원본 전략 포스팅
-----------------------------------------------------------
 
코스닥 코스피 양방향으로 투자하는 전략! 초전도체 LK99에 버금가는 발견!!
https://blog.naver.com/zacra/223177598281

OBV 활용 추가!
https://blog.naver.com/zacra/223986975517
-----------------------------------------------------------
 

-----------------------------------------------------------
✅ 트레일링 스탑 관련 포스팅
https://blog.naver.com/zacra/224157551452

위 포스팅을 꼭 참고하세요!!!

본 코드는 트레일링 스탑을 위해
스탑 트레이더가 필요합니다.
https://blog.naver.com/zacra/223958658877
-----------------------------------------------------------
 




📌 [코드 제공 목적]

이 코드는 클래스101 게만아 <파이썬 자동매매 봇 만들기> 강의의 보조 자료로 제공되며,  
강의 수강생의 **학습 및 실습을 위한 참고용 예시 코드**입니다.  
**투자 권유, 종목 추천, 자문 또는 일임을 위한 목적은 전혀 없습니다.**

📌 [기술 구현 관련 안내]

- 본 코드는 **증권사에서 공식적으로 제공한 API** 및  
  **공식 개발자 가이드 문서**에 따라 구현되었습니다.
- 해당 API는 일반 투자자 누구나 이용 가능한 서비스이며,  
  본 코드는 그것을 구현한 예시를 활용해 전략을 구현해보는 학습 목적으로 활용한 것입니다.

📌 [전략 실행 조건]

- 본 코드는 자동 반복 실행되지 않으며, 사용자가 직접 실행해야 1회 동작합니다.
- 반복 실행을 원할 경우, 사용자가 별도로 서버 및 스케줄러 구성을 해야 합니다.


- 본 코드에는 증권사 제공 API를 활용한 매매 기능이 포함되어 있으나,  
  **사용자가 명시적으로 설정을 변경하지 않는 한 실행되지 않습니다.**
  

- 전략 실행을 위해서는 다음의 과정을 **사용자가 직접** 수행해야 합니다:

  1. `ENABLE_ORDER_EXECUTION` 값을 `True`로 변경  
  2. `InvestRate` 비중을 설정 (기본값: 0)  
  3. 매수할 종목을 명시 (기본값: 빈 리스트)  
  4. AWS 또는 개인 서버 구축 및 `crontab` 또는 스케줄러 등록

- 제공자는 서버 구축, 설정, 실행 대행 등을 전혀 하지 않습니다.

📌 [법적 책임 고지]

- 제공되는 코드는 기술 학습 및 테스트 목적의 예시 코드입니다.  
- **백테스트 결과는 과거 데이터 기반이며, 미래 수익을 보장하지 않습니다.**

- 본 코드의 사용, 수정, 실행에 따른 모든 결과와 책임은 사용자에게 있으며,  
  **제공자는 법적·금전적 책임을 일절 지지 않습니다.**

📌 [저작권 안내]

- 이 코드는 저작권법 및 부정경쟁방지법의 보호를 받습니다.  
- 무단 복제, 공유, 재판매, 배포 시 민·형사상 책임이 따를 수 있습니다.

📌 [학습 권장 사항]

- 본 예시 코드는 전략 구현을 이해하기 위한 템플릿입니다.  
- 이를 바탕으로 자신만의 전략을 개발해보시길 권장드립니다 :)



주식/코인 자동매매 FAQ
https://blog.naver.com/zacra/223203988739

FAQ로 해결 안되는 기술적인 문제는 파이썬 자동매매 연구소 게만아 카페를 이용해 주세요 :)

'''

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR
import time
import pprint
import pandas as pd
import json
from datetime import datetime


import line_alert
import KIS_KR_StopTrader  # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가



#계좌 선택.. "VIRTUAL" 는 모의 계좌!
Common.SetChangeMode("VIRTUAL") #REAL or VIRTUAL


#####################################################################################################################################
'''
※ 주문 실행 여부 설정

ENABLE_ORDER_EXECUTION 값을 True로 변경할 경우,  
전략에 따라 매매가 일어납니다.

⚠️ 기본값은 False이며,  
실행 여부는 사용자 본인이 코드를 수정하여 결정해야 합니다.
'''

ENABLE_ORDER_EXECUTION = False  # 주문 실행 여부 설정 (기본값: False)

'''
📌 본 전략은 시스템을 구현하는 예시 코드이며,  
실제 투자 및 주문 실행은 사용자 본인의 의사와 책임 하에 수행됩니다.
'''
#####################################################################################################################################

'''
📌 투자할 종목은 본인의 선택으로 리스트 형식으로 직접 입력하세요!
'''
#실제 투자 종목!!!
InvestStockList = [] #아래 예시처럼 직접 판단해서 넣으셔요!
#InvestStockList = ["122630","252670","233740","251340"]

#####################################################################################################################################

'''
📌 투자 비중 설정!
기본은 0으로 설정되어 있어요.
본인의 투자 비중을 설정하세요! 

전략에서 활용할 주문이 
시장가 주문이라면 0 ~ 0.75 
지정가 주문이라면 0 ~ 0.98
사이의 값으로 설정하세요! (0.1 = 10% 0.5 = 50%)
'''
InvestRate = 0 #총 평가금액에서 해당 봇에게 할당할 총 금액비율 0.1 = 10%  0.5 = 50%
#####################################################################################################################################

# [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 트레일링 스탑 콜백비율 설정
TRAILING_STOP_CANDLE_COUNT = 20  # 콜백비율 계산에 사용할 캔들 개수
TRAILING_STOP_MULTIPLIER = 2.0   # 고가-저가 평균에 곱할 배수
TRAILING_STOP_MIN_RATE = 2.0     # 최소 콜백비율 (%)
#####################################################################################################################################




BOT_NAME = Common.GetNowDist() + "_MyKospidaq_Bot"





#포트폴리오 이름
PortfolioName = "게만아 코스피닥 매매 전략!"


#시간 정보를 읽는다
time_info = time.gmtime()

day_n = time_info.tm_mday
day_str = str(time_info.tm_mon) + "-" + str(time_info.tm_mday)

print(day_str)





###################################################################
###################################################################
#리스트에서 데이터를 리턴!
def GetKospidaqStrategyData(stock_code,KospidaqStrategyList):
    ResultData = None
    for KospidaqStrategyData in KospidaqStrategyList:
        if KospidaqStrategyData['StockCode'] == stock_code:
            ResultData = KospidaqStrategyData
            break
    return ResultData



#투자개수
def GetKospidaqInvestCnt(KospidaqStrategyList):
    
    MyStockList = KisKR.GetMyStockList()

    InvestCnt = 0
        
    for KospidaqStrategyData in KospidaqStrategyList:
        stock_code = KospidaqStrategyData['StockCode']
        
        stock_amt = 0
        #내가 보유한 주식 리스트에서 매수된 잔고 정보를 가져온다
        for my_stock in MyStockList:
            if my_stock['StockCode'] == stock_code:
                stock_amt = int(my_stock['StockAmt'])
                break
            
        if stock_amt > 0:
            InvestCnt += 1
            
        
    return InvestCnt







#####################################################################################################################################

#계좌 잔고를 가지고 온다!
Balance = KisKR.GetBalance()
#####################################################################################################################################

'''-------통합 증거금 사용자는 아래 코드도 사용할 수 있습니다! -----------'''
#통합증거금 계좌 사용자 분들중 만약 미국계좌랑 통합해서 총자산을 계산 하고 포트폴리오 비중에도 반영하고 싶으시다면 아래 코드를 사용하시면 되고 나머지는 동일합니다!!!
#Balance = Common.GetBalanceKrwTotal()

'''-----------------------------------------------------------'''
#####################################################################################################################################


print("--------------내 보유 잔고---------------------")

pprint.pprint(Balance)

print("--------------------------------------------")


##########################################################

print("--------------내 보유 주식---------------------")
#그리고 현재 이 계좌에서 보유한 주식 리스트를 가지고 옵니다!
MyStockList = KisKR.GetMyStockList()
pprint.pprint(MyStockList)
print("--------------------------------------------")
##########################################################





NowInvestMoney = 0

for stock_code in InvestStockList:
    stock_name = ""
    stock_amt = 0 #수량
    stock_avg_price = 0 #평단

    #내가 보유한 주식 리스트에서 매수된 잔고 정보를 가져온다
    for my_stock in MyStockList:
        if my_stock['StockCode'] == stock_code:
            stock_name = my_stock['StockName']
            stock_amt = int(my_stock['StockAmt'])
            stock_avg_price = float(my_stock['StockAvgPrice'])

            
            NowInvestMoney += (stock_amt*stock_avg_price)
            break



###################################################################
###################################################################
KospidaqStrategyList = list()
#파일 경로입니다.
data_file_path = "/var/autobot/KrStock_" + BOT_NAME + ".json"

try:
    #이 부분이 파일을 읽어서 리스트에 넣어주는 로직입니다. 
    with open(data_file_path, 'r') as json_file:
        KospidaqStrategyList = json.load(json_file)
    
    # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 기존 데이터 호환성 보장
    for KospidaqStrategyData in KospidaqStrategyList:
        if KospidaqStrategyData.get('IsTrailingStopSet') == None:
            KospidaqStrategyData['IsTrailingStopSet'] = False
        if KospidaqStrategyData.get('TrailingStopCallbackRate') == None:
            KospidaqStrategyData['TrailingStopCallbackRate'] = 0
        if KospidaqStrategyData.get('PrevStockAmt') == None:
            KospidaqStrategyData['PrevStockAmt'] = 0

except Exception as e:
    print("Init....")

    for stock_code in InvestStockList:

        KospidaqStrategyData = dict()
        KospidaqStrategyData['StockCode'] = stock_code #대상 종목 코드
        KospidaqStrategyData['StockName'] = KisKR.GetStockName(stock_code) #종목 이름
        KospidaqStrategyData['Status'] = "REST" #상태 READY(돌파를체크해야하는 준비상태), INVESTING(돌파해서 투자중), INVESTING_TRY(매수 주문 들어감) REST(조건불만족,투자안함,돌파체크안함) 
        KospidaqStrategyData['DayStatus'] = "NONE" #오늘 매수(BUY)하는 날인지 매도(SELL)하는 날인지 대상이 아닌지 (NONE) 체크
        KospidaqStrategyData['TargetPrice'] = 0 #돌파가격
        KospidaqStrategyData['TryBuyCnt'] = 0 #매수시도하고자 하는 수량!
        KospidaqStrategyData['IsTrailingStopSet'] = False # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가
        KospidaqStrategyData['TrailingStopCallbackRate'] = 0 # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가
        KospidaqStrategyData['PrevStockAmt'] = 0 # [2026.01.23] 추가 매수 감지를 위한 이전 보유 수량

        KospidaqStrategyList.append(KospidaqStrategyData)

    #파일에 저장
    with open(data_file_path, 'w') as outfile:
        json.dump(KospidaqStrategyList, outfile)


###################################################################
###################################################################
DateData = dict()
#파일 경로입니다.
date_file_path = "/var/autobot/KrStock_" + BOT_NAME + "_Date.json"

try:
    #이 부분이 파일을 읽어서 리스트에 넣어주는 로직입니다. 
    with open(date_file_path, 'r') as json_file:
        DateData = json.load(json_file)

except Exception as e:
    print("Init....")

    DateData['Date'] = "00" #오늘날짜

    #파일에 저장
    with open(date_file_path, 'w') as outfile:
        json.dump(DateData, outfile)

###################################################################
###################################################################



###################################################################

#오늘 코스피 시가매매 로직이 진행되었는지 날짜 저장 관리 하는 파일
DateSiGaLogicDoneDict = dict()

#파일 경로입니다.
siga_logic_file_path = "/var/autobot/KrStock_" + BOT_NAME + "_TodaySigaLogicDoneDate.json"
try:
    #이 부분이 파일을 읽어서 리스트에 넣어주는 로직입니다. 
    with open(siga_logic_file_path, 'r') as json_file:
        DateSiGaLogicDoneDict = json.load(json_file)

except Exception as e:
    #처음에는 파일이 존재하지 않을테니깐 당연히 예외처리가 됩니다!
    print("Exception by First")

###################################################################








#기준이 되는 내 총 평가금액에서 투자비중을 곱해서 나온 포트폴리오에 할당된 돈!!
TotalMoney = float(Balance['TotalMoney']) * InvestRate

print("전략에 투자하는 총 금액: ", format(round(TotalMoney), ','))

InvestMoney = TotalMoney
RemainInvestMoney = TotalMoney - NowInvestMoney

print("현재 남은 금액! (투자금 제외): ", format(round(RemainInvestMoney), ','))




DivNum = len(InvestStockList)

if ENABLE_ORDER_EXECUTION == True:

    #마켓이 열렸는지 여부~!
    IsMarketOpen = KisKR.IsMarketOpen()

    IsLP_OK = True
    #정각 9시 5분 전에는 LP유동성 공급자가 없으니 매매를 피하고자.
    if time_info.tm_hour == 0: #9시인데
        if time_info.tm_min < 6: #6분보다 적은 값이면 --> 6분부터 LP가 활동한다고 하자!
            IsLP_OK = False
            
    #장이 열렸고 LP가 활동할때 매수!!!
    if IsMarketOpen == True and IsLP_OK == True: 


        #혹시 이 봇을 장 시작하자 마자 돌린다면 20초르 쉬어준다.
        #그 이유는 20초는 지나야 오늘의 일봉 정보를 제대로 가져오는데
        #tm_hour가 0은 9시, 1은 10시를 뜻한다. 수능 등 10시에 장 시작하는 경우르 대비!
        if time_info.tm_hour in [0,1] and time_info.tm_min in [0,1]:
            time.sleep(20.0)
            

        print("Market Is Open!!!!!!!!!!!")
        #영상엔 없지만 리밸런싱이 가능할때만 내게 메시지를 보내자!



        #데이터를 조합한다.
        stock_df_list = []
        
                
        gugan_lenth = 7


        for stock_code in InvestStockList:
            df = Common.GetOhlcv("KR", stock_code,200)
            
            #########################################################################################
            #OBV 활용! 
            # OBV 계산
            df['direction'] = 0
            df.loc[df['close'] > df['close'].shift(1), 'direction'] = 1
            df.loc[df['close'] < df['close'].shift(1), 'direction'] = -1
            df['obv'] = (df['direction'] * df['volume']).cumsum()

            # OBV 이동평균선
            df['obv_ma'] = df['obv'].rolling(window=10).mean()
            
            df['prev_obv_ma'] = df['obv_ma'].shift(1)
            df['prev_obv_ma2'] = df['obv_ma'].shift(2)
            df['prev_obv'] = df['obv'].shift(1)

            #########################################################################################
    
            period = 14

            delta = df["close"].diff()
            up, down = delta.copy(), delta.copy()
            up[up < 0] = 0
            down[down > 0] = 0
            _gain = up.ewm(com=(period - 1), min_periods=period).mean()
            _loss = down.abs().ewm(com=(period - 1), min_periods=period).mean()
            RS = _gain / _loss

            df['RSI'] = pd.Series(100 - (100 / (1 + RS)), name="RSI")

            df['prevRSI'] = df['RSI'].shift(1)
            df['prevRSI2'] = df['RSI'].shift(2)
            
            df['high_'+str(gugan_lenth)+'_max'] = df['high'].rolling(window=gugan_lenth).max().shift(1)
            df['low_'+str(gugan_lenth)+'_min'] = df['low'].rolling(window=gugan_lenth).min().shift(1)


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
            
            # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 콜백비율 계산용 데이터
            df['hl_range'] = df['high'] - df['low']
            df['hl_range_avg'] = df['hl_range'].rolling(window=TRAILING_STOP_CANDLE_COUNT).mean()

            #10일마다 총 100일 평균모멘텀스코어
            specific_days = list()

            for i in range(1,11):
                st = i * 10
                specific_days.append(st)

            for day in specific_days:
                column_name = f'Momentum_{day}'
                df[column_name] = (df['prevClose'] > df['close'].shift(day)).astype(int)
                
            df['Average_Momentum'] = df[[f'Momentum_{day}' for day in specific_days]].sum(axis=1) / 10



            # Define the list of specific trading days to compare
            specific_days = list()

            for i in range(1,11):
                st = i * 3
                specific_days.append(st)



            # Iterate over the specific trading days and compare the current market price with the corresponding closing prices
            for day in specific_days:
                # Create a column name for each specific trading day
                column_name = f'Momentum_{day}'
                
                # Compare current market price with the closing price of the specific trading day
                df[column_name] = (df['prevClose'] > df['close'].shift(day)).astype(int)

            # Calculate the average momentum score
            df['Average_Momentum3'] = df[[f'Momentum_{day}' for day in specific_days]].sum(axis=1) / 10



            df.dropna(inplace=True) #데이터 없는건 날린다!


            data_dict = {stock_code: df}
            stock_df_list.append(data_dict)
            print("---stock_code---", stock_code , " len ",len(df))
            pprint.pprint(df)
            
            


            #시가매매 체크한 기록이 없는 맨 처음이라면 
            if DateSiGaLogicDoneDict.get(stock_code) == None:

                #0으로 초기화!!!!!
                DateSiGaLogicDoneDict[stock_code] = 0
                #파일에 저장
                with open(siga_logic_file_path, 'w') as outfile:
                    json.dump(DateSiGaLogicDoneDict, outfile)

            #시가매매 체크한 기록이 없는 맨 처음이라면 
            if DateSiGaLogicDoneDict.get('InvestCnt') == None:
                DateSiGaLogicDoneDict['InvestCnt'] =  GetKospidaqInvestCnt(KospidaqStrategyList) #일단 투자중 개수 저장!
                #파일에 저장
                with open(siga_logic_file_path, 'w') as outfile:
                    json.dump(DateSiGaLogicDoneDict, outfile)
                    
                    
            if DateSiGaLogicDoneDict.get('IsCut') == None:
                DateSiGaLogicDoneDict['IsCut'] =  False
                DateSiGaLogicDoneDict['IsCutCnt'] =  0
                #파일에 저장
                with open(siga_logic_file_path, 'w') as outfile:
                    json.dump(DateSiGaLogicDoneDict, outfile)



        # Combine the OHLCV data into a single DataFrame
        combined_df = pd.concat([list(data_dict.values())[0].assign(stock_code=stock_code) for data_dict in stock_df_list for stock_code in data_dict])

        # Sort the combined DataFrame by date
        combined_df.sort_index(inplace=True)

        pprint.pprint(combined_df)
        print(" len(combined_df) ", len(combined_df))


        date = combined_df.iloc[-1].name

        all_stocks = combined_df.loc[combined_df.index == date].groupby('stock_code')['close'].max().nlargest(DivNum)
        

        #######################################################################################################################################
        # 횡보장을 정의하기 위한 로직!!
        # https://blog.naver.com/zacra/223225906361 이 포스팅을 정독하세요!!!
        Kosdaq_Long_Data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "233740")]
        Kosdaq_Short_Data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "251340")]
        Kospi_Long_Data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "122630")]
        Kospi_Short_Data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == "252670")]
        
        
        IsNoWay = False
        if  (Kospi_Long_Data['prevChangeMa_S'].values[0] > 0 and Kospi_Short_Data['prevChangeMa_S'].values[0] > 0) or (Kospi_Long_Data['prevChangeMa_S'].values[0] < 0 and Kospi_Short_Data['prevChangeMa_S'].values[0] < 0)  or (Kosdaq_Long_Data['prevChangeMa_S'].values[0] > 0 and Kosdaq_Short_Data['prevChangeMa_S'].values[0] > 0) or (Kosdaq_Long_Data['prevChangeMa_S'].values[0] < 0 and Kosdaq_Short_Data['prevChangeMa_S'].values[0] < 0) :
            IsNoWay = True
        #######################################################################################################################################

        
        

        #날짜가 다르다면 날이 바뀐거다
        if day_str != DateData['Date']:
                
                
            line_alert.SendMessage(PortfolioName + "  장이 열려서 매매 가능!!")




            # 일봉 정보 가지고 오는 모듈이 달라지면 에러가 나므로 예외처리
            date_format = "%Y-%m-%d %H:%M:%S"
            date_object = None

            try:
                date_object = datetime.strptime(str(date), date_format)
            
            except Exception as e:
                try:
                    date_format = "%Y%m%d"
                    date_object = datetime.strptime(str(date), date_format)

                except Exception as e2:
                    date_format = "%Y-%m-%d"
                    date_object = datetime.strptime(str(date), date_format)
                    

            # 요일 가져오기 (0: 월요일, 1: 화요일,2 수요일 3 목요일 4 금요일 5 토요일 ..., 6: 일요일)
            weekday = date_object.weekday()
            print("--weekday--", weekday, time_info.tm_wday)





            #가장 최근 데이터의 날짜의 요일과 봇이 실행되는 요일은 같아야 한다.
            #이게 다르다면 아직 최근 데이터의 날자가 갱신 안되었단 이야기인데 이는 9시 정각이나..(20초 딜레이가 필요) 수능등으로 장 오픈시간이 지연되었을때 다를 수 있다. 그때는 매매하면 안된다
            if weekday == time_info.tm_wday:
                
                DateSiGaLogicDoneDict['InvestCnt'] = GetKospidaqInvestCnt(KospidaqStrategyList) #일단 투자중 개수 저장!
                #파일에 저장
                with open(siga_logic_file_path, 'w') as outfile:
                    json.dump(DateSiGaLogicDoneDict, outfile)
                    
                    

                DateData['Date'] = day_str #오늘 맨처음 할일 (종목 선정 및 돌파가격 설정, 상태 설정)을 끝냈으니 날짜를 넣어 다음날 다시 실행되게 한다.
                with open(date_file_path, 'w') as outfile:
                    json.dump(DateData, outfile)

                #기본적으로 날이 바뀌었기 때문에 데이 조건(BUY_DAY,SELL_DAY)를 모두 초기화 한다!
                for KospidaqStrategyData in KospidaqStrategyList:
                    KospidaqStrategyData['DayStatus'] = "NONE"

                    #그리고 투자중 상태는 SELL_DAY로 바꿔준다!!
                    if KospidaqStrategyData['Status'] == "INVESTING":
                        KospidaqStrategyData['DayStatus'] = "SELL_DAY"

                        msg = KospidaqStrategyData['StockName'] + "  투자중 상태에요! 조건을 만족하면 매도로 트레이딩 종료 합니다.!!"
                        print(msg)
                        line_alert.SendMessage(msg)


            
                for stock_code in  all_stocks.index:
                    stock_data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]

                    #해당 정보를 읽는다.
                    KospidaqStrategyData = GetKospidaqStrategyData(stock_code,KospidaqStrategyList)

                    #만약 정보가 없다면 새로 추가된 종목이니 새로 저장한다!!!
                    if KospidaqStrategyData == None:

                        KospidaqStrategyData = dict()
                        KospidaqStrategyData['StockCode'] = stock_code #대상 종목 코드
                        KospidaqStrategyData['StockName'] = KisKR.GetStockName(stock_code) #종목 이름
                        KospidaqStrategyData['Status'] = "REST" #상태 READY(돌파를체크해야하는 준비상태), INVESTING(돌파해서 투자중), REST(조건불만족,투자안함,돌파체크안함) 
                        KospidaqStrategyData['DayStatus'] = "NONE" #오늘 매수하는 날인지 매도하는 날인지 체크
                        KospidaqStrategyData['TargetPrice'] = 0 #돌파가격
                        KospidaqStrategyData['TryBuyCnt'] = 0 #매수시도하고자 하는 수량!
                        KospidaqStrategyData['IsTrailingStopSet'] = False # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가
                        KospidaqStrategyData['TrailingStopCallbackRate'] = 0 # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가

                        KospidaqStrategyList.append(KospidaqStrategyData)

                    #코스닥 전략...돌파 매매..
                    if stock_code in ["233740","251340"]:
                        
                            
                        PrevClosePrice = stock_data['prevClose'].values[0] 
                        
                        DolpaRate = 0.4

                        # KODEX 코스닥150선물인버스
                        if stock_code == "251340":

                            DolpaRate = 0.4

                        #KODEX 코스닥150레버리지
                        else: 

                            if PrevClosePrice > stock_data['ma60_before'].values[0]:
                                DolpaRate = 0.3
                            else:
                                DolpaRate = 0.4


                        ##########################################################################
                        #갭 상승 하락을 이용한 돌파값 조절!
                        # https://blog.naver.com/zacra/223277173514 이 포스팅을 체크!!!!
                        ##########################################################################
                        Gap = ((abs(stock_data['open'].values[0] - PrevClosePrice) / PrevClosePrice)) * 100.0

                        GapSt = (Gap*0.025)

                        if GapSt > 1.0:
                            GapSt = 1.0
                        if GapSt < 0:
                            GapSt = 0.1

                        if PrevClosePrice > stock_data['open'].values[0] and Gap >= 3.0:
                            DolpaRate *= (1.0 + GapSt)

                        if PrevClosePrice < stock_data['open'].values[0] and Gap >= 3.0:
                            DolpaRate *= (1.0 - GapSt)

            
                        DolPaPrice = stock_data['open'].values[0] + ((stock_data['prevHigh'].values[0] - stock_data['prevLow'].values[0]) * DolpaRate)


                        #어제 무슨 이유에서건 매수 실패했다면 일단 REST로!
                        if KospidaqStrategyData['Status'] == "INVESTING_TRY":
                            KospidaqStrategyData['Status'] = "REST"
                            KospidaqStrategyData['DayStatus'] = "NONE"

                        #어제 무슨 이유에서건 매도 실패했다면 투자중 상태로 변경!
                        if KospidaqStrategyData['Status'] == "SELL_DONE_CHECK":
                            KospidaqStrategyData['Status'] = "INVESTING"
                            KospidaqStrategyData['DayStatus'] = "SELL_DAY"



                        
                        if KospidaqStrategyData['Status'] != "INVESTING": #투자 상태가 아니라면 조건을 체크하여 매수시도할 수 있다!
                            
                            IsBuyReady = True #일단 무조건 True 만약 필터하고자 하면 False로 하고 조건만족시 True로 바꾸면 된다.
                            

                            KospidaqStrategyData['StockCode'] = stock_code #대상 종목 코드
                            KospidaqStrategyData['StockName'] = KisKR.GetStockName(stock_code)


                            if stock_code == "251340":
                                if stock_data['prevClose'].values[0] <= stock_data['ma20_before'].values[0]:
                                    IsBuyReady = False 
            

                            else: #레버리지

                                if stock_data['prevLow'].values[0] > stock_data['open'].values[0] and stock_data['prevClose'].values[0] < stock_data['ma10_before'].values[0]:
                                    IsBuyReady = False 
                                    
                            # 추가 개선 로직 https://blog.naver.com/zacra/223326173552 이 포스팅 참고!!!!
                            IsJung = False    
                            if stock_data['ma10_before'].values[0] > stock_data['ma20_before'].values[0] > stock_data['ma60_before'].values[0] > stock_data['ma120_before'].values[0]:
                                IsJung = True
                                
                            if IsJung == False:
                                
                                        
                                high_price = stock_data['high_'+str(gugan_lenth)+'_max'].values[0] 
                                low_price =  stock_data['low_'+str(gugan_lenth)+'_min'].values[0] 
                                
                                Gap = (high_price - low_price) / 4
                                
                                
                                MaximunPrice = low_price + Gap * 3.0
                                
                                
                                if stock_data['open'].values[0] > MaximunPrice:
                                    IsBuyReady = False
            
            
            
                            #OBV 활용! 추가 필터!
                            if IsBuyReady == True:
                                #OBV 10이평선이 감소중이고 OBV값이 10이평선 아래에 있다면 매수를 취소한다!
                                if stock_data['prev_obv_ma2'].values[0] > stock_data['prev_obv_ma'].values[0] and stock_data['prev_obv'].values[0] < stock_data['prev_obv_ma'].values[0]:
                                    IsBuyReady = False
                                    

                            #기본 필터 통과!! 돌파가격을 정하고 READY상태로 변경
                            if IsBuyReady == True:
                                print("IS Ready!!!")
                                KospidaqStrategyData['TargetPrice'] = DolPaPrice #돌파가격

                                KospidaqStrategyData['Status'] = "READY"
                                KospidaqStrategyData['DayStatus'] = "BUY_DAY"


                                msg = KospidaqStrategyData['StockName'] + " 돌파하면 매수합니다!!!"
                                print(msg)
                                line_alert.SendMessage(msg)

                            #기본 필터 통과 실패 매수 안함! 
                            else:
                                print("No Ready")
                
                                KospidaqStrategyData['Status'] = "REST"
                                KospidaqStrategyData['DayStatus'] = "NONE"


                                msg = KospidaqStrategyData['StockName'] + "  조건을 불만족하여 오늘 돌파매수는 쉽니다!!!"
                                print(msg)
                                line_alert.SendMessage(msg)
                            
                    #코스피 전략.... 시가 매매
                    else:
                        

                        #어제 무슨 이유에서건 매수 실패했다면 일단 REST로!
                        if KospidaqStrategyData['Status'] == "INVESTING_TRY":
                            KospidaqStrategyData['Status'] = "REST"
                            KospidaqStrategyData['DayStatus'] = "NONE"

                        #어제 무슨 이유에서건 매도 실패했다면 투자중 상태로 변경!
                        if KospidaqStrategyData['Status'] == "SELL_DONE_CHECK":
                            KospidaqStrategyData['Status'] = "INVESTING"
                            KospidaqStrategyData['DayStatus'] = "SELL_DAY"

                        

                        if KospidaqStrategyData['Status'] != "INVESTING": #투자 상태가 아니라면 조건을 체크하여 매수시도할 수 있다!
                            


                            KospidaqStrategyData['StockCode'] = stock_code #대상 종목 코드
                            KospidaqStrategyData['StockName'] = KisKR.GetStockName(stock_code)

                            KospidaqStrategyData['Status'] = "READY"
                            KospidaqStrategyData['DayStatus'] = "BUY_DAY"


                            msg = KospidaqStrategyData['StockName'] + " 조건을 만족했다면 매수합니다!!!"
                            print(msg)
                            line_alert.SendMessage(msg)




                    #파일에 저장
                    with open(data_file_path, 'w') as outfile:
                        json.dump(KospidaqStrategyList, outfile)
            else:

                if time_info.tm_min == 0 or time_info.tm_min == 30:
                    msg = "요일이 다르게 나왔어요! 좀 더 기다려봐요!"
                    print(msg)
                    line_alert.SendMessage(msg)
                    

        if day_str == DateData['Date']: #오늘 할일을 한다!

            ### 매도 파트 ###
            for KospidaqStrategyData in KospidaqStrategyList:
                pprint.pprint(KospidaqStrategyData)

                stock_code = KospidaqStrategyData['StockCode']
                
                stock_data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]

                if len(stock_data) == 1:
                    
                    NowOpenPrice = stock_data['open'].values[0]
                    PrevOpenPrice = stock_data['prevOpen'].values[0] 
                    PrevClosePrice = stock_data['prevClose'].values[0] 


                    #현재가!
                    CurrentPrice = KisKR.GetCurrentPrice(stock_code)        
                    


                    IsSellAlready = False   
                    #해당 ETF가 매도하는 날 상태이다!
                    if KospidaqStrategyData['DayStatus'] == "SELL_DAY":

                        #제대로 매도되었는지 확인!
                        if KospidaqStrategyData['Status'] == "SELL_DONE_CHECK":
                            stock_amt = 0 #수량

                            
                            #내가 보유한 주식 리스트에서 매수된 잔고 정보를 가져온다
                            for my_stock in MyStockList:
                                if my_stock['StockCode'] == stock_code:
                                    stock_amt = int(my_stock['StockAmt'])
                                    break

                            print("stock_amt : ", stock_amt)

                            if stock_amt == 0:
                                KospidaqStrategyData['Status'] = "REST" 
                                KospidaqStrategyData['DayStatus'] = "NONE"
                                KospidaqStrategyData['PrevStockAmt'] = 0  # [2026.01.23] 추가 매수 감지 - REST 전환 시 초기화

                                msg = KospidaqStrategyData['StockName']  + " 모두 매도된 것이 확인 되었습니다!"
                                print(msg)
                                line_alert.SendMessage(msg)


                                                
                                #파일에 저장
                                with open(data_file_path, 'w') as outfile:
                                    json.dump(KospidaqStrategyList, outfile)

                            else:

                                KisKR.CancelAllOrders(KospidaqStrategyData['StockCode'],"ALL")

                                data = KisKR.MakeSellMarketOrder(KospidaqStrategyData['StockCode'],stock_amt)


                                msg = KospidaqStrategyData['StockName']  + " 모두 매도한 줄 알았는데 실패했나봐요 다시 시도합니다.\n" + str(data)
                                print(msg)
                                line_alert.SendMessage(msg)



                        #만약 투자중이라면 조건을 체크!
                        if KospidaqStrategyData['Status'] == "INVESTING": #투자중 상태


                            stock_amt = 0 #수량
                            stock_avg_price = 0 #평단
                            stock_eval_totalmoney = 0 #총평가금액!
                            stock_revenue_rate = 0 #종목 수익률
                            stock_revenue_money = 0 #종목 수익금

                        
                            
                            #내가 보유한 주식 리스트에서 매수된 잔고 정보를 가져온다
                            for my_stock in MyStockList:
                                if my_stock['StockCode'] == stock_code:
                                    stock_name = my_stock['StockName']
                                    stock_amt = int(my_stock['StockAmt'])
                                    stock_avg_price = float(my_stock['StockAvgPrice'])
                                    stock_eval_totalmoney = float(my_stock['StockNowMoney'])
                                    stock_revenue_rate = float(my_stock['StockRevenueRate'])
                                    stock_revenue_money = float(my_stock['StockRevenueMoney'])

                                    break
                            
                            # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 추가 매수 감지 및 트레일링 스탑 재설정
                            if KospidaqStrategyData.get('PrevStockAmt') == None:
                                KospidaqStrategyData['PrevStockAmt'] = 0
                            
                            prev_amt = KospidaqStrategyData['PrevStockAmt']
                            
                            # 수량 증가 = 추가 매수 발생
                            if stock_amt > prev_amt and stock_amt > 0:
                                if KospidaqStrategyData.get('IsTrailingStopSet') == True:
                                    if ENABLE_ORDER_EXECUTION == True:
                                        # 기존 트레일링 스탑 취소
                                        KIS_KR_StopTrader.CancelOrderByTicker(stock_code)
                                        time.sleep(0.5)
                                        
                                        # 새로운 수량 기준으로 콜백비율 재계산 및 재설정
                                        stock_data_now = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
                                        if len(stock_data_now) == 1:
                                            hl_avg = stock_data_now['hl_range_avg'].values[0]
                                            current_price = KisKR.GetCurrentPrice(stock_code)
                                            if current_price > 0 and hl_avg > 0:
                                                callback_rate = (hl_avg * TRAILING_STOP_MULTIPLIER / current_price) * 100.0
                                                
                                                if callback_rate < TRAILING_STOP_MIN_RATE:
                                                    callback_rate = TRAILING_STOP_MIN_RATE
                                                
                                                KospidaqStrategyData['TrailingStopCallbackRate'] = callback_rate
                                                KIS_KR_StopTrader.MakeTrailingStopLoss(stock_code, callback_rate, None, True)
                                                time.sleep(0.5)
                                                
                                                msg = stock_name + " 추가 매수 감지! 트레일링스탑 재설정 (" + str(prev_amt) + "주 → " + str(stock_amt) + "주, 콜백: " + str(round(callback_rate, 2)) + "%)"
                                                print(msg)
                                                line_alert.SendMessage(msg)
                                
                                KospidaqStrategyData['PrevStockAmt'] = stock_amt
                            
                            # 수량 감소 = 트레일링 스탑 체결 or 매도
                            elif stock_amt < prev_amt:
                                KospidaqStrategyData['PrevStockAmt'] = stock_amt
                                # 수량이 0이 되었다면 트레일링 스탑 상태 초기화
                                if stock_amt == 0:
                                    KospidaqStrategyData['IsTrailingStopSet'] = False
                                    KospidaqStrategyData['TrailingStopCallbackRate'] = 0
                                
                            #코스닥 전략...돌파 매매..
                            if stock_code in ["233740","251340"]:
                                
                                        
                                if stock_amt > 0:
                                    

                                    CutRate = 0.4

                                    if stock_code == "251340":
                                        CutRate = 0.4

                                    else:

                                        if PrevClosePrice > stock_data['ma60_before'].values[0]:
                                            CutRate = 0.4
                                        else:
                                            CutRate = 0.3


                                    
                                    CutPrice = stock_data['open'].values[0] - ((stock_data['prevHigh'].values[0] - stock_data['prevLow'].values[0]) * CutRate)
                                    
                                    

                                    CurrentPrice = KisKR.GetCurrentPrice(stock_code)  

                                    if CurrentPrice <= CutPrice or stock_data['low'].values[0] <= CutPrice :
                                        
                                        # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 매도 시 트레일링 스탑 취소
                                        if KospidaqStrategyData.get('IsTrailingStopSet') == True:
                                            KIS_KR_StopTrader.CancelOrderByTicker(stock_code)
                                            time.sleep(0.5)
                                        
                                        # 남은 물량 전량 매도
                                        pprint.pprint(KisKR.MakeSellMarketOrder(stock_code,stock_amt))
                                        
                                        KospidaqStrategyData['Status'] = "SELL_DONE_CHECK"
                                        KospidaqStrategyData['IsTrailingStopSet'] = False  # [2026.01.23] 트레일링 스탑 상태 초기화
                                        KospidaqStrategyData['TrailingStopCallbackRate'] = 0  # [2026.01.23] 트레일링 스탑 상태 초기화
                                        KospidaqStrategyData['PrevStockAmt'] = 0  # [2026.01.23] 추가 매수 감지 - 매도 완료 시 초기화

                                        msg = KospidaqStrategyData['StockName']  + " 매도조건 충족! 남은 물량 전량 매도!!! " + str(stock_revenue_money) + " 수익 확정!! 수익률:" + str(stock_revenue_rate) + "%"
                                        print(msg)
                                        line_alert.SendMessage(msg)


                                        if stock_revenue_rate < 0:
            
                                            DateSiGaLogicDoneDict['IsCut'] = True
                                            DateSiGaLogicDoneDict['IsCutCnt'] += 1
                                            #파일에 저장
                                            with open(siga_logic_file_path, 'w') as outfile:
                                                json.dump(DateSiGaLogicDoneDict, outfile)


                                        else:
                
                                            DateSiGaLogicDoneDict['IsCut'] =  False
                                            DateSiGaLogicDoneDict['IsCutCnt'] -= 1
                                            if DateSiGaLogicDoneDict['IsCutCnt'] < 0:
                                                DateSiGaLogicDoneDict['IsCutCnt'] = 0

                                            #파일에 저장
                                            with open(siga_logic_file_path, 'w') as outfile:
                                                json.dump(DateSiGaLogicDoneDict, outfile)



                                        IsSellAlready = True
                                        
                                        


                                    
                                else:
                                    KospidaqStrategyData['Status'] = "REST" 
                                    KospidaqStrategyData['DayStatus'] = "NONE"


                                    msg = KospidaqStrategyData['StockName']  + " 매수했다고 기록되었는데 물량이 없네요? 암튼 초기화 했어요 다음날 다시 전략 시작합니다!"
                                    print(msg)
                                    line_alert.SendMessage(msg)
                            #코스피
                            else:
                                
                                if stock_amt > 0:
                                    
                                    IsSellGo = False

                                    if stock_code == "252670":
                                        
                                        if stock_data['Disparity11'].values[0] > 105:
                                            #
                                            if  PrevClosePrice < stock_data['ma3_before'].values[0]: 
                                                IsSellGo = True

                                        else:
                                            #
                                            if PrevClosePrice < stock_data['ma6_before'].values[0] and PrevClosePrice < stock_data['ma19_before'].values[0] : 
                                                IsSellGo = True

                                    else:
                                        print("")
                                        
                            
                                        total_volume = (stock_data['prevVolume'].values[0]+ stock_data['prevVolume2'].values[0] +stock_data['prevVolume3'].values[0]) / 3.0

                                        Disparity = stock_data['Disparity20'].values[0] 

                                        if (stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0] or stock_data['prevVolume'].values[0] < total_volume) and (Disparity < 98 or Disparity > 105):
                                            print("hold..")
                                        else:
                                            IsSellGo = True

                        
                                    if IsSellGo == True:
                                        
                                        # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 매도 시 트레일링 스탑 취소
                                        if KospidaqStrategyData.get('IsTrailingStopSet') == True:
                                            KIS_KR_StopTrader.CancelOrderByTicker(stock_code)
                                            time.sleep(0.5)
                                        
                                        DateSiGaLogicDoneDict['InvestCnt'] -= 1 #코스피 시가 매도 걸렸을 때만 투자중 카운트를 감소!
                                        #파일에 저장
                                        with open(siga_logic_file_path, 'w') as outfile:
                                            json.dump(DateSiGaLogicDoneDict, outfile)
                                            
                    
                                        # 남은 물량 전량 매도
                                        pprint.pprint(KisKR.MakeSellMarketOrder(stock_code,stock_amt))
                                        
                                        KospidaqStrategyData['Status'] = "SELL_DONE_CHECK"
                                        KospidaqStrategyData['IsTrailingStopSet'] = False
                                        KospidaqStrategyData['TrailingStopCallbackRate'] = 0

                                        msg = KospidaqStrategyData['StockName']  + " 매도조건 충족! 남은 물량 전량 매도!!! " + str(stock_revenue_money) + " 수익 확정!! 수익률:" + str(stock_revenue_rate) + "%"
                                        print(msg)
                                        line_alert.SendMessage(msg)

                                        IsSellAlready = True
                                        


                                        ############## 팔렸다면 남은 금액 갱신 #######################
                                        time.sleep(5.0)
                                        MyStockList = KisKR.GetMyStockList()
                                        NowInvestMoney = 0

                                        for stock_code in InvestStockList:
                                            stock_name = ""
                                            stock_amt = 0 #수량
                                            stock_avg_price = 0 #평단

                                            #내가 보유한 주식 리스트에서 매수된 잔고 정보를 가져온다
                                            for my_stock in MyStockList:
                                                if my_stock['StockCode'] == stock_code:
                                                    stock_name = my_stock['StockName']
                                                    stock_amt = int(my_stock['StockAmt'])
                                                    stock_avg_price = float(my_stock['StockAvgPrice'])

                                                    
                                                    NowInvestMoney += (stock_amt*stock_avg_price)
                                                    break

                                        RemainInvestMoney = TotalMoney - NowInvestMoney
                                        ###########################################################

                                    
                                else:
                                    KospidaqStrategyData['Status'] = "REST" 
                                    KospidaqStrategyData['DayStatus'] = "NONE"


                                    msg = KospidaqStrategyData['StockName']  + " 매수했다고 기록되었는데 물량이 없네요? 암튼 초기화 했어요 다음날 다시 전략 시작합니다!"
                                    print(msg)
                                    line_alert.SendMessage(msg)


            ### 매수 파트 ###
            for KospidaqStrategyData in KospidaqStrategyList:
                pprint.pprint(KospidaqStrategyData)

                stock_code = KospidaqStrategyData['StockCode']
                
                stock_data = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]

                if len(stock_data) == 1:
                    
                    NowOpenPrice = stock_data['open'].values[0]
                    PrevOpenPrice = stock_data['prevOpen'].values[0] 
                    PrevClosePrice = stock_data['prevClose'].values[0] 


                    #현재가!
                    CurrentPrice = KisKR.GetCurrentPrice(stock_code)        
                    
                
                    #해당 ETF가 매수하는 날 상태이다!
                    if KospidaqStrategyData['DayStatus'] == "BUY_DAY":              
                        
                        #매수 시도가 진행 되었다. 매수 완료 되었는지 체크
                        if KospidaqStrategyData['Status'] == "INVESTING_TRY":
                            
                            MyStockList = KisKR.GetMyStockList()

                            stock_amt = 0 #수량

                            
                            #내가 보유한 주식 리스트에서 매수된 잔고 정보를 가져온다
                            for my_stock in MyStockList:
                                if my_stock['StockCode'] == KospidaqStrategyData['StockCode']:
                                    stock_amt = int(my_stock['StockAmt'])
                                    break
                                
                        #실제로 1주라도 매수가 되었다면 투자중 상태로 변경!!!
                        if stock_amt > 0:
                            KospidaqStrategyData['Status'] = "INVESTING"
                            KospidaqStrategyData['DayStatus'] = "NONE"
                            
                            # [2026.01.23] 절반 트레일링 스탑 정리 로직 추가 - 보유 물량의 절반에 트레일링 스탑 설정
                            if KospidaqStrategyData.get('IsTrailingStopSet') == None:
                                KospidaqStrategyData['IsTrailingStopSet'] = False
                            
                            if KospidaqStrategyData['IsTrailingStopSet'] == False:
                                stock_data_now = combined_df[(combined_df.index == date) & (combined_df['stock_code'] == stock_code)]
                                if len(stock_data_now) == 1:
                                    # 최근 N개 캔들 고가-저가 평균의 M배를 콜백비율로 설정
                                    hl_avg = stock_data_now['hl_range_avg'].values[0]
                                    current_price = KisKR.GetCurrentPrice(stock_code)
                                    if current_price > 0 and hl_avg > 0:
                                        callback_rate = (hl_avg * TRAILING_STOP_MULTIPLIER / current_price) * 100.0
                                        
                                        # 최소 콜백비율 보장
                                        if callback_rate < TRAILING_STOP_MIN_RATE:
                                            callback_rate = TRAILING_STOP_MIN_RATE
                                        
                                        KospidaqStrategyData['TrailingStopCallbackRate'] = callback_rate
                                        KIS_KR_StopTrader.MakeTrailingStopLoss(stock_code, callback_rate, None, True)
                                        KospidaqStrategyData['IsTrailingStopSet'] = True
                                        time.sleep(0.5)
                                        
                                        msg = KospidaqStrategyData['StockName'] + " 투자중! 보유물량 절반에 트레일링스탑 설정 (콜백: " + str(round(callback_rate, 2)) + "%)"
                                        print(msg)
                                        line_alert.SendMessage(msg)
                                    else:
                                        msg = KospidaqStrategyData['StockName'] + " 투자중이에요!!"
                                        print(msg)
                                        line_alert.SendMessage(msg)
                                else:
                                    msg = KospidaqStrategyData['StockName'] + " 투자중이에요!!"
                                    print(msg)
                                    line_alert.SendMessage(msg)
                            else:
                                msg = KospidaqStrategyData['StockName'] + " 투자중이에요!!"
                                print(msg)
                                line_alert.SendMessage(msg)
                            
                            # [2026.01.23] 추가 매수 감지 - 첫 매수 체결 시 PrevStockAmt 초기화
                            KospidaqStrategyData['PrevStockAmt'] = stock_amt


                        #아니라면 알림으로 알려준다!!
                        else:
                    
                            msg = KospidaqStrategyData['StockName'] + "  조건을 만족하여 매수 시도했는데 아직 1주도 매수되지 않았어요! 감산해서 매수시도 합니다! "
                            print(msg)
                            line_alert.SendMessage(msg)


                            if KospidaqStrategyData.get('TryBuyCnt') == None:
                                KospidaqStrategyData['TryBuyCnt'] = 1


                            KospidaqStrategyData['TryBuyCnt'] = int(KospidaqStrategyData['TryBuyCnt'] * 0.7)

                            if KospidaqStrategyData['TryBuyCnt'] > 1:
                                returnData = KisKR.MakeBuyMarketOrder(KospidaqStrategyData['StockCode'],KospidaqStrategyData['TryBuyCnt'],True) #30%감소된 수량으로 매수 시도!!

                                msg = KospidaqStrategyData['StockName'] + "  매수 시도!!! " + str(returnData)
                                print(msg)
                                line_alert.SendMessage(msg)

                            else:

                                KospidaqStrategyData['Status'] = "REST"
                                KospidaqStrategyData['DayStatus'] = "NONE"
                                

                                msg = KospidaqStrategyData['StockName'] + "  매수 실패!!! "
                                print(msg)
                                line_alert.SendMessage(msg)


                                
                            
                            
                        #상태를 체크해서 READY라면 돌파시 매수한다!
                        if KospidaqStrategyData['Status'] == "READY" and DateSiGaLogicDoneDict['InvestCnt'] < 2:
                            
                            
                            
                            print("돌파 체크중...")
                            
                            
                            #코스닥 전략...돌파 매매..
                            if stock_code in ["233740","251340"]:
                                

                        
                                DolpaRate = 0.4

                                # KODEX 코스닥150선물인버스
                                if stock_code == "251340":

                                    DolpaRate = 0.4

                                #KODEX 코스닥150레버리지
                                else: 

                                    if PrevClosePrice > stock_data['ma60_before'].values[0]:
                                        DolpaRate = 0.3
                                    else:
                                        DolpaRate = 0.4


                    
                                ##########################################################################
                                #갭 상승 하락을 이용한 돌파값 조절!
                                # https://blog.naver.com/zacra/223277173514 이 포스팅을 체크!!!!
                                ##########################################################################
                                Gap = ((abs(stock_data['open'].values[0] - PrevClosePrice) / PrevClosePrice)) * 100.0

                                GapSt = (Gap*0.025)

                                if GapSt > 1.0:
                                    GapSt = 1.0
                                if GapSt < 0:
                                    GapSt = 0.1

                                if PrevClosePrice > stock_data['open'].values[0] and Gap >= 3.0:
                                    DolpaRate *= (1.0 + GapSt)

                                if PrevClosePrice < stock_data['open'].values[0] and Gap >= 3.0:
                                    DolpaRate *= (1.0 - GapSt)


                    
                                DolPaPrice = stock_data['open'].values[0] + ((stock_data['prevHigh'].values[0] - stock_data['prevLow'].values[0]) * DolpaRate)

                                KospidaqStrategyData['TargetPrice'] = DolPaPrice


                                #돌파가격보다 현재가가 높다? 돌파한거다 매수한다!
                                if CurrentPrice >= KospidaqStrategyData['TargetPrice'] or stock_data['high'].values[0] >= KospidaqStrategyData['TargetPrice']  :

                                    Rate = 1.0
                                    if len(Kosdaq_Long_Data) == 1 and len(Kosdaq_Short_Data) == 1:
                                    
                                        IsLongStrong = False
                                        
                                        if Kosdaq_Long_Data['Average_Momentum'].values[0] > Kosdaq_Short_Data['Average_Momentum'].values[0]:
                                            IsLongStrong = True
                                            
                                        IsLongStrong2 = False
                                        
                                        if Kosdaq_Long_Data['prevChangeMa'].values[0] > Kosdaq_Short_Data['prevChangeMa'].values[0]:
                                            IsLongStrong2 = True
                                            
                                            
                                        if IsLongStrong == True and IsLongStrong2 == True:
                                            
                                            if stock_code == "233740":
                                                Rate = 1.3
                                            else:
                                                Rate = 0.7
                                                
                                        elif IsLongStrong == False and IsLongStrong2 == False:
                                                
                                            if stock_code == "233740":
                                                Rate = 0.7
                                            else:
                                                Rate = 1.3
                                                

                                    #############################################################
                                    #시스템 손절(?) 관련
                                    # https://blog.naver.com/zacra/223225906361 이 포스팅 체크!!!
                                    #############################################################
                                                
                                    AdjustRate = 1.0

                                    if DateSiGaLogicDoneDict['IsCut'] == True and DateSiGaLogicDoneDict['IsCutCnt'] >= 2:
                                        
                                        if stock_data['prevOpen'].values[0] > stock_data['prevClose'].values[0] and stock_data['prevHigh2'].values[0] > stock_data['prevHigh'].values[0]:

                                            AdjustRate = stock_data['Average_Momentum3'].values[0] 

                                            if DateSiGaLogicDoneDict['IsCutCnt'] >= 4:
                                                AdjustRate = stock_data['Average_Momentum3'].values[0] * 0.5


                                        
                            
                                    InvestMoneyCell = 0

                                    if IsNoWay == True:
                                        
                                        InvestMoneyCell = InvestMoney * 0.25 * Rate * AdjustRate
                                        

                                    else:                                         
                                    
                                        InvestMoneyCell = InvestMoney * 0.5 * Rate * AdjustRate
                                        
                                        #if DateSiGaLogicDoneDict['InvestCnt']  >= 1:
                                        #    InvestMoneyCell = RemainInvestMoney * Rate * AdjustRate

                                    
                                    if Rate > 0 and AdjustRate > 0:
                                        
                                        #할당된 투자금이 남은돈보다 많다면 남은 돈만큼으로 세팅!
                                        if RemainInvestMoney < InvestMoneyCell:
                                            InvestMoneyCell = RemainInvestMoney



                                            
                                        BuyAmt = int(InvestMoneyCell / CurrentPrice)
                                        

                                        #최소 2주는 살 수 있도록!
                                        if BuyAmt < 2:
                                            BuyAmt = 2

                                        KospidaqStrategyData['TryBuyCnt'] = BuyAmt #매수할 수량을..저장!

                                        ######## 시장가 지정가 나눠서 고고 ##########    
                                        #SliceAmt = int(BuyAmt / 2)

                                        #절반은 시장가로 바로고!
                                        #KisKR.MakeBuyMarketOrder(KospidaqStrategyData['StockCode'],SliceAmt,True) 
                                        
                                        #절반은 돌파가격 지정가로!
                                        #KisKR.MakeBuyLimitOrder(KospidaqStrategyData['StockCode'],SliceAmt,KospidaqStrategyData['TargetPrice'])

                                        
                                        ######## 시장가 1번에 고고 ##########
                                        #시장가로 바로고!
                                        KisKR.MakeBuyMarketOrder(KospidaqStrategyData['StockCode'],BuyAmt,True) 
                                        
                                    
                                    
                                        DateSiGaLogicDoneDict['InvestCnt'] += 1
                                        #파일에 저장
                                        with open(siga_logic_file_path, 'w') as outfile:
                                            json.dump(DateSiGaLogicDoneDict, outfile)
                                            
                                        RemainInvestMoney -= InvestMoneyCell
                                        
                                        KospidaqStrategyData['Status'] = "INVESTING_TRY"

                            


                                        msg = KospidaqStrategyData['StockName'] + "  조건을 만족하여 매수!!! 투자 시작!! "
                                        print(msg)
                                        line_alert.SendMessage(msg)
                                    else:


                                        msg = KospidaqStrategyData['StockName'] + "  돌파했지만 추세가 안좋아 매수 안함! "
                                        print(msg)
                                        line_alert.SendMessage(msg)
                    
                                else:
                                    print("아직 돌파 안함..")
                                
                                
                            #코스피 전략...시가 매매
                            else:
                                print("")
                                
                                                    
                                                    
                                #체크 날짜가 다르다면 맨 처음이거나 날이 바뀐것이다!!
                                if DateSiGaLogicDoneDict[stock_code] != day_n:
                                    




                                            
                                    IsBuyGo = False
                                    if stock_code == "252670":

                                        #이거변경
                                        if PrevClosePrice > stock_data['ma3_before'].values[0]  and PrevClosePrice > stock_data['ma6_before'].values[0]  and PrevClosePrice > stock_data['ma19_before'].values[0] and stock_data['prevRSI'].values[0] < 70 and stock_data['prevRSI2'].values[0] < stock_data['prevRSI'].values[0]:
                                            if (stock_data['prevVolume2'].values[0] < stock_data['prevVolume'].values[0]) and (stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and PrevClosePrice > stock_data['ma60_before'].values[0] and stock_data['ma60_before2'].values[0] < stock_data['ma60_before'].values[0]  and stock_data['ma3_before'].values[0]  > stock_data['ma6_before'].values[0]  > stock_data['ma19_before'].values[0]  :
                                                IsBuyGo = True

                                    else:

                                        Disparity = stock_data['Disparity20'].values[0] 
                                        
                                        if (stock_data['prevLow2'].values[0] < stock_data['prevLow'].values[0]) and (Disparity < 98 or Disparity > 106) and stock_data['prevRSI'].values[0] < 80 :
                                            IsBuyGo = True
                        
                                        
                                    if IsBuyGo == True:
                                        
                        
                        
                                        Rate = 1.0
                                        
                                        

                                        InvestMoneyCell = 0


                                        if IsNoWay == True:
                                            
                                            InvestMoneyCell = InvestMoney * 0.25 * Rate

                                        else:
                                            

                                            InvestMoneyCell = InvestMoney * 0.5 * Rate

                                            #if DateSiGaLogicDoneDict['InvestCnt']  >= 1:
                                            #    InvestMoneyCell = RemainInvestMoney * Rate * AdjustRate


                                        #할당된 투자금이 남은돈보다 많다면 남은 돈만큼으로 세팅!
                                        if RemainInvestMoney < InvestMoneyCell:
                                            InvestMoneyCell = RemainInvestMoney

                                            
                                        BuyAmt = int(InvestMoneyCell / CurrentPrice)
                                        
                                        

                                        #최소 2주는 살 수 있도록!
                                        if BuyAmt < 2:
                                            BuyAmt = 2

                                        KospidaqStrategyData['TryBuyCnt'] = BuyAmt #매수할 수량을..저장!
                                        ######## 시장가 지정가 나눠서 고고 ##########    
                                        #SliceAmt = int(BuyAmt / 2)

                                        #절반은 시장가로 바로고!
                                        #KisKR.MakeBuyMarketOrder(KospidaqStrategyData['StockCode'],SliceAmt,True) 
                                        
                                        #절반은 돌파가격 지정가로!
                                        #KisKR.MakeBuyLimitOrder(KospidaqStrategyData['StockCode'],SliceAmt,CurrentPrice)

                                        
                                        ######## 시장가 1번에 고고 ##########
                                        #시장가로 바로고!
                                        KisKR.MakeBuyMarketOrder(KospidaqStrategyData['StockCode'],BuyAmt,True) 
                                        
                                            
                                        DateSiGaLogicDoneDict['InvestCnt'] += 1
                                        #파일에 저장
                                        with open(siga_logic_file_path, 'w') as outfile:
                                            json.dump(DateSiGaLogicDoneDict, outfile)
                                            
                                        
                                        
                                        RemainInvestMoney -= InvestMoneyCell
                                        
                                        KospidaqStrategyData['Status'] = "INVESTING_TRY" 
                            


                                        msg = KospidaqStrategyData['StockName'] + "  조건을 만족하여 매수!!! 투자 시작!! "
                                        print(msg)
                                        line_alert.SendMessage(msg)



                                    msg = KospidaqStrategyData['StockName'] + " 오늘 매수여부 체크 완료!"
                                    print(msg)
                                    line_alert.SendMessage(msg)


                                    #시가 매수 로직 안으로 들어왔다면 날자를 바꿔준다!!
                                    DateSiGaLogicDoneDict[stock_code] = day_n
                                    #파일에 저장
                                    with open(siga_logic_file_path, 'w') as outfile:
                                        json.dump(DateSiGaLogicDoneDict, outfile)

            #파일에 저장
            with open(data_file_path, 'w') as outfile:
                json.dump(KospidaqStrategyList, outfile)
    else:
        print("Market Is Close!!!!!!!!!!!")

        #line_alert.SendMessage(PortfolioName + "  장이 열려있지 않아요!")


    pprint.pprint(DateData)
    pprint.pprint(KospidaqStrategyList)


else:
    print("코드 맨 첫 부분에 ENABLE_ORDER_EXECUTION 값을 True로 변경해야 매수매도가 진행됩니다!")



