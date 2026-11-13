import { Moon, Network, PanelRight, Sun } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChatMessage } from "./components/ChatMessage";
import { Composer } from "./components/Composer";
import { Sidebar } from "./components/Sidebar";
import { getHealth, getPublicConfig, sendChat, streamChat } from "./lib/api";
import type { ChatResponse, Conversation, HealthStatus, Message, PublicConfig } from "./lib/types";

const STORAGE_KEY = "mxh-graphrag-conversations-v1";
const DEFAULT_CONFIG: PublicConfig = {
  mode: "fake",
  graph_provider: "fake",
  llm_provider: "fake",
  scope_id: "nlpgraph-v1",
  max_iterations: 5,
  max_records_per_query: 20,
  max_graph_hops: 4,
  debug_traces: true,
  enable_sse: true,
};

const SUGGESTIONS = [
  "An Nguyen có những bài báo nào?",
  "Đồng tác giả của An Nguyen là ai?",
  "Đường kết nối giữa An Nguyen và Binh Tran?",
  "Top tác giả có nhiều đồng tác giả nhất",
];

function newConversation(): Conversation {
  return { id: crypto.randomUUID(), title: "Hội thoại mới", messages: [], updatedAt: Date.now() };
}

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [newConversation()];
    }
    const parsed = JSON.parse(raw) as Conversation[];
    return parsed.length > 0 ? parsed : [newConversation()];
  } catch {
    return [newConversation()];
  }
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState(conversations[0].id);
  const [config, setConfig] = useState<PublicConfig>(DEFAULT_CONFIG);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.slice(0, 30)));
  }, [conversations]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    Promise.all([getPublicConfig(), getHealth()])
      .then(([publicConfig, healthStatus]) => {
        setConfig(publicConfig);
        setHealth(healthStatus);
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Không kết nối được API."));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active.messages]);

  function updateConversation(conversationId: string, updater: (conversation: Conversation) => Conversation) {
    setConversations((current) =>
      current.map((conversation) => (conversation.id === conversationId ? updater(conversation) : conversation)),
    );
  }

  function addConversation() {
    const created = newConversation();
    setConversations((current) => [created, ...current]);
    setActiveId(created.id);
    setError(null);
  }

  function renameConversation(id: string) {
    const current = conversations.find((conversation) => conversation.id === id);
    const title = window.prompt("Tên hội thoại", current?.title ?? "");
    if (!title?.trim()) {
      return;
    }
    updateConversation(id, (conversation) => ({ ...conversation, title: title.trim(), updatedAt: Date.now() }));
  }

  function deleteConversation(id: string) {
    const selected = conversations.find((conversation) => conversation.id === id);
    if (!window.confirm(`Xóa hội thoại “${selected?.title ?? "không tên"}”?`)) {
      return;
    }
    setConversations((current) => {
      const remaining = current.filter((conversation) => conversation.id !== id);
      if (remaining.length > 0) {
        if (activeId === id) {
          setActiveId(remaining[0].id);
        }
        return remaining;
      }
      const replacement = newConversation();
      setActiveId(replacement.id);
      return [replacement];
    });
  }

  async function ask(question: string) {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    const requestConversationId = active.id;
    const userMessage: Message = { id: crypto.randomUUID(), role: "user", content: question };
    const pendingId = crypto.randomUUID();
    const pendingMessage: Message = { id: pendingId, role: "assistant", content: "", pending: true };
    updateConversation(requestConversationId, (conversation) => ({
      ...conversation,
      title: conversation.messages.length === 0 ? question.slice(0, 52) : conversation.title,
      messages: [...conversation.messages, userMessage, pendingMessage],
      updatedAt: Date.now(),
    }));
    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      let response: ChatResponse;
      if (config.enable_sse) {
        try {
          response = await streamChat(question, true, () => undefined, controller.signal);
        } catch (streamError) {
          if (controller.signal.aborted) {
            throw streamError;
          }
          response = await sendChat(question, true, controller.signal);
        }
      } else {
        response = await sendChat(question, true, controller.signal);
      }
      updateConversation(requestConversationId, (conversation) => ({
        ...conversation,
        messages: conversation.messages.map((message) =>
          message.id === pendingId
            ? { ...message, content: response.answer, response, pending: false }
            : message,
        ),
        updatedAt: Date.now(),
      }));
    } catch (caught: unknown) {
      const message = caught instanceof Error ? caught.message : "Yêu cầu thất bại.";
      if (message.includes("aborted")) {
        updateConversation(requestConversationId, (conversation) => ({
          ...conversation,
          messages: conversation.messages.filter((item) => item.id !== pendingId),
        }));
      } else {
        setError(message);
        updateConversation(requestConversationId, (conversation) => ({
          ...conversation,
          messages: conversation.messages.map((item) =>
            item.id === pendingId ? { ...item, content: message, pending: false } : item,
          ),
        }));
      }
    } finally {
      controllerRef.current = null;
      setBusy(false);
    }
  }

  function stop() {
    controllerRef.current?.abort();
  }

  const degraded = health?.status === "degraded";
  return (
    <div className="app-shell">
      <Sidebar
        conversations={conversations}
        activeId={active.id}
        collapsed={sidebarCollapsed}
        mode={config.mode}
        onToggle={() => setSidebarCollapsed((value) => !value)}
        onNew={addConversation}
        onSelect={setActiveId}
        onRename={renameConversation}
        onDelete={deleteConversation}
      />
      <main id="main-chat" className="chat-main">
        <header className="topbar">
          <div className="brand-lockup">
            <Network aria-hidden="true" />
            <div><strong>NLP Graph Atlas</strong><span>{config.scope_id}</span></div>
          </div>
          <div className="topbar__actions">
            <span className={degraded ? "health-dot health-dot--bad" : "health-dot"}>
              {health ? (degraded ? "Dịch vụ chưa sẵn sàng" : "Đã kết nối") : "Đang kiểm tra"}
            </span>
            <button className="icon-button" onClick={() => setTheme((value) => (value === "light" ? "dark" : "light"))} aria-label="Đổi giao diện sáng tối">
              {theme === "light" ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
            </button>
            <button className="icon-button icon-button--desktop" aria-label="Mở bảng bằng chứng" onClick={() => document.querySelector(".detail-panel")?.scrollIntoView({ behavior: "smooth" })}>
              <PanelRight aria-hidden="true" />
            </button>
          </div>
        </header>

        {config.mode === "fake" && <div className="simulation-banner">SIMULATED — no real LLM/DB · Dùng để kiểm thử luồng, không phải kết quả nghiên cứu thật.</div>}
        {degraded && <div className="service-alert" role="alert"><strong>Chế độ real chưa sẵn sàng.</strong><span>{health?.llm.detail} · {health?.graph.detail}</span></div>}
        {error && <div className="error-alert" role="alert" tabIndex={-1}>{error}</div>}

        <section className="message-stage" aria-label="Nội dung hội thoại">
          {active.messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state__mark"><Network aria-hidden="true" /></div>
              <h1>Đi theo bằng chứng trong graph.</h1>
              <p>Đặt câu hỏi mở về tác giả, bài báo, tổ chức, venue, chủ đề và quan hệ trích dẫn trong corpus NLP 2023–2025.</p>
              {config.mode === "fake" && (
                <div className="suggestion-grid">
                  {SUGGESTIONS.map((suggestion) => <button key={suggestion} onClick={() => ask(suggestion)}>{suggestion}</button>)}
                </div>
              )}
            </div>
          ) : (
            <div className="messages">
              {active.messages.map((message) => <ChatMessage key={message.id} message={message} />)}
              <div ref={endRef} />
            </div>
          )}
        </section>
        <Composer busy={busy} disabled={Boolean(degraded)} onSend={ask} onStop={stop} />
      </main>
    </div>
  );
}

