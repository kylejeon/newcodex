export type Snapshot = {
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

export type DashboardPayload = {
  snapshot: Snapshot;
  holdings: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  strategy_state: Array<Record<string, unknown>>;
  meta?: Record<string, unknown>;
};

export type StoredData = {
  latest: DashboardPayload | null;
  history: Snapshot[];
};
