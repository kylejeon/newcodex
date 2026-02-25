import time

import requests

TOKEN = '8247347427:AAFnw2cxJrHMkiagOQucrtcSwEnGIAh7dv0'
CHAT_ID = 1050566686  # 여러분의 챗ID값으로 변경!!!
SEND_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def SendMessage(msg):
    for i in range(3):
        try:
            resp = requests.post(
                SEND_URL,
                json={"chat_id": CHAT_ID, "text": str(msg)},
                timeout=5,
            )
            if resp.status_code == 200:
                return
            raise RuntimeError(f"HTTP {resp.status_code} {resp.text}")
        except Exception as ex:
            if i == 2:
                print("telegram send failed:", ex)
                return
            time.sleep(0.4 + (0.4 * i))
