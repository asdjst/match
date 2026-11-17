import { useEffect, useState } from "react";
import { Button, Stack, Switch } from "@astryxdesign/core";
import { useUi } from "./store/ui";
import { useRuns } from "./store/runs";
import { AccountEntry } from "./components/AccountEntry";
import { ConversationList } from "./components/ConversationList";
import ChatPage from "./pages/ChatPage";
import KnowledgePage from "./pages/KnowledgePage";

const CHAT_ICON = (
  <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4.5h12v8.5H8.5L5 16v-3H4z" />
  </svg>
);

const KB_ICON = (
  <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
    <ellipse cx="10" cy="4.6" rx="6.3" ry="2.5" />
    <path d="M3.7 4.6v4.8c0 1.4 2.8 2.5 6.3 2.5s6.3-1.1 6.3-2.5V4.6" />
    <path d="M3.7 9.4v4.8c0 1.4 2.8 2.5 6.3 2.5s6.3-1.1 6.3-2.5V9.4" />
  </svg>
);

export default function App() {
  const { mode, setMode } = useUi();
  const { runs, activeSessionId, newConversation } = useRuns();
  const [page, setPage] = useState<"chat" | "kb">(() => (window.location.hash === "#kb" ? "kb" : "chat"));
  // 当前会话已有消息时，点击工作台才新开一段；空会话重复点不产生新 session
  const currentHasRuns = runs.some((r) => r.sessionId === activeSessionId);

  useEffect(() => {
    const base = `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(null, "", `${base}${page === "kb" ? "#kb" : ""}`);
  }, [page]);

  return (
    <div className="app-shell">
      <aside className="side-nav">
        <div className="side-brand">
          <div className="brand-text">
            <strong>
              Glucoguard <span>AI</span>
            </strong>
            <small>慢病控糖膳食助手</small>
          </div>
        </div>

        <nav className="side-links" aria-label="工作台导航">
          <Button
            label="控糖工作台"
            variant={page === "chat" ? "secondary" : "ghost"}
            icon={CHAT_ICON}
            aria-current={page === "chat" ? "page" : undefined}
            width="100%"
            tooltip="点击新开一段对话"
            onClick={() => {
              if (page !== "chat") {
                setPage("chat");
                return;
              }
              if (currentHasRuns) newConversation();
            }}
          />
          <Button
            label="知识库维护"
            variant={page === "kb" ? "secondary" : "ghost"}
            icon={KB_ICON}
            aria-current={page === "kb" ? "page" : undefined}
            width="100%"
            tooltip="查看 R2R 摄入结构与召回状态"
            onClick={() => setPage("kb")}
          />
        </nav>

        {page === "chat" ? (
          <ConversationList />
        ) : (
          <div className="side-kb-note">
            <span>只读维护视图</span>
            <p>不影响正在进行的问答会话；回到工作台后可继续提问。</p>
          </div>
        )}

        <div className="side-foot">
          <AccountEntry />
          <Stack direction="horizontal" gap={2} vAlign="center">
            <span className="side-foot-label">深色模式</span>
            <Switch
              label="深色模式"
              isLabelHidden
              value={mode === "dark"}
              onChange={(checked) => setMode(checked ? "dark" : "light")}
            />
          </Stack>
        </div>
      </aside>

      <div className="app-main">
        <header className="app-topbar">
          <span className="top-page-icon">{page === "chat" ? CHAT_ICON : KB_ICON}</span>
          <div className="top-title">{page === "chat" ? "控糖工作台" : "知识库维护"}</div>
          <div className="top-date">
            {new Date().toLocaleDateString("zh-CN", {
              year: "numeric",
              month: "2-digit",
              day: "2-digit",
              weekday: "short",
            })}
          </div>
        </header>

        <div className="app-page">
          {page === "chat" ? <ChatPage /> : <KnowledgePage />}
        </div>
      </div>
    </div>
  );
}
