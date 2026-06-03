# -*- coding: utf-8 -*-
"""
Telegram callback handler — V_FINAL 매수/매도 자동 처리.

플로우:
1. signal_bot 알림 → inline keyboard 버튼 ("매수완료")
2. 사용자 클릭 → callback_data = "buy:YYYYMMDD:TICKER"
3. handler 가 pending state 에 저장 → "체결가/수량 입력 대기" 답신
4. 사용자 텍스트 답신 (예: "65600 100")
5. handler 가 파싱 → v_final_holdings.json 에 추가 → 확인 답신

매도 동일 (callback_data = "sell:YYYYMMDD:TICKER" → 수량 자동 (보유분 전량)).

5분마다 cron 으로 실행 권장.

Usage:
  python3 telegram_callback_handler.py
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import telegram_alert

ROOT = Path(__file__).resolve().parent
HOLDINGS_FILE = ROOT / 'v_final_holdings.json'
PENDING_DIR = ROOT / 'v_final_pending'
PENDING_DIR.mkdir(exist_ok=True)
STATE_FILE = PENDING_DIR / 'handler_state.json'
WAITING_FILE = PENDING_DIR / 'waiting_input.json'

ALLOWED_CHAT_ID = telegram_alert.CHAT_ID


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {'last_update_id': 0}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def load_waiting():
    if WAITING_FILE.exists():
        try:
            with open(WAITING_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_waiting(data):
    if data is None:
        if WAITING_FILE.exists():
            WAITING_FILE.unlink()
    else:
        with open(WAITING_FILE, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def load_holdings():
    if not HOLDINGS_FILE.exists():
        return []
    with open(HOLDINGS_FILE) as f:
        return json.load(f)


def save_holdings(holdings):
    with open(HOLDINGS_FILE, 'w') as f:
        json.dump(holdings, f, indent=2, ensure_ascii=False)


def load_pending_signals(scan_date):
    p = PENDING_DIR / f'pending_signals_{scan_date}.json'
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def handle_buy_callback(scan_date, ticker):
    """User clicked '매수완료' button. Save waiting state, ask for price/qty."""
    pending = load_pending_signals(scan_date)
    if pending is None:
        telegram_alert.SendMessage(f"⚠️ {scan_date} signal data not found")
        return
    signal = next((s for s in pending['signals'] if s['ticker'] == ticker), None)
    if signal is None:
        telegram_alert.SendMessage(f"⚠️ {ticker} not in pending signals")
        return

    waiting = {
        'action': 'buy',
        'ticker': ticker,
        'name': signal['name'],
        'signal_close': signal['close'],
        'scan_date': scan_date,
        'created_at': datetime.now().isoformat(),
    }
    save_waiting(waiting)
    telegram_alert.SendMessage(
        f"📝 {ticker} {signal['name']} 매수 정보 입력\n"
        f"형식: 체결가 수량\n"
        f"예: 65600 100\n"
        f"(signal close: {signal['close']:,.0f}원)"
    )


def handle_sell_callback(scan_date, ticker):
    """User clicked '매도완료' button. Save waiting state, ask for price."""
    holdings = load_holdings()
    h = next((h for h in holdings if h['ticker'] == ticker), None)
    if h is None:
        telegram_alert.SendMessage(f"⚠️ {ticker} not in holdings")
        return

    waiting = {
        'action': 'sell',
        'ticker': ticker,
        'name': h.get('name', ticker),
        'entry_px': h['entry_px'],
        'qty': h.get('qty', 0),
        'created_at': datetime.now().isoformat(),
    }
    save_waiting(waiting)
    telegram_alert.SendMessage(
        f"📝 {ticker} {h.get('name', '')} 매도 정보 입력\n"
        f"형식: 체결가\n"
        f"예: 55100\n"
        f"(entry {h['entry_px']:,.0f}원, qty {h.get('qty', 0):,})"
    )


def handle_text_input(text):
    """User sent text. Check waiting state and process."""
    waiting = load_waiting()
    if waiting is None:
        return False  # not waiting for input

    text = text.strip()

    if waiting['action'] == 'buy':
        # Parse "price qty"
        m = re.match(r'^(\d[\d,]*)\s+(\d+)$', text)
        if not m:
            telegram_alert.SendMessage(
                f"⚠️ 형식 오류: '{text}'\n"
                f"올바른 형식: 체결가 수량\n"
                f"예: 65600 100"
            )
            return True
        entry_px = float(m.group(1).replace(',', ''))
        qty = int(m.group(2))
        if entry_px <= 0 or qty <= 0:
            telegram_alert.SendMessage(f"⚠️ 가격/수량은 양수여야 함")
            return True

        # Add to holdings.json
        holdings = load_holdings()
        # Check duplicate
        if any(h['ticker'] == waiting['ticker'] for h in holdings):
            telegram_alert.SendMessage(f"⚠️ {waiting['ticker']} 이미 보유 중")
            save_waiting(None)
            return True

        # Entry date = next Monday after scan_date (signal scan is Friday)
        scan_dt = datetime.strptime(waiting['scan_date'], '%Y%m%d')
        # Add 3 days (Fri → Mon)
        from datetime import timedelta
        entry_date = (scan_dt + timedelta(days=3)).strftime('%Y-%m-%d')

        new_holding = {
            'ticker': waiting['ticker'],
            'name': waiting['name'],
            'entry_date': entry_date,
            'entry_px': entry_px,
            'qty': qty,
            'max_close': entry_px,
            'max_close_date': entry_date,
        }
        holdings.append(new_holding)
        save_holdings(holdings)
        save_waiting(None)

        telegram_alert.SendMessage(
            f"✅ 매수 등록 완료\n"
            f"{waiting['ticker']} {waiting['name']}\n"
            f"체결가: {entry_px:,.0f}원\n"
            f"수량: {qty:,}\n"
            f"entry_date: {entry_date}\n"
            f"\n현재 보유: {len(holdings)}건"
        )
        return True

    elif waiting['action'] == 'sell':
        # Parse "price"
        m = re.match(r'^(\d[\d,]*)$', text)
        if not m:
            telegram_alert.SendMessage(
                f"⚠️ 형식 오류: '{text}'\n"
                f"올바른 형식: 체결가\n"
                f"예: 55100"
            )
            return True
        exit_px = float(m.group(1).replace(',', ''))
        if exit_px <= 0:
            telegram_alert.SendMessage(f"⚠️ 가격은 양수여야 함")
            return True

        # Remove from holdings.json
        holdings = load_holdings()
        h = next((h for h in holdings if h['ticker'] == waiting['ticker']), None)
        if h is None:
            telegram_alert.SendMessage(f"⚠️ {waiting['ticker']} not in holdings")
            save_waiting(None)
            return True

        entry_px = h['entry_px']
        qty = h.get('qty', waiting.get('qty', 0))
        pnl_pct = (exit_px / entry_px - 1) * 100
        pnl_amt = (exit_px - entry_px) * qty

        # Log to closed trades
        closed_log = ROOT / 'v_final_closed_trades.json'
        closed = []
        if closed_log.exists():
            try:
                with open(closed_log) as f:
                    closed = json.load(f)
            except Exception:
                closed = []
        closed.append({
            'ticker': waiting['ticker'],
            'name': waiting['name'],
            'entry_date': h['entry_date'],
            'entry_px': entry_px,
            'exit_date': datetime.now().strftime('%Y-%m-%d'),
            'exit_px': exit_px,
            'qty': qty,
            'pnl_pct': pnl_pct,
            'pnl_amt': pnl_amt,
        })
        with open(closed_log, 'w') as f:
            json.dump(closed, f, indent=2, ensure_ascii=False)

        holdings = [hh for hh in holdings if hh['ticker'] != waiting['ticker']]
        save_holdings(holdings)
        save_waiting(None)

        telegram_alert.SendMessage(
            f"✅ 매도 등록 완료\n"
            f"{waiting['ticker']} {waiting['name']}\n"
            f"체결가: {exit_px:,.0f}원 (entry {entry_px:,.0f})\n"
            f"P&L: {pnl_pct:+.1f}% ({pnl_amt:+,.0f}원)\n"
            f"\n현재 보유: {len(holdings)}건"
        )
        return True

    return False


def main():
    state = load_state()
    offset = state.get('last_update_id', 0) + 1
    updates = telegram_alert.GetUpdates(offset=offset, timeout=5)

    if not updates:
        return

    for update in updates:
        update_id = update.get('update_id', 0)
        state['last_update_id'] = max(state['last_update_id'], update_id)

        # Callback query (button press)
        cb = update.get('callback_query')
        if cb:
            chat = cb.get('message', {}).get('chat', {})
            if chat.get('id') != ALLOWED_CHAT_ID:
                continue
            data = cb.get('data', '')
            telegram_alert.AnswerCallback(cb['id'], text='접수')
            parts = data.split(':')
            if len(parts) >= 3:
                action, scan_date, ticker = parts[0], parts[1], parts[2]
                if action == 'buy':
                    handle_buy_callback(scan_date, ticker)
                elif action == 'sell':
                    handle_sell_callback(scan_date, ticker)
            continue

        # Text message
        msg = update.get('message')
        if msg:
            chat = msg.get('chat', {})
            if chat.get('id') != ALLOWED_CHAT_ID:
                continue
            text = msg.get('text', '')
            if not text:
                continue
            # Special command: /holdings
            if text.strip() == '/holdings':
                holdings = load_holdings()
                if not holdings:
                    telegram_alert.SendMessage("📋 V_FINAL 보유: 없음")
                else:
                    lines = [f"📋 V_FINAL 보유 ({len(holdings)}건)"]
                    for h in holdings:
                        lines.append(
                            f"• {h['ticker']} {h.get('name', '')}: "
                            f"entry {h['entry_date']} @ {h['entry_px']:,.0f}, qty {h.get('qty', 0):,}"
                        )
                    telegram_alert.SendMessage('\n'.join(lines))
                continue
            # Cancel waiting state
            if text.strip() == '/cancel':
                save_waiting(None)
                telegram_alert.SendMessage("❎ 입력 대기 취소")
                continue
            # Process text input (price/qty)
            handle_text_input(text)

    save_state(state)


if __name__ == '__main__':
    main()
