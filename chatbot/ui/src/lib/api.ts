import type { ChatResponse, HealthStatus, PublicConfig } from "./types";

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
  debug: boolean,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ question, debug }),
    signal,
  });
  return parseJson<ChatResponse>(response);
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
  debug: boolean,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ question, debug }),
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

