export type ChatStatus =
  | "answered"
  | "partial"
  | "not_found"
  | "ambiguous"
  | "out_of_scope"
  | "clarify"
  | "error";

export type ChatRoute = "GRAPH_QA" | "CHAT_HISTORY" | "CLARIFY" | "OUT_OF_SCOPE";

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface Continuation {
  action: string;
  params: Record<string, unknown>;
  offset: number;
  total?: number | null;
}

export interface Citation {
  paper_id: string;
  title: string;
  url: string;
  claim_ids: string[];
}

export interface CandidateEntity {
  id: string;
  label: string;
  name: string;
  score: number;
}

export interface TraceStep {
  iteration: number;
  action: string;
  records: number;
  new_facts: number;
  duration_ms: number;
  status: "ok" | "empty" | "error" | "infrastructure";
  params?: Record<string, unknown> | null;
  total?: number | null;
  truncated?: boolean;
  decision?: string | null;
  decision_source?: string | null;
  detail?: string | null;
}

export interface ChatResponse {
  answer: string;
  status: ChatStatus;
  route?: ChatRoute;
  complete: boolean;
  iterations_used: number;
  stop_reason: string;
  sources: Citation[];
  facts_count: number;
  trace?: TraceStep[] | null;
  provider_info?: Record<string, string> | null;
  ambiguous_candidates: CandidateEntity[];
  continuation?: Continuation | null;
  total_results?: number | null;
  shown_results?: number | null;
  llm_calls?: number;
  db_calls?: number;
  parse_source?: string | null;
  watermark?: string | null;
}

export interface PublicConfig {
  mode: "fake" | "real" | "snapshot";
  graph_provider: "fake" | "neo4j" | "snapshot";
  llm_provider: "fake" | "ollama" | "hf_cpu";
  scope_id: string;
  max_iterations: number;
  max_records_per_query: number;
  max_graph_hops: number;
  debug_traces: boolean;
  enable_sse: boolean;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  mode: "fake" | "real" | "snapshot";
  llm: { provider: string; ready: boolean; detail: string };
  graph: { provider: string; ready: boolean; detail: string };
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  pending?: boolean;
  progress?: string[];
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

