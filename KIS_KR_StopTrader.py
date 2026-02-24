'''

관련 포스팅
https://blog.naver.com/zacra/223958658877

📌 게만아의 모든 코드는 특정 종목 추천이나 투자 권유를 위한 것이 아닙니다.  
제작자의 개인적인 견해를 바탕으로 구성된 교육용 예시 코드이며, 수익을 보장하지 않습니다
실제 투자 판단 및 실행은 전적으로 사용자 본인의 책임입니다.

주식/코인 파이썬 매매 FAQ
https://blog.naver.com/zacra/223203988739

FAQ로 해결 안되는 기술적인 문제는 클래스101 강의의 댓글이나 위 포스팅에 댓글로 알려주세요.
파이썬 코딩에 대한 답변만 가능합니다. 현행법 상 투자 관련 질문은 답변 불가하다는 점 알려드려요!


'''
# -*- coding: utf-8 -*-
import KIS_Common as Common
import KIS_API_Helper_KR as KisKR
import time
import random
import json
import line_alert
import fcntl
import datetime

DIST = "한국주식"

#장이 열린지 여부 판단을 위한 계좌 정보로 현재 자동매매중인 계좌명 아무거나 넣으면 됩니다.
Common.SetChangeMode("REAL3") #즉 다계좌 매매로 REAL, REAL2, REAL3 여러개를 자동매매 해도 한개만 여기 넣으면 됨!

IsMarketOpen = KisKR.IsMarketOpen()

#최소 주문 수량 (주식은 1주 단위)
minimumVolume = 1

auto_order_file_path = "/var/autobot/KIS_KR_StopTrader_AutoOrderList.json"
time.sleep(random.random()*0.1)

#자동 주문 리스트 읽기!
AutoOrderList = list()
try:
    with open(auto_order_file_path, 'r') as json_file:
        fcntl.flock(json_file, fcntl.LOCK_EX)  # 파일 락 설정
        AutoOrderList = json.load(json_file)
        fcntl.flock(json_file, fcntl.LOCK_UN)  # 파일 락 해제
except Exception as e:
    print("Exception by First")

# 주문 ID 생성 함수
def generate_order_id(order_type, stock_code):
    """
    주문 ID를 생성하는 함수
    형식: 주문타입_주문시간(밀리초)_종목코드
    
    Args:
        order_type: 주문 타입 (StopBuy, StopSell, ProfitSell, TrailingStopBuy, TrailingStopSell,StopLoss, TrailingStopLoss)
        stock_code: 종목 코드 (예: "005930")
    
    Returns:
        str: 고유한 주문 ID
    """
    current_time = datetime.datetime.now()
    timestamp = current_time.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 밀리초까지 포함
    order_id = f"{order_type}_{timestamp}_{stock_code}"
    return order_id

# 주문 ID로 주문 정보 찾기
def GetOrderById(order_id):
    global AutoOrderList
    DIST = Common.GetNowDist()
    
    for order in AutoOrderList:
        if order['OrderId'] == order_id and order.get('AccountType') == DIST:
            return order
    return None

# 종목코드와 주문유형으로 주문 정보 찾기
def GetOrderByTickerAndType(stock_code, order_type):
    global AutoOrderList
    DIST = Common.GetNowDist()
    
    for order in AutoOrderList:
        if order['stock_code'] == stock_code and order['OrderType'] == order_type and order.get('AccountType') == DIST:
            return order
    return None

# 전체 주문 리스트 반환
def GetAllOrders():
    global AutoOrderList
    return AutoOrderList

# 주문 취소 함수
def CancelOrderById(order_id):
    """
    주문 ID로 주문을 취소하는 함수
    
    Args:
        order_id: 취소할 주문의 ID
    
    Returns:
        bool: 취소 성공 여부
    """
    global AutoOrderList
    DIST = Common.GetNowDist()
    
    try:
        # 주문 리스트에서 해당 ID를 가진 주문 찾기
        order_to_remove = None
        for order in AutoOrderList:
            if order.get('OrderId') == order_id and order.get('AccountType') == DIST:
                order_to_remove = order
                break
        
        if order_to_remove is None:
            msg = DIST + f" 주문 ID {order_id}를 찾을 수 없습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return False
        
        # 주문을 리스트에서 완전히 제거
        AutoOrderList.remove(order_to_remove)
        
        # 파일에 저장
        with open(auto_order_file_path, 'w') as outfile:
            fcntl.flock(outfile, fcntl.LOCK_EX)
            json.dump(AutoOrderList, outfile)
            fcntl.flock(outfile, fcntl.LOCK_UN)
        
        msg = DIST + f" 주문 ID {order_id}가 성공적으로 취소되었습니다."
        print(msg)
        line_alert.SendMessage(msg)
        return True
        
    except Exception as e:
        msg = DIST + f" 주문 ID {order_id} 취소 중 오류 발생: {str(e)}"
        print(msg)
        line_alert.SendMessage(msg)
        return False

# 종목별 주문 취소 함수
def CancelOrderByTicker(stock_code, order_type="All", with_limit_orders=False):
    """
    종목코드로 해당 종목의 주문을 취소하는 함수
    
    Args:
        stock_code: 취소할 주문의 종목코드 (예: "005930")
        order_type: 취소할 주문 유형 ("All", "StopBuy", "StopSell", "ProfitSell", "TrailingStopBuy", "TrailingStopSell" ,"StopLoss", "TrailingStopLoss")
        with_limit_orders: 실제 거래소의 지정가 주문도 함께 취소할지 여부
    
    Returns:
        int: 취소된 주문 개수
    """
    global AutoOrderList
    DIST = Common.GetNowDist()
    
    try:
        if with_limit_orders == True:
            # 실제 거래소의 해당 종목 주문 취소
            KisKR.CancelAllOrders(stock_code)
        
        # 해당 종목의 주문 찾기 (주문 유형 필터링)
        orders_to_remove = []
        for order in AutoOrderList:
            if order.get('stock_code') == stock_code and order.get('AccountType') == DIST:
                if order_type == "All" or order.get('OrderType') == order_type:
                    orders_to_remove.append(order)
        
        if not orders_to_remove:
            order_type_msg = "모든" if order_type == "All" else order_type
            msg = DIST + f" 종목 {stock_code}의 {order_type_msg} 주문을 찾을 수 없습니다."
            print(msg)
            #line_alert.SendMessage(msg)
            return 0
        
        # 주문들을 리스트에서 완전히 제거
        for order in orders_to_remove:
            AutoOrderList.remove(order)
        
        # 파일에 저장
        with open(auto_order_file_path, 'w') as outfile:
            fcntl.flock(outfile, fcntl.LOCK_EX)
            json.dump(AutoOrderList, outfile)
            fcntl.flock(outfile, fcntl.LOCK_UN)
        
        canceled_count = len(orders_to_remove)
        order_type_msg = "모든" if order_type == "All" else order_type
        msg = DIST + f" 종목 {stock_code}의 {order_type_msg} 주문 {canceled_count}개가 성공적으로 취소되었습니다."
        print(msg)
        line_alert.SendMessage(msg)
        return canceled_count
        
    except Exception as e:
        msg = DIST + f" 종목 {stock_code} 주문 취소 중 오류 발생: {str(e)}"
        print(msg)
        line_alert.SendMessage(msg)
        return 0





# 스탑 매수 주문 함수
def MakeStopBuyOrder(stock_code, order_volume, stop_price, Exclusive=False):
    global AutoOrderList
    global IsMarketOpen
    
    DIST = Common.GetNowDist()
    
    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None
    
    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "StopBuy" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 스탑 매수 주문이 실행 중이라 현재 진행 중인 스탑 매수가 끝날 때 까지 추가 스탑 매수 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)

    if order_volume < minimumVolume:
        order_volume = minimumVolume

    # 주문 ID 생성
    order_id = generate_order_id("StopBuy", stock_code)

    # 스탑 매수 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "StopBuy"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['OrderVolume'] = order_volume
    AutoStopData['StopPrice'] = stop_price

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 스탑 매수 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "주문 수량: " + str(order_volume) + "주\n"
    msg += "스탑 가격: " + str(stop_price) + "원\n"
    msg += "현재 가격: " + str(nowPrice) + "원"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id

# 스탑 매도 주문 함수
def MakeStopSellOrder(stock_code, order_volume, stop_price, Exclusive=False, CancelLimitOrders=False):
    global AutoOrderList
    global IsMarketOpen

    DIST = Common.GetNowDist()

    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None

    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "StopSell" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 스탑 매도 주문이 실행 중이라 현재 진행중인 스탑 매도가 끝날 때 까지 추가 스탑 매도 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)

    if order_volume < minimumVolume:
        order_volume = minimumVolume

    # 주문 ID 생성
    order_id = generate_order_id("StopSell", stock_code)

    # 스탑 매도 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "StopSell"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['OrderVolume'] = order_volume
    AutoStopData['StopPrice'] = stop_price
    AutoStopData['CancelLimitOrders'] = CancelLimitOrders

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 스탑 매도 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "주문 수량: " + str(order_volume) + "주\n"
    msg += "스탑 가격: " + str(stop_price) + "원\n"
    msg += "현재 가격: " + str(nowPrice) + "원"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id

# 익절 매도 주문 함수
def MakeProfitSellOrder(stock_code, order_volume, profit_price, Exclusive=False, CancelLimitOrders=False):
    global AutoOrderList
    global IsMarketOpen

    DIST = Common.GetNowDist()

    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None

    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "ProfitSell" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 익절 매도 주문이 실행 중이라 현재 진행중인 익절 매도가 끝날 때 까지 추가 익절 매도 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)

    if order_volume < minimumVolume:
        order_volume = minimumVolume

    # 주문 ID 생성
    order_id = generate_order_id("ProfitSell", stock_code)

    # 익절 매도 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "ProfitSell"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['OrderVolume'] = order_volume
    AutoStopData['ProfitPrice'] = profit_price
    AutoStopData['CancelLimitOrders'] = CancelLimitOrders

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 익절 매도 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "주문 수량: " + str(order_volume) + "주\n"
    msg += "익절 가격: " + str(profit_price) + "원\n"
    msg += "현재 가격: " + str(nowPrice) + "원"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id

# 트레일링 스탑 매수 주문 함수
def MakeTrailingStopBuyOrder(stock_code, order_volume, trailing_percent, activation_price=None, Exclusive=False):
    global AutoOrderList
    global IsMarketOpen
    
    DIST = Common.GetNowDist()
    
    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None
    
    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "TrailingStopBuy" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 트레일링 스탑 매수 주문이 실행 중이라 현재 진행 중인 트레일링 스탑 매수가 끝날 때 까지 추가 트레일링 스탑 매수 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)

    if order_volume < minimumVolume:
        order_volume = minimumVolume

    # 주문 ID 생성
    order_id = generate_order_id("TrailingStopBuy", stock_code)

    # 트레일링 스탑 매수 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "TrailingStopBuy"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['OrderVolume'] = order_volume
    AutoStopData['TrailingPercent'] = float(trailing_percent)  # 실수형으로 변환
    
    # 활성화 가격 설정
    if activation_price is not None:
        AutoStopData['ActivationPrice'] = activation_price
        AutoStopData['LowestPrice'] = nowPrice  # 현재가로 시작 (활성화 전 플레이스홀더)
        AutoStopData['IsActivated'] = False  # 아직 활성화되지 않음
    else:
        AutoStopData['LowestPrice'] = nowPrice  # 현재가로 시작
        AutoStopData['IsActivated'] = True  # 즉시 활성화

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 트레일링 스탑 매수 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "주문 수량: " + str(order_volume) + "주\n"
    msg += "트레일링 퍼센트: " + str(trailing_percent) + "%\n"
    msg += "현재 가격: " + str(nowPrice) + "원"
    if activation_price is not None:
        msg += "\n활성화 가격: " + str(activation_price) + "원"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id

# 트레일링 스탑 매도 주문 함수
def MakeTrailingStopSellOrder(stock_code, order_volume, trailing_percent, activation_price=None, Exclusive=False, CancelLimitOrders=False):
    global AutoOrderList
    global IsMarketOpen

    DIST = Common.GetNowDist()

    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None

    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "TrailingStopSell" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 트레일링 스탑 매도 주문이 실행 중이라 현재 진행중인 트레일링 스탑 매도가 끝날 때 까지 추가 트레일링 스탑 매도 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)

    if order_volume < minimumVolume:
        order_volume = minimumVolume

    # 주문 ID 생성
    order_id = generate_order_id("TrailingStopSell", stock_code)

    # 트레일링 스탑 매도 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "TrailingStopSell"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['OrderVolume'] = order_volume
    AutoStopData['TrailingPercent'] = float(trailing_percent)  # 실수형으로 변환
    
    # 활성화 가격 설정
    if activation_price is not None:
        AutoStopData['ActivationPrice'] = activation_price
        AutoStopData['HighestPrice'] = nowPrice  # 현재가로 시작 (활성화 전 플레이스홀더)
        AutoStopData['IsActivated'] = False  # 아직 활성화되지 않음
    else:
        AutoStopData['HighestPrice'] = nowPrice  # 현재가로 시작
        AutoStopData['IsActivated'] = True  # 즉시 활성화
    
    AutoStopData['CancelLimitOrders'] = CancelLimitOrders

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 트레일링 스탑 매도 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "주문 수량: " + str(order_volume) + "주\n"
    msg += "트레일링 퍼센트: " + str(trailing_percent) + "%\n"
    msg += "현재 가격: " + str(nowPrice) + "원"
    if activation_price is not None:
        msg += "\n활성화 가격: " + str(activation_price) + "원"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id

# 스탑로스 주문 함수 (해당 티커의 보유수량 전부 정리)
def MakeStopLoss(stock_code, stop_price, Exclusive=False):
    global AutoOrderList
    global IsMarketOpen

    DIST = Common.GetNowDist()

    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None

    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "StopLoss" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 스탑로스 주문이 실행 중이라 현재 진행중인 스탑로스가 끝날 때 까지 추가 스탑로스 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)



    # 주문 ID 생성
    order_id = generate_order_id("StopLoss", stock_code)

    # 스탑로스 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "StopLoss"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['StopPrice'] = stop_price
    AutoStopData['CancelLimitOrders'] = True  # 자동으로 True 설정

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 스탑로스 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "스탑 가격: " + str(stop_price) + "원\n"
    msg += "현재 가격: " + str(nowPrice) + "원\n"
    msg += "지정가 주문 자동 취소: 활성화"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id 

# 트레일링 스탑로스 주문 함수 (해당 종목의 보유수량 전부 정리)
def MakeTrailingStopLoss(stock_code, trailing_percent, activation_price=None, Exclusive=False):
    global AutoOrderList
    global IsMarketOpen

    DIST = Common.GetNowDist()

    if IsMarketOpen == False:
        time.sleep(1.0)
        IsMarketOpen = KisKR.IsMarketOpen()
        if IsMarketOpen == False:
            msg = "현재 시장이 마감되었습니다. 주문을 처리하지 않습니다."
            print(msg)
            line_alert.SendMessage(msg)
            return None

    if Exclusive == True:
        for AutoStopData in AutoOrderList:
            if AutoStopData['OrderType'] == "TrailingStopLoss" and AutoStopData['AccountType'] == DIST:
                if AutoStopData['stock_code'] == stock_code:
                    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 독점 트레일링 스탑로스 주문이 실행 중이라 현재 진행중인 트레일링 스탑로스가 끝날 때 까지 추가 트레일링 스탑로스 주문은 처리하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    return None

    nowPrice = KisKR.GetCurrentPrice(stock_code)
    time.sleep(0.1)

    # 주문 ID 생성
    order_id = generate_order_id("TrailingStopLoss", stock_code)

    # 트레일링 스탑로스 데이터 생성
    AutoStopData = dict()
    AutoStopData['OrderId'] = order_id
    AutoStopData['AccountType'] = DIST
    AutoStopData['OrderType'] = "TrailingStopLoss"
    AutoStopData['stock_code'] = stock_code
    AutoStopData['TrailingPercent'] = float(trailing_percent)  # 실수형으로 변환
    AutoStopData['CancelLimitOrders'] = True  # 자동으로 True 설정
    
    # 활성화 가격 설정
    if activation_price is not None:
        AutoStopData['ActivationPrice'] = activation_price
        AutoStopData['HighestPrice'] = nowPrice  # 현재가로 시작 (활성화 전 플레이스홀더)
        AutoStopData['IsActivated'] = False  # 아직 활성화되지 않음
    else:
        AutoStopData['HighestPrice'] = nowPrice  # 현재가로 시작
        AutoStopData['IsActivated'] = True  # 즉시 활성화

    # 데이터를 리스트에 추가하고 저장
    AutoOrderList.append(AutoStopData)
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)

    msg = DIST + " " + stock_code + " " + KisKR.GetStockName(stock_code) + " 트레일링 스탑로스 주문이 등록되었습니다.\n"
    msg += "주문 ID: " + order_id + "\n"
    msg += "트레일링 퍼센트: " + str(trailing_percent) + "%\n"
    msg += "현재 가격: " + str(nowPrice) + "원"
    if activation_price is not None:
        msg += "\n활성화 가격: " + str(activation_price) + "원"
    msg += "\n지정가 주문 자동 취소: 활성화"
    print(msg)
    line_alert.SendMessage(msg)
    
    return order_id
