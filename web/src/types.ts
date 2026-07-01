export interface Meta { date: string; generated_at: string; tz: string; news_relevant: number; events: number; }
export interface Temperature {
  trade_date: string; pool_counted: number; up: number; down: number;
  flat: number; limit_up: number; limit_down: number; avg_pct: number;
}
export interface Headline { fact: string; user_judgment: string; confidence: string; }
export interface Top3Item { change: string; evidence: string; node_ids: string[]; related_stocks: string[]; }
export interface Sector { chain: string; status: string; }
export interface Falsification { claim: string; condition: string; draft_by: string; }
export interface Report {
  report_id: string; session: string; data_cutoff: string;
  headline: Headline; top3: Top3Item[]; sectors: Sector[];
  falsification: Falsification[]; holdings_moves: any[]; generated_at: string;
}
export interface NewsItem {
  title: string; one_line: string; sentiment: string; src: string;
  url: string | null; codes: string[]; holding: boolean; watching: boolean;
}
export interface NewsNode { node_id: string; chain: string; node: string; items: NewsItem[]; }
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

export interface HealthSource { name: string; latest: string; stale: boolean; }
export interface HealthTask { task: string; status: string; count: number | null; duration_ms: number | null; ts: string; }
export interface HealthFlag { kind: string; count: number; }
export interface Health {
  level: string; sources: HealthSource[]; tasks: HealthTask[]; flags: HealthFlag[];
}

export interface ResearchReport {
  date: string; code: string; name: string; org: string; rating: string;
  title: string; tp: number | null; pe: number | null; node_ids: string[];
}
export interface Coverage { name: string; n: number; latest: string; }
export interface FundLetter {
  fund_name: string; period: string | null; stance: string | null;
  strategy: string | null; relevance: number | null; core_views: any; status: string;
}
export interface Research { reports: ResearchReport[]; coverage: Coverage[]; letters: FundLetter[]; }

export interface Dashboard {
  meta: Meta; report: Report | null; temperature: Temperature;
  news_by_node: NewsNode[]; stock_events: StockEvent[];
  heatmap?: Heatmap; health?: Health; research?: Research;
}
