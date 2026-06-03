import json
import time

import requests

TOKEN = '8247347427:AAFnw2cxJrHMkiagOQucrtcSwEnGIAh7dv0'
CHAT_ID = 1050566686  # 여러분의 챗ID값으로 변경!!!
API_BASE = f"https://api.telegram.org/bot{TOKEN}"
SEND_URL = f"{API_BASE}/sendMessage"
GETUPDATES_URL = f"{API_BASE}/getUpdates"
ANSWER_CB_URL = f"{API_BASE}/answerCallbackQuery"
TIMEOUT = (3.5, 15)
MAX_RETRIES = 4
DEDUP_WINDOW_SEC = 20
_LAST_SENT = {}


def SendMessage(msg, reply_markup=None):
    text = str(msg)
    now_ts = time.time()
    last_ts = _LAST_SENT.get(text)
    if last_ts is not None and (now_ts - last_ts) < DEDUP_WINDOW_SEC:
        return

    payload = {"chat_id": CHAT_ID, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)

    for i in range(MAX_RETRIES):
        try:
            resp = requests.post(SEND_URL, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                _LAST_SENT[text] = time.time()
                return
            raise RuntimeError(f"HTTP {resp.status_code} {resp.text}")
        except Exception as ex:
            if i == (MAX_RETRIES - 1):
                print("telegram send failed:", ex)
                return
            time.sleep(0.7 + (0.8 * i))


def InlineKeyboard(buttons):
    """buttons: list of rows, each row is list of (text, callback_data).
    Returns dict for reply_markup."""
    return {
        "inline_keyboard": [
            [{"text": b[0], "callback_data": b[1]} for b in row]
            for row in buttons
        ]
    }


def GetUpdates(offset=None, timeout=5):
    """Long-poll for new messages/callbacks. Returns list of updates."""
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(GETUPDATES_URL, params=params, timeout=(3.5, timeout + 5))
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
    except Exception as ex:
        print("getUpdates failed:", ex)
    return []


def AnswerCallback(callback_query_id, text=None):
    """Acknowledge callback button press."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(ANSWER_CB_URL, json=payload, timeout=TIMEOUT)
    except Exception as ex:
        print("answerCallback failed:", ex)
