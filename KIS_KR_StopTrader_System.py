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
import json
import random
import fcntl
import line_alert

from tendo import singleton 
me = singleton.SingleInstance()

#장이 열린지 여부 판단을 위한 계좌 정보로 현재 자동매매중인 계좌명 아무거나 넣으면 됩니다.
Common.SetChangeMode("REAL3") #즉 다계좌 매매로 REAL, REAL2, REAL3 여러개를 자동매매 해도 한개만 여기 넣으면 됨!

time.sleep(30.0) #스플릿 트레이더와 중복을 피하기 위해! 30초 대기!


IsMarketOpen = KisKR.IsMarketOpen()

auto_order_file_path = "/var/autobot/KIS_KR_StopTrader_AutoOrderList.json"
time.sleep(random.random()*0.1)

#지정가 주문을 읽고 필요 수량만큼 취소하는 함수
def CancelLimitOrdersForQuantity(stock_code, target_quantity):
    """
    지정가 주문을 읽고 목표 수량만큼 취소하는 함수
    
    Args:
        stock_code: 주식 종목 코드 (예: "005930")
        target_quantity: 목표 취소 수량
    
    Returns:
        float: 실제 취소된 수량
    """
    canceled_quantity = 0.0  # 취소된 주문의 총 수량을 추적
    
    try:
        # 해당 종목의 모든 주문 정보를 가져옵니다 (매도 주문만)
        orders_data = KisKR.GetOrderList(stock_code, side="SELL", status="OPEN")
        
        if len(orders_data) > 0:
            for order in orders_data:
                # 필요한 수량이 확보되었는지 확인
                if canceled_quantity >= target_quantity:
                    print(f"목표 수량 {target_quantity} 확보 완료. 추가 주문 취소 중단")
                    break
                
                # 지정가 매도 주문이고 상태가 'Open'인 경우만 취소
                if order['OrderSide'] == 'Sell' and order['OrderType'] == 'Limit' and order['OrderSatus'] == 'Open':
                    remaining_quantity = float(order['OrderAmt'])
                    
                    # 주문 취소
                    try:
                        KisKR.CancelModifyOrder(stock_code, order['OrderNum'], order['OrderNum2'], 
                                              remaining_quantity, order['OrderAvgPrice'], mode="CANCEL")
                        canceled_quantity += remaining_quantity
                        print(f"주문 취소: {order['OrderNum']}-{order['OrderNum2']}, 수량: {remaining_quantity}, 누적 취소 수량: {canceled_quantity}")
                        time.sleep(0.1)  # API 호출 제한 방지
                    except Exception as e:
                        print(f"주문 취소 실패: {order['OrderNum']}-{order['OrderNum2']}, 에러: {e}")
        
        print(f"총 취소된 수량: {canceled_quantity}, 목표 수량: {target_quantity}")
        
    except Exception as e:
        print(f"주문 정보 조회 실패: {e}")
    
    return canceled_quantity

#자동 주문 리스트 읽기!
AutoOrderList = list()
try:
    with open(auto_order_file_path, 'r') as json_file:
        fcntl.flock(json_file, fcntl.LOCK_EX)  # 파일 락 설정
        AutoOrderList = json.load(json_file)
        fcntl.flock(json_file, fcntl.LOCK_UN)  # 파일 락 해제
except Exception as e:
    print("Exception by First:", e)

# 스탑로스가 실행된 종목들을 추적하는 리스트
stop_loss_executed_tickers = []

#장이 열린 상황에서만!
if IsMarketOpen == True:
    print("장이 열린 상황")

    items_to_remove = list()

    #저장된 스탑 주문 데이터를 순회한다 
    for AutoStopData in AutoOrderList:
        
        #계좌 세팅!
        Common.SetChangeMode(AutoStopData.get('AccountType', 'REAL'))
        DIST = Common.GetNowDist()
        stock_code = AutoStopData['stock_code']
        stock_name = KisKR.GetStockName(stock_code)

        # 스탑 매수 주문 처리
        if AutoStopData['OrderType'] == "StopBuy":

            stop_price = AutoStopData['StopPrice']
            order_volume = AutoStopData['OrderVolume']
            
            # 현재가 조회
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.1)
            
            # 스탑 가격에 도달했는지 확인
            if nowPrice >= stop_price:
                # 스탑 매수 실행
                data = KisKR.MakeBuyMarketOrder(stock_code, order_volume)
                print(data)
                
                msg = DIST + " " + stock_code + " " + stock_name + " 스탑 매수 주문이 실행되었습니다.\n"
                msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                msg += "주문 수량: " + str(order_volume) + "주\n"
                msg += "스탑 가격: " + str(stop_price) + "원\n"
                msg += "현재 가격: " + str(nowPrice) + "원"
                print(msg)
                line_alert.SendMessage(msg)
                
                # 주문 완료 후 리스트에서 제거
                items_to_remove.append(AutoStopData)

        # 스탑 매도 주문 처리
        elif AutoStopData['OrderType'] == "StopSell":

            stop_price = AutoStopData['StopPrice']
            order_volume = AutoStopData['OrderVolume']
            cancel_limit_orders = AutoStopData.get('CancelLimitOrders', False)
            
            # 현재가 조회
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.1)
            
            # 스탑 가격에 도달했는지 확인
            if nowPrice <= stop_price:
                # 지정가 주문 취소 옵션이 있으면 실행
                if cancel_limit_orders:
                    # 현재 매도 가능 수량 확인
                    balances = KisKR.GetMyStockList()
                    free_quantity = 0
                    for balance in balances:
                        if balance['StockCode'] == stock_code:
                            free_quantity = float(balance['StockAmt'])
                            break
                    
                    # 부족한 수량 계산
                    need_quantity = order_volume - free_quantity
                    
                    # 부족한 수량만큼 지정가 주문 취소
                    if need_quantity > 0:
                        canceled_quantity = CancelLimitOrdersForQuantity(stock_code, need_quantity)
                        if canceled_quantity > 0:
                            msg = DIST + " " + stock_code + " " + stock_name + " 스탑 매도 전 지정가 주문 취소 완료. 취소 수량: " + str(canceled_quantity)
                            print(msg)
                            line_alert.SendMessage(msg)
                            time.sleep(0.1)
                
                # 스탑 매도 실행
                data = KisKR.MakeSellMarketOrder(stock_code, order_volume)
                print(data)
                
                msg = DIST + " " + stock_code + " " + stock_name + " 스탑 매도 주문이 실행되었습니다.\n"
                msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                msg += "주문 수량: " + str(order_volume) + "주\n"
                msg += "스탑 가격: " + str(stop_price) + "원\n"
                msg += "현재 가격: " + str(nowPrice) + "원"
                print(msg)
                line_alert.SendMessage(msg)
                
                # 주문 완료 후 리스트에서 제거
                items_to_remove.append(AutoStopData)

        # 익절 매도 주문 처리
        elif AutoStopData['OrderType'] == "ProfitSell":

            profit_price = AutoStopData['ProfitPrice']
            order_volume = AutoStopData['OrderVolume']
            cancel_limit_orders = AutoStopData.get('CancelLimitOrders', False)
            
            # 현재가 조회
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.1)
            
            # 익절 가격에 도달했는지 확인
            if nowPrice >= profit_price:
                # 지정가 주문 취소 옵션이 있으면 실행
                if cancel_limit_orders:
                    # 현재 매도 가능 수량 확인
                    balances = KisKR.GetMyStockList()
                    free_quantity = 0
                    for balance in balances:
                        if balance['StockCode'] == stock_code:
                            free_quantity = float(balance['StockAmt'])
                            break
                    
                    # 부족한 수량 계산
                    need_quantity = order_volume - free_quantity
                    
                    # 부족한 수량만큼 지정가 주문 취소
                    if need_quantity > 0:
                        canceled_quantity = CancelLimitOrdersForQuantity(stock_code, need_quantity)
                        if canceled_quantity > 0:
                            msg = DIST + " " + stock_code + " " + stock_name + " 익절 매도 전 지정가 주문 취소 완료. 취소 수량: " + str(canceled_quantity)
                            print(msg)
                            line_alert.SendMessage(msg)
                            time.sleep(0.1)
                
                # 익절 매도 실행
                data = KisKR.MakeSellMarketOrder(stock_code, order_volume)
                print(data)
                
                msg = DIST + " " + stock_code + " " + stock_name + " 익절 매도 주문이 실행되었습니다.\n"
                msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                msg += "주문 수량: " + str(order_volume) + "주\n"
                msg += "익절 가격: " + str(profit_price) + "원\n"
                msg += "현재 가격: " + str(nowPrice) + "원"
                print(msg)
                line_alert.SendMessage(msg)
                
                # 주문 완료 후 리스트에서 제거
                items_to_remove.append(AutoStopData)

        # 트레일링 스탑 매수 주문 처리
        elif AutoStopData['OrderType'] == "TrailingStopBuy":
            print(AutoStopData)
            
            order_volume = AutoStopData['OrderVolume']
            trailing_percent = AutoStopData['TrailingPercent']
            lowest_price = AutoStopData['LowestPrice']
            is_activated = AutoStopData.get('IsActivated', True)
            activation_price = AutoStopData.get('ActivationPrice')
            
            # 현재가 조회
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.1)
            
            # 활성화 가격이 설정되어 있고 아직 활성화되지 않았다면
            if activation_price is not None and not is_activated:
                if nowPrice <= activation_price:
                    AutoStopData['IsActivated'] = True
                    AutoStopData['LowestPrice'] = nowPrice
                    is_activated = True
                    print(f"트레일링 스탑 매수 활성화: {stock_code}, 활성화 가격: {activation_price}")
            # 활성화 가격이 None인 경우 즉시 활성화
            elif activation_price is None and not is_activated:
                AutoStopData['IsActivated'] = True
                AutoStopData['LowestPrice'] = nowPrice
                is_activated = True
                print(f"트레일링 스탑 매수 즉시 활성화: {stock_code} (ActivationPrice: None)")
            
            # 활성화된 상태에서만 트레일링 로직 실행
            if is_activated:
                # 최저가 업데이트
                if nowPrice < lowest_price:
                    AutoStopData['LowestPrice'] = nowPrice
                    lowest_price = nowPrice
                
                # 트레일링 스탑 가격 계산
                trailing_stop_price = lowest_price * (1 + trailing_percent / 100)
                
                # 현재가가 트레일링 스탑 가격에 도달했는지 확인
                if nowPrice >= trailing_stop_price:
                    # 트레일링 스탑 매수 실행
                    data = KisKR.MakeBuyMarketOrder(stock_code, order_volume)
                    print(data)
                    
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑 매수 주문이 실행되었습니다.\n"
                    msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                    msg += "주문 수량: " + str(order_volume) + "주\n"
                    msg += "트레일링 퍼센트: " + str(trailing_percent) + "%\n"
                    msg += "최저가: " + str(lowest_price) + "원\n"
                    msg += "트레일링 스탑 가격: " + str(trailing_stop_price) + "원\n"
                    msg += "현재 가격: " + str(nowPrice) + "원"
                    print(msg)
                    line_alert.SendMessage(msg)
                    
                    # 주문 완료 후 리스트에서 제거
                    items_to_remove.append(AutoStopData)

        # 트레일링 스탑 매도 주문 처리
        elif AutoStopData['OrderType'] == "TrailingStopSell":
            print(AutoStopData)
            
            order_volume = AutoStopData['OrderVolume']
            trailing_percent = AutoStopData['TrailingPercent']
            highest_price = AutoStopData['HighestPrice']
            is_activated = AutoStopData.get('IsActivated', True)
            activation_price = AutoStopData.get('ActivationPrice')
            cancel_limit_orders = AutoStopData.get('CancelLimitOrders', False)
            
            # 현재가 조회
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.1)
            
            # 활성화 가격이 설정되어 있고 아직 활성화되지 않았다면
            if activation_price is not None and not is_activated:
                if nowPrice <= activation_price:
                    AutoStopData['IsActivated'] = True
                    AutoStopData['HighestPrice'] = nowPrice
                    is_activated = True
                    print(f"트레일링 스탑 매도 활성화: {stock_code}, 활성화 가격: {activation_price}")
            # 활성화 가격이 None인 경우 즉시 활성화
            elif activation_price is None and not is_activated:
                AutoStopData['IsActivated'] = True
                AutoStopData['HighestPrice'] = nowPrice
                is_activated = True
                print(f"트레일링 스탑 매도 즉시 활성화: {stock_code} (ActivationPrice: None)")
            
            # 활성화된 상태에서만 트레일링 로직 실행
            if is_activated:
                # 최고가 업데이트
                if nowPrice > highest_price:
                    AutoStopData['HighestPrice'] = nowPrice
                    highest_price = nowPrice
                
                # 트레일링 스탑 가격 계산
                trailing_stop_price = highest_price * (1 - trailing_percent / 100)
                
                # 현재가가 트레일링 스탑 가격에 도달했는지 확인
                if nowPrice <= trailing_stop_price:
                    # 지정가 주문 취소 옵션이 있으면 실행
                    if cancel_limit_orders:
                        # 현재 매도 가능 수량 확인
                        balances = KisKR.GetMyStockList()
                        free_quantity = 0
                        for balance in balances:
                            if balance['StockCode'] == stock_code:
                                free_quantity = float(balance['StockAmt'])
                                break
                        
                        # 부족한 수량 계산
                        need_quantity = order_volume - free_quantity
                        
                        # 부족한 수량만큼 지정가 주문 취소
                        if need_quantity > 0:
                            canceled_quantity = CancelLimitOrdersForQuantity(stock_code, need_quantity)
                            if canceled_quantity > 0:
                                msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑 매도 전 지정가 주문 취소 완료. 취소 수량: " + str(canceled_quantity)
                                print(msg)
                                line_alert.SendMessage(msg)
                                time.sleep(0.1)
                    
                    # 트레일링 스탑 매도 실행
                    data = KisKR.MakeSellMarketOrder(stock_code, order_volume)
                    print(data)
                    
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑 매도 주문이 실행되었습니다.\n"
                    msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                    msg += "주문 수량: " + str(order_volume) + "주\n"
                    msg += "트레일링 퍼센트: " + str(trailing_percent) + "%\n"
                    msg += "최고가: " + str(highest_price) + "원\n"
                    msg += "트레일링 스탑 가격: " + str(trailing_stop_price) + "원\n"
                    msg += "현재 가격: " + str(nowPrice) + "원"
                    print(msg)
                    line_alert.SendMessage(msg)
                    
                    # 주문 완료 후 리스트에서 제거
                    items_to_remove.append(AutoStopData)

        # 스탑로스 주문 처리 (보유수량 전부 정리)
        elif AutoStopData['OrderType'] == "StopLoss":
            print(AutoStopData)
            
            
            stop_price = AutoStopData['StopPrice']
            
            # 현재가 조회
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.1)
            
            # 스탑 가격에 도달했는지 확인
            if nowPrice <= stop_price:


                KisKR.CancelAllOrders(stock_code)
                time.sleep(0.5)
                
                # 현재 매도 가능 수량 확인
                balances = KisKR.GetMyStockList()
                FreeAmt = 0
                for balance in balances:
                    if balance['StockCode'] == stock_code:
                        FreeAmt = float(balance['StockAmt'])
                        break
                                # 보유수량이 0이면 주문하지 않음
                if FreeAmt <= 0:
                    msg = DIST + " " + stock_code + " 보유수량이 0이므로 스탑로스 주문을 실행하지 않습니다."
                    print(msg)
                    line_alert.SendMessage(msg)
                    items_to_remove.append(AutoStopData)
                    continue
                
                # 스탑로스 실행 (보유수량 전부 매도)
                data = KisKR.MakeSellMarketOrder(stock_code, FreeAmt)
                print(data)
                
                msg = DIST + " " + stock_code + " " + stock_name + " 스탑로스 주문이 실행되었습니다.\n"
                msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                msg += "매도 수량: " + str(FreeAmt) + "주\n"
                msg += "스탑 가격: " + str(stop_price) + "원\n"
                msg += "현재 가격: " + str(nowPrice) + "원\n"
                msg += "보유수량 전부 정리 완료"
                print(msg)
                line_alert.SendMessage(msg)
                
                # 주문 완료 후 리스트에서 제거
                items_to_remove.append(AutoStopData)
                
                # 스탑로스가 실행된 종목을 추적 리스트에 추가
                stop_loss_executed_tickers.append(stock_code)

        # 트레일링 스탑로스 처리 (보유수량 전부 정리)
        elif AutoStopData['OrderType'] == "TrailingStopLoss":
            nowPrice = KisKR.GetCurrentPrice(stock_code)
            time.sleep(0.2)
            
            # 활성화 여부 확인
            if AutoStopData.get('IsActivated', True) == False:
                activation_price = AutoStopData.get('ActivationPrice')
                # 활성화 가격이 설정되어 있고 해당 가격에 도달한 경우
                if activation_price is not None and nowPrice >= activation_price:
                    AutoStopData['IsActivated'] = True
                    AutoStopData['HighestPrice'] = nowPrice
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑로스가 활성화되었습니다. 활성화 가격: " + str(nowPrice)
                    print(msg)
                    line_alert.SendMessage(msg)
                # 활성화 가격이 None인 경우 즉시 활성화
                elif activation_price is None:
                    AutoStopData['IsActivated'] = True
                    AutoStopData['HighestPrice'] = nowPrice
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑로스가 즉시 활성화되었습니다. (ActivationPrice: None)"
                    print(msg)
                    line_alert.SendMessage(msg)
                else:
                    # 아직 활성화되지 않았으면 다음 체크로
                    continue
            
            # 활성화된 경우 최고가 업데이트
            if AutoStopData.get('IsActivated', True) == True:
                if nowPrice > AutoStopData['HighestPrice']:
                    AutoStopData['HighestPrice'] = nowPrice
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑로스 최고가 업데이트: " + str(nowPrice)
                    print(msg)
                    line_alert.SendMessage(msg)
            
            # 트레일링 스탑 가격 계산 (최고가 대비 n% 하락)
            trailing_stop_price = AutoStopData['HighestPrice'] * (1 - AutoStopData['TrailingPercent'] / 100)
            
            # 현재 가격이 트레일링 스탑 가격 이하이면 매도 실행
            if nowPrice <= trailing_stop_price:
                try:
                    KisKR.CancelAllOrders(stock_code)
                    time.sleep(0.5)

                    # 현재 매도 가능 수량 확인
                    balances = KisKR.GetMyStockList()
                    FreeAmt = 0
                    for balance in balances:
                        if balance['StockCode'] == stock_code:
                            FreeAmt = float(balance['StockAmt'])
                            break
                    
                    # 보유수량이 0이면 주문하지 않음
                    if FreeAmt <= 0:
                        msg = DIST + " " + stock_code + " " + stock_name + " 보유수량이 0이므로 트레일링 스탑로스 주문을 실행하지 않습니다."
                        print(msg)
                        line_alert.SendMessage(msg)
                        items_to_remove.append(AutoStopData)
                        continue
                    
                    # 매도 주문 실행 (보유수량 전부)
                    KisKR.MakeSellMarketOrder(stock_code, FreeAmt)
                    time.sleep(0.2)
                    
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑로스 주문이 실행되었습니다.\n"
                    msg += "주문 ID: " + AutoStopData['OrderId'] + "\n"
                    msg += "매도 수량: " + str(FreeAmt) + "주\n"
                    msg += "실행 가격: " + str(nowPrice) + "원\n"
                    msg += "최고가: " + str(AutoStopData['HighestPrice']) + "원\n"
                    msg += "트레일링 스탑 가격: " + str(trailing_stop_price) + "원\n"
                    msg += "보유수량 전부 정리 완료"
                    print(msg)
                    line_alert.SendMessage(msg)
                    
                    # 주문 완료 후 리스트에서 제거
                    items_to_remove.append(AutoStopData)
                    
                    # 트레일링 스탑로스가 실행된 종목을 추적 리스트에 추가
                    stop_loss_executed_tickers.append(stock_code)
                    
                except Exception as e:
                    msg = DIST + " " + stock_code + " " + stock_name + " 트레일링 스탑로스 주문 실행 중 오류 발생: " + str(e)
                    print(msg)
                    line_alert.SendMessage(msg)
                    items_to_remove.append(AutoStopData)

    # 스탑로스가 실행된 종목의 모든 스탑트레이더 주문 삭제
    for ticker in stop_loss_executed_tickers:
        for AutoStopData in AutoOrderList:
            if AutoStopData['stock_code'] == ticker and AutoStopData not in items_to_remove:
                msg = DIST + " " + ticker + " " + KisKR.GetStockName(ticker) + " 스탑로스 실행으로 인한 관련 주문 삭제: " + AutoStopData['OrderType']
                print(msg)
                line_alert.SendMessage(msg)
                items_to_remove.append(AutoStopData)

    # 스탑로스 실행 후 추가 보유수량 확인 및 매도
    for ticker in stop_loss_executed_tickers:
        try:

            KisKR.CancelAllOrders(ticker)
            time.sleep(0.5)

            # 추가 보유수량 확인
            balances = KisKR.GetMyStockList()
            additional_balance = 0
            for balance in balances:
                if balance['StockCode'] == ticker:
                    additional_balance = float(balance['StockAmt'])
                    break
            time.sleep(0.1)
            
            if additional_balance > 0:
                # 추가 보유수량 매도
                data = KisKR.MakeSellMarketOrder(ticker, additional_balance)
                print(data)
                time.sleep(0.1)
                
                msg = DIST + " " + ticker + " " + KisKR.GetStockName(ticker) + " 스탑로스 후 추가 보유수량 발견 및 매도 완료: " + str(additional_balance) + "주"
                print(msg)
                line_alert.SendMessage(msg)
        except Exception as e:
            msg = DIST + " " + ticker + " " + KisKR.GetStockName(ticker) + " 스탑로스 후 추가 보유수량 확인/매도 중 오류: " + str(e)
            print(msg)
            line_alert.SendMessage(msg)

    # 완료된 주문들을 리스트에서 제거
    for item in items_to_remove:
        AutoOrderList.remove(item)


    time.sleep(random.random()*0.1)
    #파일에 저장
    with open(auto_order_file_path, 'w') as outfile:
        fcntl.flock(outfile, fcntl.LOCK_EX)
        json.dump(AutoOrderList, outfile)
        fcntl.flock(outfile, fcntl.LOCK_UN)


else:
    print("장이 마감된 상황") 