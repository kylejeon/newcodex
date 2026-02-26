import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR


ROOT = Path(__file__).resolve().parent
KST = ZoneInfo("Asia/Seoul")


def safe_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def main():
    vercel_url = os.getenv("DASHBOARD_VERCEL_URL", "").rstrip("/")
    ingest_token = os.getenv("DASHBOARD_INGEST_TOKEN", "")
    account_mode = os.getenv("ACCOUNT_MODE", "REAL").upper()

    if not vercel_url or not ingest_token:
        raise RuntimeError("Set DASHBOARD_VERCEL_URL and DASHBOARD_INGEST_TOKEN env vars")

    Common.SetChangeMode(account_mode)

    bot_name = f"{account_mode}_MyKospidaq_Bot"
    strategy_path = ROOT / f"KrStock_{bot_name}.json"
    date_path = ROOT / f"KrStock_{bot_name}_Date.json"
    autobot_dir = Path(os.getenv("AUTOBOT_DATA_DIR", str(Path.home() / "autobot")))
    siga_path = autobot_dir / f"KrStock_{bot_name}_TodaySigaLogicDoneDate.json"

    market_open = False
    try:
        market_open = bool(KisKR.IsMarketOpen())
    except Exception:
        pass

    balance = KisKR.GetBalance()
    my_stocks = KisKR.GetMyStockList()
    orders = KisKR.GetOrderList(status="ALL", side="ALL", limit=45)

    if isinstance(balance, str):
        balance = {}
    if isinstance(my_stocks, str):
        my_stocks = []
    if isinstance(orders, str):
        orders = []

    payload = {
        "snapshot": {
            "ts": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "account_mode": account_mode,
            "market_open": market_open,
            "total_money": float(balance.get("TotalMoney", 0.0)),
            "stock_money": float(balance.get("StockMoney", 0.0)),
            "remain_money": float(balance.get("RemainMoney", 0.0)),
            "stock_revenue": float(balance.get("StockRevenue", 0.0)),
            "invest_cnt": int(safe_json(siga_path, {}).get("InvestCnt", 0)),
            "is_cut": bool(safe_json(siga_path, {}).get("IsCut", False)),
            "cut_cnt": int(safe_json(siga_path, {}).get("IsCutCnt", 0)),
            "exposure_rate": float(safe_json(siga_path, {}).get("ExposureRate", 1.0)),
            "peak_money": float(safe_json(siga_path, {}).get("PeakMoney", 0.0)),
        },
        "holdings": my_stocks,
        "orders": orders,
        "strategy_state": safe_json(strategy_path, []),
        "meta": {
            "date_state": safe_json(date_path, {}),
            "siga_state": safe_json(siga_path, {}),
            "bot_name": bot_name,
        },
    }

    url = f"{vercel_url}/api/ingest"
    r = requests.post(url, json=payload, headers={"x-dashboard-token": ingest_token}, timeout=20)
    print("status:", r.status_code)
    print(r.text)
    r.raise_for_status()


if __name__ == "__main__":
    main()
