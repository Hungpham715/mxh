import { Send, Square } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
}

export function Composer({ busy, disabled, onSend, onStop }: ComposerProps) {
  const [value, setValue] = useState("");

  function submit() {
    const question = value.trim();
    if (!question || busy || disabled) {
      return;
    }
    onSend(question);
    setValue("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer-wrap">
      <label className="sr-only" htmlFor="chat-question">
        Câu hỏi về mạng nghiên cứu NLP
      </label>
      <div className="composer">
        <textarea
          id="chat-question"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Hỏi về tác giả, bài báo, tổ chức, chủ đề hoặc đường đồng tác giả…"
          rows={1}
          maxLength={2000}
          disabled={disabled}
        />
        {busy ? (
          <button className="send-button send-button--stop" onClick={onStop} aria-label="Dừng trả lời">
            <Square aria-hidden="true" />
          </button>
        ) : (
          <button className="send-button" onClick={submit} disabled={disabled || !value.trim()} aria-label="Gửi câu hỏi">
            <Send aria-hidden="true" />
          </button>
        )}
      </div>
      <p className="composer-help">Enter để gửi · Shift+Enter để xuống dòng · Kết quả chỉ giới hạn trong corpus.</p>
    </div>
  );
}

