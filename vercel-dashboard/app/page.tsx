'use client';

import { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type Snapshot = {
  ts: string;
  account_mode: 'REAL' | 'VIRTUAL';
  market_open: boolean;
  total_money: number;
  stock_money: number;
  remain_money: number;
  stock_revenue: number;
  invest_cnt: number;
  is_cut: boolean;
  cut_cnt: number;
  exposure_rate: number;
  peak_money: number;
};

type DashboardPayload = {
  snapshot: Snapshot;
  holdings: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  strategy_state: Array<Record<string, unknown>>;
  meta?: Record<string, unknown>;
};

type ApiResp = {
  ok: boolean;
  latest: DashboardPayload | null;
  history: Snapshot[];
  error?: string;
};

function num(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return n;
}

function money(v: unknown) {
  return `${Math.round(num(v)).toLocaleString()}원`;
}

export default function Page() {
  const [data, setData] = useState<ApiResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshSec, setRefreshSec] = useState(15);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/data', { cache: 'no-store' });
      const j = (await r.json()) as ApiResp;
      setData(j);
    } catch (e) {
      setData({ ok: false, latest: null, history: [], error: String(e) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (refreshSec <= 0) return;
    const t = setInterval(load, refreshSec * 1000);
    return () => clearInterval(t);
  }, [refreshSec]);

  const chartRows = useMemo(() => {
    const h = data?.history ?? [];
    let hwm = 0;
    return h.map((x) => {
      hwm = Math.max(hwm, num(x.total_money));
      const dd = hwm > 0 ? num(x.total_money) / hwm - 1 : 0;
      return {
        ts: x.ts?.slice(5, 16),
        total: num(x.total_money),
        dd: dd * 100,
        exposure: num(x.exposure_rate),
        invest: num(x.invest_cnt),
      };
    });
  }, [data]);

  const latest = data?.latest;
  const snapshot = latest?.snapshot;

  const totalRet = useMemo(() => {
    if (chartRows.length < 2) return 0;
    const a = chartRows[0].total;
    const b = chartRows[chartRows.length - 1].total;
    if (a <= 0) return 0;
    return ((b / a) - 1) * 100;
  }, [chartRows]);

  const maxDD = useMemo(() => {
    if (!chartRows.length) return 0;
    return Math.min(...chartRows.map((x) => x.dd));
  }, [chartRows]);

  return (
    <main className="container">
      <div className="header-row">
        <div>
          <h1>Kosdaqpi 실시간 대시보드</h1>
          <div className="sub">잔고, 보유현황, 주문내역, 노출(Exposure), DD를 웹에서 상시 확인</div>
        </div>
        <div className="controls">
          <label>새로고침(초)</label>
          <select value={refreshSec} onChange={(e) => setRefreshSec(Number(e.target.value))}>
            <option value={0}>OFF</option>
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={15}>15</option>
            <option value={30}>30</option>
            <option value={60}>60</option>
          </select>
          <button onClick={load}>{loading ? '로딩...' : '새로고침'}</button>
        </div>
      </div>

      {data?.error && <div className="card danger">에러: {data.error}</div>}

      <div className="grid kpi">
        <div className="card"><div className="kpi-title">조회시각</div><div className="kpi-value">{snapshot?.ts ?? '-'}</div></div>
        <div className="card"><div className="kpi-title">장 상태</div><div className="kpi-value"><span className={`badge ${snapshot?.market_open ? 'open' : 'close'}`}>{snapshot?.market_open ? 'OPEN' : 'CLOSE'}</span></div></div>
        <div className="card"><div className="kpi-title">총 평가금액</div><div className="kpi-value">{money(snapshot?.total_money)}</div></div>
        <div className="card"><div className="kpi-title">주식 평가금액</div><div className="kpi-value">{money(snapshot?.stock_money)}</div></div>
        <div className="card"><div className="kpi-title">예수금</div><div className="kpi-value">{money(snapshot?.remain_money)}</div></div>
        <div className="card"><div className="kpi-title">평가손익</div><div className="kpi-value">{money(snapshot?.stock_revenue)}</div></div>
      </div>

      <div className="grid kpi" style={{ marginTop: 12 }}>
        <div className="card"><div className="kpi-title">누적 수익률(업로드 기준)</div><div className="kpi-value">{totalRet.toFixed(2)}%</div></div>
        <div className="card"><div className="kpi-title">MDD</div><div className="kpi-value danger">{maxDD.toFixed(2)}%</div></div>
        <div className="card"><div className="kpi-title">Exposure</div><div className="kpi-value">{num(snapshot?.exposure_rate).toFixed(2)}</div></div>
        <div className="card"><div className="kpi-title">InvestCnt</div><div className="kpi-value">{num(snapshot?.invest_cnt)}</div></div>
        <div className="card"><div className="kpi-title">CutCnt</div><div className="kpi-value">{num(snapshot?.cut_cnt)}</div></div>
        <div className="card"><div className="kpi-title">계좌 모드</div><div className="kpi-value">{snapshot?.account_mode ?? '-'}</div></div>
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>총 자산 추이</h3>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartRows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="ts" minTickGap={40} />
              <YAxis tickFormatter={(v) => `${Math.round(v / 10000)}만`} />
              <Tooltip formatter={(v: number) => `${Math.round(v).toLocaleString()}원`} />
              <Area type="monotone" dataKey="total" stroke="#0f766e" fill="#99f6e4" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3>Drawdown / Exposure</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartRows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="ts" minTickGap={40} />
              <YAxis yAxisId="left" tickFormatter={(v) => `${v.toFixed(1)}%`} />
              <YAxis yAxisId="right" orientation="right" />
              <Tooltip />
              <Line yAxisId="left" type="monotone" dataKey="dd" stroke="#b91c1c" dot={false} />
              <Line yAxisId="right" type="monotone" dataKey="exposure" stroke="#1d4ed8" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>보유 종목</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>코드</th><th>종목명</th><th>수량</th><th>평단</th><th>현재가</th><th>평가손익률</th><th>평가손익</th>
                </tr>
              </thead>
              <tbody>
                {(latest?.holdings ?? []).map((r, i) => (
                  <tr key={i}>
                    <td>{String(r.StockCode ?? '')}</td>
                    <td>{String(r.StockName ?? '')}</td>
                    <td>{String(r.StockAmt ?? '')}</td>
                    <td>{String(r.StockAvgPrice ?? '')}</td>
                    <td>{String(r.StockNowPrice ?? '')}</td>
                    <td>{String(r.StockRevenueRate ?? '')}</td>
                    <td>{String(r.StockRevenueMoney ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>봇 전략 상태</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>코드</th><th>종목명</th><th>Status</th><th>DayStatus</th><th>Target</th><th>TryBuyCnt</th><th>Trailing</th>
                </tr>
              </thead>
              <tbody>
                {(latest?.strategy_state ?? []).map((r, i) => (
                  <tr key={i}>
                    <td>{String(r.StockCode ?? '')}</td>
                    <td>{String(r.StockName ?? '')}</td>
                    <td>{String(r.Status ?? '')}</td>
                    <td>{String(r.DayStatus ?? '')}</td>
                    <td>{String(r.TargetPrice ?? '')}</td>
                    <td>{String(r.TryBuyCnt ?? '')}</td>
                    <td>{String(r.IsTrailingStopSet ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>최근 주문/체결</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>주문일</th><th>시간</th><th>코드</th><th>종목명</th><th>매수/매도</th><th>타입</th><th>상태</th><th>수량</th><th>체결수량</th><th>평균단가</th>
              </tr>
            </thead>
            <tbody>
              {(latest?.orders ?? []).slice(0, 300).map((r, i) => (
                <tr key={i}>
                  <td>{String(r.OrderDate ?? '')}</td>
                  <td>{String(r.OrderTime ?? '')}</td>
                  <td>{String(r.OrderStock ?? '')}</td>
                  <td>{String(r.OrderStockName ?? '')}</td>
                  <td>{String(r.OrderSide ?? '')}</td>
                  <td>{String(r.OrderType ?? '')}</td>
                  <td>{String(r.OrderSatus ?? '')}</td>
                  <td>{String(r.OrderAmt ?? '')}</td>
                  <td>{String(r.OrderResultAmt ?? '')}</td>
                  <td>{String(r.OrderAvgPrice ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
