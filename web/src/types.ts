export interface Meta { date: string; generated_at: string; tz: string; news_relevant: number; events: number; }
export interface Temperature {
  trade_date: string; pool_counted: number; up: number; down: number;
  flat: number; limit_up: number; limit_down: number; avg_pct: number;
}
export interface Headline { fact: string; user_judgment: string; confidence: string; }
export interface Top3Item { change: string; evidence: string; node_ids: string[]; related_stocks: string[]; }
export interface Sector { chain: string; status: string; }
export interface Falsification { claim: string; condition: string; draft_by: string; }
export interface UsItem { ticker: string; name: string; mapping: string; close: number | null; pct: number | null; }
export interface UsOvernight { us_session_date: string; items: UsItem[]; n_ok: number; fetched_at: string; }
export interface Report {
  report_id: string; session: string; data_cutoff: string;
  headline: Headline; top3: Top3Item[]; sectors: Sector[];
  falsification: Falsification[]; holdings_moves: any[]; generated_at: string;
  us_overnight?: UsOvernight;
}
export interface NewsItem {
  title: string; one_line: string; summary?: string | null; sentiment: string; event_type?: string; src: string;
  url: string | null; time?: string; codes: string[]; holding: boolean; watching: boolean;
}
export interface NewsNode { node_id: string; chain: string; node: string; scope?: string; items: NewsItem[]; }
export interface StockEvent {
  code: string; event_type: string; direction: string; date: string;
  summary: string; node_ids: string[]; holding: boolean; watching: boolean;
}
export interface HeatNode {
  node_id: string; chain: string; node: string; n_stocks: number;
  total_mv: number | null; ret_1m: number | null; ret_6m: number | null;
  or_yoy: number | null; gross_margin: number | null; pe: number | null;
  ps: number | null; quadrant: string;
}
export interface HeatStock {
  code: string; name: string; total_mv: number | null; pe: number | null;
  ps: number | null; ret_1m: number | null; ret_6m: number | null;
  or_yoy: number | null; gross_margin: number | null; pe_pct: number | null;
}
export interface Heatmap { nodes: HeatNode[]; stocks: HeatStock[]; }

export interface HealthSource { name: string; latest: string; stale: boolean; pending?: boolean; }
export interface HealthTask { task: string; status: string; count: number | null; duration_ms: number | null; ts: string; }
export interface HealthFlag { kind: string; count: number; }
export interface Health {
  level: string; sources: HealthSource[]; tasks: HealthTask[]; flags: HealthFlag[];
}

export interface ResearchReport {
  date: string; code: string; name: string; org: string; rating: string;
  title: string; tp: number | null; pe: number | null; node_ids: string[];
  scope?: string; industry?: string | null;
}
export interface Coverage { name: string; n: number; latest: string; scope?: string; }
export interface FundLetter {
  fund_name: string; period: string | null; stance: string | null;
  strategy: string | null; relevance: number | null; core_views: any; status: string;
  title?: string | null; url?: string | null; relevant_points?: any;
}
export interface Research { reports: ResearchReport[]; coverage: Coverage[]; letters: FundLetter[]; }

export interface Judgment {
  id: number; report_id: string; claim: string; condition: string;
  date: string; falsified: boolean; error_type: string | null;
}
export interface Ledger {
  judgments: Judgment[]; alive: number; falsified: number; error_dist: Record<string, number>;
}

export interface UsBoardItem {
  ticker: string; name: string; sector: string; close: number | null; pct: number | null;
  ret_6m: number | null; pos_52w: number | null; market_cap: number | null; pe: number | null;
  rev_growth?: number | null; gross_margin?: number | null;
  target_mean?: number | null; rec_key?: string | null; n_analysts?: number | null;
}
export interface UsBoard { us_session_date: string; items: UsBoardItem[]; n_ok: number; fetched_at?: string; }
export interface UsTemperature { counted: number; up: number; down: number; flat: number; avg_pct: number; }
export interface UsResearchItem {
  code: string; name: string; sector: string; target_mean: number | null; upside: number | null;
  rec_key: string | null; n_analysts: number | null; pe: number | null;
}
export interface UsNewsItem {
  title: string; one_line: string; sentiment: string; src: string; url: string | null;
  sector: string; ticker: string;
}
export interface UsData {
  us_session_date: string;
  board: { items: UsBoardItem[]; n_ok: number };
  temperature: UsTemperature;
  heatmap: Heatmap;
  research: UsResearchItem[];
  news: UsNewsItem[];
  report: Report | null;
  indices: UsBoardItem[];
}

export interface Dashboard {
  meta: Meta; report: Report | null; temperature: Temperature;
  news_by_node: NewsNode[]; stock_events: StockEvent[];
  heatmap?: Heatmap; health?: Health; research?: Research; ledger?: Ledger;
  us?: UsData | null;
}
