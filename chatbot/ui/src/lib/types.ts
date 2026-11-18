export type ChatStatus =
  | "answered"
  | "partial"
  | "not_found"
  | "ambiguous"
  | "clarify"
  | "out_of_scope"
  | "error";

export type RouteName = "graph_qa" | "chat_history" | "clarify" | "out_of_scope";

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
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
  detail?: string | null;
}

export interface ChatResponse {
  answer: string;
  status: ChatStatus;
  complete: boolean;
  iterations_used: number;
  stop_reason: string;
  sources: Citation[];
  facts_count: number;
  truncated?: boolean;
  route?: RouteName | null;
  parsed_intent?: string | null;
  parse_source?: string | null;
  llm_calls?: number;
  model?: string | null;
  trace?: TraceStep[] | null;
  provider_info?: Record<string, string> | null;
  ambiguous_candidates: CandidateEntity[];
  watermark?: string | null;
}

export interface PublicConfig {
  mode: "fake" | "real";
  graph_provider: "fake" | "neo4j";
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
  mode: "fake" | "real";
  llm: { provider: string; ready: boolean; detail: string };
  graph: { provider: string; ready: boolean; detail: string };
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  pending?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

