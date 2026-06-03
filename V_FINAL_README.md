# V_FINAL 운영 가이드

KOSDAQ Rocket Hunter V_FINAL — 매주 금요일 entry signal + 매일 exit check.

## 시스템 구성

### 1. `V_FINAL_signal_bot.py` — 매주 금요일 entry scan
- 1208 KOSDAQ universe scan
- V_FINAL config 적용 (A_only + MA200 dist≤1.45 + lowvol + par 0.12)
- 시장 filter check (KOSDAQ 14d abs < 7%)
- 보유 종목 (`v_final_holdings.json`) 자동 제외
- 결과: `v_final_signals/signals_YYYYMMDD.txt` + 콘솔

### 2. `V_FINAL_exit_monitor.py` — 매일 exit check
- 보유 종목 각각 exit 조건 check
- HARDSTOP / Peak-stall / FAST_MA / PARABOLIC / Ratchet trail / MA200 / TIME
- max_close 자동 추적 (holdings.json 업데이트)
- 결과: `v_final_exits/exits_YYYYMMDD.txt` + 콘솔

### 3. `v_final_holdings.json` — 보유 종목 (수동 입력)
```json
[
  {
    "ticker": "257720",
    "name": "실리콘투",
    "entry_date": "2024-03-25",
    "entry_px": 11400,
    "qty": 1000,
    "max_close": 11400,
    "max_close_date": "2024-03-25"
  }
]
```

## 운영 주기

### 매주 금요일 (15:30+)
```bash
cd /Users/yonghyuk/newcodex
python3 V_FINAL_signal_bot.py
```
- 신호 종목 list 확인
- 월요일 OPEN 매수 (KIS 부계좌, 수동)
- 매수 후 `v_final_holdings.json` 에 추가

### 매일 (15:30+)
```bash
python3 V_FINAL_exit_monitor.py
```
- 보유 종목 exit 신호 check
- 🚨 EXIT 신호 발생 시: 다음 거래일 OPEN 매도
- 매도 후 `v_final_holdings.json` 에서 제거

### 매수 시 holdings.json 추가 예시
```json
{
  "ticker": "257720",
  "name": "실리콘투",
  "entry_date": "2026-06-09",
  "entry_px": 38700,
  "qty": 26,
  "max_close": 38700,
  "max_close_date": "2026-06-09"
}
```
- `ticker`: 6자리 종목코드
- `name`: 종목명
- `entry_date`: 매수 체결일 YYYY-MM-DD
- `entry_px`: 매수 단가
- `qty`: 매수 수량
- `max_close`: 매수 후 최고 종가 (초기는 entry_px)
- `max_close_date`: 최고 종가 일자

`max_close` 는 매일 exit_monitor 실행 시 자동 업데이트됨.

## 시장 filter 동작

KOSDAQ 14-day return 절대값 ≥ 7% 시:
- signal scan 자체 SKIP (entry 안 함)
- 보유 종목 exit check 는 정상 진행

## 데이터 갱신 (수동)

### 매주 (또는 주기적으로)
```bash
# 1208 KOSDAQ OHLCV 갱신 (cache 검사 후 5년 데이터)
python3 -c "from KOSDAQ_rocket_screener import build_universe; ..."

# 외인 cache 갱신 (보유 종목 + 후보 우선)
python3 bulk_fetch_investor.py
```

### KOSDAQ index (매일 자동, yfinance)
- `V_FINAL_signal_bot.py` 실행 시 자동 fetch

## 알림 옵션 (추가 구현 가능)

현재는 콘솔 + 파일 출력만. 다음 옵션 가능:
- 텔레그램 봇 (token 추가 시)
- 이메일 (SMTP 설정 시)
- macOS notification (osascript)

## 운영 권장 사항 (CEO)

1. **자본 5-10% 할당** — KR v7_best 봇 (90%) + V_FINAL (5-10%)
2. **별도 KIS 부계좌** 사용 (자본 분리)
3. **매주 금요일 15:30+ scan, 월요일 09:00 OPEN 매수**
4. **매일 15:30+ exit check, 다음 거래일 OPEN 매도**
5. **첫 1-2달 paper trade** — 실제 신호 받아서 매매 ROI 비교

## V_FINAL 기대값 (정직 estimate, V30-V32 검증 후 업데이트)

| 지표 | Backtest (full cache 1184) | Walk-forward OOS (Fold 3) | 운영 기대치 (bias 보정 후) |
|---|---|---|---|
| CAGR | +146.8% | +66.7% | **+45 ~ +55%** |
| MDD | -33.3% | -28.6% | -25 ~ -35% |
| Win rate | 42% | — | 40~45% |
| Trade 빈도 | 평균 14/년 | — | 5~16/년 |
| 보유 기간 | 평균 49일 | — | 7~150일 |

### 검증 요약 (V30~V32)
- ✅ Walk-forward robust 통과 (avg train→test drop -15pp)
- ⚠️ Survivorship bias 존재 (universe = 현재 상장 종목만, ~500 상폐 종목 누락)
- ❌ vol 1.9 우위 미미 (2021년 효과만)
- ❌ Partial profit taking 모두 baseline 보다 열위
- → V_FINAL config (vol 2.0, ma200_dist 1.45) **그대로 운영 시작**

## 한계 + 위험 (정직)

1. **Survivorship bias** — Backtest CAGR 은 실제 대비 30% 정도 과대평가 가능성
2. **mega-rocket 의존** — 2024년 단일 +711% 가 전체 CAGR 의 60% 기여
3. **외인 cache 의존** — 매주 incremental Naver scraping 필요
4. **+200% rocket 5년 2건** = rare event, 미래 보장 X
5. **단일 trade 손실 가능** — 첫 trade 가 -16~-20% HARDSTOP 으로 끝날 수 있음 (5월 102940 예시)
6. **수동 매매 의존** — CEO 가 월요일 09:00 OPEN 직접 매수 필요

## 운영 첫 1-2달 점검 포인트

- 5월 실거래 시 trade 1건 (102940 코오롱생명과학, -16% HARDSTOP) 발생했을 시나리오
- 첫 trade 손실 시 흔들리지 말 것 (Win rate 42% = 손실 trade 정상)
- 5년 누적 결과로 판단
- 3-6개월 후 grid 재검증 (vol/ma200) 권장
