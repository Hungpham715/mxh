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

export interface AtlasNode {
  id: string;
  name: string;
  identity_status: string;
  degree: number;
  weighted_degree: number;
  pagerank: number;
  community: number | null;
  core_number: number;
}

export interface AtlasEdge {
  id: string;
  source: string;
  target: string;
  shared_count: number;
  evidence_paper_ids: string[];
}

export interface AtlasSnapshot {
  schema_version: string;
  source_kind: "real_offline_snapshot";
  scope_id: string;
  provenance: {
    directory: string;
    artifacts: string[];
    projection: string;
    analysis_source: string;
  };
  counts: {
    nodes: Record<string, number>;
    relationships: Record<string, number>;
    total_nodes: number;
    total_relationships: number;
  };
  network_stats: {
    authors_total: number;
    edges: number;
    connected_components: number;
    lcc_size: number;
    lcc_ratio_of_all_authors: number;
  };
  top_pagerank: Array<{
    author_id: string;
    name: string;
    score: number;
    degree: number;
    weighted_degree: number;
    evidence_paper_ids: string[];
  }>;
  communities: { n_communities: number; modularity: number; method: string };
  community_summary: Array<{
    community: number;
    size: number;
    papers: number;
    top_topics: Array<[string, number]>;
    members_sample: string[];
    kernel_members: string[];
  }>;
  core: { max_core: number; kernel_size: number; kernel_density: number };
  small_world: {
    C_obs: number;
    C_rand: number;
    L_obs: number;
    L_rand: number;
    sigma: number;
    verdict: string;
    limitations: string[];
  };
  small_world_sensitivity?: {
    slice_count: number;
    verdict_counts: Record<string, number>;
    conclusion: string;
  } | null;
  graph: { nodes: AtlasNode[]; edges: AtlasEdge[]; bounded: boolean; max_nodes: number };
  caveats: string[];
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

