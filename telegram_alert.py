import time

import requests

TOKEN = '8247347427:AAFnw2cxJrHMkiagOQucrtcSwEnGIAh7dv0'
CHAT_ID = 1050566686  # 여러분의 챗ID값으로 변경!!!
SEND_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
TIMEOUT = (3.5, 15)
MAX_RETRIES = 4
DEDUP_WINDOW_SEC = 20
_LAST_SENT = {}


def SendMessage(msg):
    text = str(msg)
    now_ts = time.time()
    last_ts = _LAST_SENT.get(text)
    if last_ts is not None and (now_ts - last_ts) < DEDUP_WINDOW_SEC:
        return

    for i in range(MAX_RETRIES):
        try:
            resp = requests.post(
                SEND_URL,
                json={"chat_id": CHAT_ID, "text": text},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                _LAST_SENT[text] = time.time()
                return
            raise RuntimeError(f"HTTP {resp.status_code} {resp.text}")
        except Exception as ex:
            if i == (MAX_RETRIES - 1):
                print("telegram send failed:", ex)
                return
            time.sleep(0.7 + (0.8 * i))
