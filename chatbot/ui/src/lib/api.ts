import type { ChatResponse, Continuation, HealthStatus, HistoryTurn, PublicConfig } from "./types";

const MAX_HISTORY_TURNS = 12;
const MAX_TURN_CHARS = 4000;

/** Keep the last turns the backend accepts; only user/assistant roles are ever sent. */
export function trimHistory(history: HistoryTurn[]): HistoryTurn[] {
  return history
    .filter((turn) => turn.content.trim().length > 0)
    .slice(-MAX_HISTORY_TURNS)
    .map((turn) => ({ role: turn.role, content: turn.content.slice(0, MAX_TURN_CHARS) }));
}

const JSON_HEADERS = { "Content-Type": "application/json" };

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API ${response.status}: ${body.slice(0, 240)}`);
  }
  return (await response.json()) as T;
}

export async function getPublicConfig(): Promise<PublicConfig> {
  return parseJson<PublicConfig>(await fetch("/api/config/public"));
}

export async function getHealth(): Promise<HealthStatus> {
  return parseJson<HealthStatus>(await fetch("/api/health"));
}

export async function sendChat(
  question: string,
  history: HistoryTurn[],
  debug: boolean,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ question, history: trimHistory(history), debug }),
    signal,
  });
  return parseJson<ChatResponse>(response);
}

export async function fetchMore(continuation: Continuation, signal?: AbortSignal): Promise<ChatResponse> {
  const response = await fetch("/api/chat/more", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ continuation, debug: true }),
    signal,
  });
  return parseJson<ChatResponse>(response);
}

/** Short Vietnamese label for one live progress event (shown while the answer is pending). */
export function describeEvent(event: StreamEvent): string | null {
  const data = (event.data ?? {}) as Record<string, unknown>;
  switch (event.event) {
    case "parse":
      return `Phân tích: ${String(data.route ?? "")}${data.intent && data.intent !== "unknown" ? ` · ${String(data.intent)}` : ""}`;
    case "linked":
      return "Đã nối thực thể với graph";
    case "query_start":
      return `Truy vấn #${String(data.iteration)}: ${String(data.action ?? "").replaceAll("_", " ")}`;
    case "query_result":
      return `→ ${String(data.records ?? 0)} bản ghi${data.truncated ? " (còn nữa)" : ""}`;
    case "decision":
      return `Quyết định: ${String(data.decision ?? "")}`;
    case "answer":
      return "Đang hoàn tất câu trả lời";
    default:
      return null;
  }
}

export interface StreamEvent {
  event: string;
  data: unknown;
}

export function parseSSEBlock(block: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) {
      event = line.slice(7);
    }
    if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    }
  }
  if (dataLines.length === 0) {
    return null;
  }
  return { event, data: JSON.parse(dataLines.join("\n")) as unknown };
}

export async function streamChat(
  question: string,
  history: HistoryTurn[],
  debug: boolean,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ question, history: trimHistory(history), debug }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Streaming API unavailable (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: ChatResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const parsed = parseSSEBlock(block);
      if (!parsed) {
        continue;
      }
      onEvent(parsed);
      if (parsed.event === "done") {
        completed = parsed.data as ChatResponse;
      }
      if (parsed.event === "error") {
        throw new Error(`Chat stream failed: ${JSON.stringify(parsed.data)}`);
      }
    }
    if (done) {
      break;
    }
  }
  if (!completed) {
    throw new Error("Chat stream ended without a done event");
  }
  return completed;
}

