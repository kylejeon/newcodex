import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

import KIS_Common as Common
import KIS_API_Helper_KR as KisKR


# -------------------------
# Config
# -------------------------
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard_data"
DATA_DIR.mkdir(exist_ok=True)

SNAPSHOT_CSV = DATA_DIR / "equity_history.csv"
ORDERS_CSV = DATA_DIR / "orders_history.csv"
HOLDINGS_CSV = DATA_DIR / "holdings_history.csv"

st.set_page_config(page_title="Kosdaqpi Bot Dashboard", layout="wide")
st.title("Kosdaqpi Bot Dashboard")


# -------------------------
# Sidebar
# -------------------------
with st.sidebar:
    st.header("설정")
    account_mode = st.selectbox("계좌 모드", ["REAL", "VIRTUAL"], index=0)
    order_lookback_days = st.slider("주문 조회 기간(일)", min_value=5, max_value=180, value=45, step=5)
    refresh_sec = st.slider("자동 새로고침(초)", min_value=0, max_value=60, value=10, step=5)
    if st.button("수동 새로고침"):
        st.rerun()

Common.SetChangeMode(account_mode)

if refresh_sec > 0:
    st.caption(f"자동 새로고침: {refresh_sec}초")
    st.markdown(
        f"""
        <script>
        setTimeout(function() {{ window.location.reload(); }}, {refresh_sec * 1000});
        </script>
        """,
        unsafe_allow_html=True,
    )


# -------------------------
# Helpers
# -------------------------
def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def safe_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def to_df(x):
    if isinstance(x, list):
        return pd.DataFrame(x)
    return pd.DataFrame()


def append_snapshot(balance: dict, market_open: bool, siga: dict):
    row = {
        "ts": now_kst_str(),
        "total_money": float(balance.get("TotalMoney", 0.0)),
        "stock_money": float(balance.get("StockMoney", 0.0)),
        "remain_money": float(balance.get("RemainMoney", 0.0)),
        "stock_revenue": float(balance.get("StockRevenue", 0.0)),
        "market_open": int(bool(market_open)),
        "invest_cnt": int(siga.get("InvestCnt", 0)) if isinstance(siga, dict) else 0,
        "is_cut": int(bool(siga.get("IsCut", False))) if isinstance(siga, dict) else 0,
        "cut_cnt": int(siga.get("IsCutCnt", 0)) if isinstance(siga, dict) else 0,
        "exposure_rate": float(siga.get("ExposureRate", 1.0)) if isinstance(siga, dict) else 1.0,
        "peak_money": float(siga.get("PeakMoney", 0.0)) if isinstance(siga, dict) else 0.0,
    }
    df_new = pd.DataFrame([row])
    if SNAPSHOT_CSV.exists():
        df_old = pd.read_csv(SNAPSHOT_CSV)
        if not df_old.empty and str(df_old.iloc[-1].get("ts", "")) == row["ts"]:
            return
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new
    df_all.to_csv(SNAPSHOT_CSV, index=False)


def append_orders(order_df: pd.DataFrame):
    if order_df.empty:
        return
    c = order_df.copy()
    c["snapshot_ts"] = now_kst_str()
    dedup_cols = ["OrderDate", "OrderTime", "OrderNum", "OrderNum2", "OrderStock", "OrderSide", "OrderAmt"]

    if ORDERS_CSV.exists():
        prev = pd.read_csv(ORDERS_CSV)
        merged = pd.concat([prev, c], ignore_index=True)
        for col in dedup_cols:
            if col not in merged.columns:
                merged[col] = ""
        merged = merged.drop_duplicates(subset=dedup_cols, keep="last")
    else:
        merged = c
    merged.to_csv(ORDERS_CSV, index=False)


def append_holdings(hold_df: pd.DataFrame):
    if hold_df.empty:
        return
    c = hold_df.copy()
    c["snapshot_ts"] = now_kst_str()
    if HOLDINGS_CSV.exists():
        prev = pd.read_csv(HOLDINGS_CSV)
        merged = pd.concat([prev, c], ignore_index=True)
    else:
        merged = c
    merged.to_csv(HOLDINGS_CSV, index=False)


def calc_drawdown(total_series: pd.Series) -> pd.Series:
    if total_series.empty:
        return pd.Series(dtype=float)
    hwm = total_series.cummax()
    return total_series / hwm - 1.0


# -------------------------
# File paths from bot
# -------------------------
bot_name = f"{account_mode}_MyKospidaq_Bot"
strategy_path = ROOT / f"KrStock_{bot_name}.json"
date_path = ROOT / f"KrStock_{bot_name}_Date.json"
autobot_dir = Path(os.getenv("AUTOBOT_DATA_DIR", str(Path.home() / "autobot")))
siga_path = autobot_dir / f"KrStock_{bot_name}_TodaySigaLogicDoneDate.json"

strategy_state = safe_json(strategy_path, [])
date_state = safe_json(date_path, {})
siga_state = safe_json(siga_path, {})


# -------------------------
# API fetch
# -------------------------
api_error = None
market_open = False
balance = {}
my_stocks = []
orders = []

try:
    market_open = bool(KisKR.IsMarketOpen())
    balance = KisKR.GetBalance()
    my_stocks = KisKR.GetMyStockList()
    orders = KisKR.GetOrderList(status="ALL", side="ALL", limit=order_lookback_days)
except Exception as e:
    api_error = str(e)

if isinstance(balance, str):
    api_error = api_error or f"GetBalance 오류: {balance}"
    balance = {}
if isinstance(my_stocks, str):
    api_error = api_error or f"GetMyStockList 오류: {my_stocks}"
    my_stocks = []
if isinstance(orders, str):
    api_error = api_error or f"GetOrderList 오류: {orders}"
    orders = []

hold_df = to_df(my_stocks)
order_df = to_df(orders)
state_df = to_df(strategy_state)

if balance:
    append_snapshot(balance, market_open, siga_state)
if not order_df.empty:
    append_orders(order_df)
if not hold_df.empty:
    append_holdings(hold_df)


# -------------------------
# Top KPIs
# -------------------------
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("조회시각(KST)", now_kst_str())
c2.metric("장 상태", "OPEN" if market_open else "CLOSE")
c3.metric("총 평가금액", f"{int(balance.get('TotalMoney', 0)):,}")
c4.metric("주식 평가금액", f"{int(balance.get('StockMoney', 0)):,}")
c5.metric("예수금", f"{int(balance.get('RemainMoney', 0)):,}")
c6.metric("평가손익", f"{int(balance.get('StockRevenue', 0)):,}")

if api_error:
    st.warning(f"API 경고: {api_error}")


# -------------------------
# Charts
# -------------------------
hist_df = pd.read_csv(SNAPSHOT_CSV) if SNAPSHOT_CSV.exists() else pd.DataFrame()
if not hist_df.empty:
    hist_df["ts"] = pd.to_datetime(hist_df["ts"])
    hist_df = hist_df.sort_values("ts")
    hist_df["drawdown"] = calc_drawdown(hist_df["total_money"])

    left, right = st.columns(2)
    with left:
        st.subheader("총 자산 추이")
        st.line_chart(hist_df.set_index("ts")["total_money"], height=260)
    with right:
        st.subheader("Drawdown 추이")
        st.line_chart((hist_df.set_index("ts")["drawdown"] * 100.0), height=260)

    left2, right2 = st.columns(2)
    with left2:
        st.subheader("Exposure / InvestCnt")
        chart_df = hist_df.set_index("ts")[["exposure_rate", "invest_cnt"]]
        st.line_chart(chart_df, height=240)
    with right2:
        st.subheader("CutCnt / Risk Flag")
        chart_df2 = hist_df.set_index("ts")[["cut_cnt", "is_cut"]]
        st.line_chart(chart_df2, height=240)

    max_dd = float(hist_df["drawdown"].min() * 100.0)
    total_ret = 0.0
    if len(hist_df) > 0 and hist_df["total_money"].iloc[0] > 0:
        total_ret = (hist_df["total_money"].iloc[-1] / hist_df["total_money"].iloc[0] - 1.0) * 100.0
    st.info(f"누적 수익률(대시보드 기준): {total_ret:.2f}% | MDD: {max_dd:.2f}%")
else:
    st.info("자산 스냅샷이 아직 없습니다. 봇 실행 후 새로고침하세요.")


# -------------------------
# Tables
# -------------------------
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("현재 보유 종목")
    if hold_df.empty:
        st.write("보유 종목 없음")
    else:
        show_cols = [
            c for c in [
                "StockCode", "StockName", "StockAmt", "StockAvgPrice", "StockNowPrice",
                "StockNowMoney", "StockRevenueRate", "StockRevenueMoney"
            ] if c in hold_df.columns
        ]
        st.dataframe(hold_df[show_cols], use_container_width=True, height=360)

with col_b:
    st.subheader("봇 전략 상태")
    if state_df.empty:
        st.write("전략 상태 파일 없음")
    else:
        show_cols = [
            c for c in [
                "StockCode", "StockName", "Status", "DayStatus", "TargetPrice",
                "TryBuyCnt", "IsTrailingStopSet", "TrailingStopCallbackRate", "PrevStockAmt"
            ] if c in state_df.columns
        ]
        st.dataframe(state_df[show_cols], use_container_width=True, height=360)

st.subheader("주문/체결 내역")
if order_df.empty:
    st.write("조회된 주문 내역 없음")
else:
    order_cols = [
        c for c in [
            "OrderDate", "OrderTime", "OrderStock", "OrderStockName", "OrderSide", "OrderType",
            "OrderSatus", "OrderAmt", "OrderResultAmt", "OrderAvgPrice", "OrderIsCancel", "OrderNum", "OrderNum2"
        ] if c in order_df.columns
    ]
    if order_cols:
        order_df = order_df.sort_values(by=[c for c in ["OrderDate", "OrderTime"] if c in order_df.columns], ascending=False)
        st.dataframe(order_df[order_cols], use_container_width=True, height=320)

st.subheader("봇 보조 상태(JSON)")
j1, j2, j3 = st.columns(3)
with j1:
    st.caption(str(date_path))
    st.json(date_state)
with j2:
    st.caption(str(siga_path))
    st.json(siga_state)
with j3:
    st.caption("계정/경로")
    st.json(
        {
            "account_mode": account_mode,
            "strategy_path": str(strategy_path),
            "autobot_data_dir": str(autobot_dir),
            "orders_history_csv": str(ORDERS_CSV),
            "equity_history_csv": str(SNAPSHOT_CSV),
            "holdings_history_csv": str(HOLDINGS_CSV),
        }
    )
