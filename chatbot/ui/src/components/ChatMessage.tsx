import { Bot, Copy, UserRound } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import type { Message } from "../lib/types";
import { EvidencePanel } from "./EvidencePanel";
import { TracePanel } from "./TracePanel";

export function ChatMessage({ message }: { message: Message }) {
  const isAssistant = message.role === "assistant";
  const response = message.response;

  async function copyAnswer() {
    await navigator.clipboard.writeText(message.content);
  }

  return (
    <article className={`message message--${message.role}`} aria-live={message.pending ? "polite" : undefined}>
      <div className="message__avatar" aria-hidden="true">
        {isAssistant ? <Bot /> : <UserRound />}
      </div>
      <div className="message__body">
        <div className="message__meta">
          <strong>{isAssistant ? "Graph Atlas" : "Bạn"}</strong>
          {response && <span className={`status-pill status-pill--${response.status}`}>{response.status.replaceAll("_", " ")}</span>}
          {response?.watermark && <span className="simulation-label">{response.watermark}</span>}
        </div>
        {message.pending ? (
          <div className="typing" aria-label="Đang xử lý"><span /><span /><span /></div>
        ) : (
          <div className="markdown"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{message.content}</ReactMarkdown></div>
        )}
        {response && response.ambiguous_candidates.length > 0 && (
          <div className="candidate-grid" aria-label="Các thực thể có thể chọn">
            {response.ambiguous_candidates.map((candidate) => (
              <button key={candidate.id} onClick={() => navigator.clipboard.writeText(candidate.id)}>
                <strong>{candidate.name}</strong>
                <span>{candidate.id}</span>
                <small>Chép ID để hỏi lại</small>
              </button>
            ))}
          </div>
        )}
        {response && <EvidencePanel sources={response.sources} />}
        {response?.trace && <TracePanel steps={response.trace} stopReason={response.stop_reason} />}
        {isAssistant && !message.pending && (
          <button className="copy-button" onClick={copyAnswer} aria-label="Sao chép câu trả lời">
            <Copy aria-hidden="true" /> Sao chép
          </button>
        )}
      </div>
    </article>
  );
}

