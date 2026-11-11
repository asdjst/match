/**
 * 应用外壳：左侧工作台导航 + 顶部状态条，三个页面共享。
 */
import { type ReactNode } from "react";
import { Stack, Switch } from "@astryxdesign/core";
import { useUi, type PageKey } from "./store/ui";
import { ConversationList } from "./components/ConversationList";
import ChatPage from "./pages/ChatPage";
import ProfilePage from "./pages/ProfilePage";
import TracePage from "./pages/TracePage";

const NAV: Array<{ key: PageKey; index: string; label: string }> = [
  { key: "chat", index: "01", label: "控糖工作台" },
  { key: "profile", index: "02", label: "健康档案" },
  { key: "audit", index: "03", label: "合规审计" },
];

const PAGE_ICONS: Record<PageKey, ReactNode> = {
  chat: (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 4.5h12v8.5H8.5L5 16v-3H4z" />
    </svg>
  ),
  profile: (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <circle cx="10" cy="6.8" r="2.8" />
      <path d="M4.8 16c.5-2.8 2.6-4.2 5.2-4.2s4.7 1.4 5.2 4.2" />
    </svg>
  ),
  audit: (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5.5 3.5h9v13h-9z" />
      <path d="M7.8 7h4.4M7.8 10h4.4M7.8 13h2.8" />
    </svg>
  ),
};

export default function App() {
  const { page, setPage, mode, setMode } = useUi();

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
          {NAV.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`side-item${page === item.key ? " is-active" : ""}`}
              onClick={() => setPage(item.key)}
            >
              <span className="side-index">{item.index}</span>
              <span className="side-text">{item.label}</span>
            </button>
          ))}
        </nav>

        <ConversationList />

        <div className="side-foot">
          <Stack gap={2}>
            <Stack direction="horizontal" gap={2} vAlign="center">
              <span className="side-foot-label">深色模式</span>
              <Switch
                label="深色模式"
                isLabelHidden
                value={mode === "dark"}
                onChange={(checked) => setMode(checked ? "dark" : "light")}
              />
            </Stack>
          </Stack>
        </div>
      </aside>

      <div className="app-main">
        <header className="app-topbar">
          <span className="top-page-icon">{PAGE_ICONS[page]}</span>
          <div className="top-title">{NAV.find((n) => n.key === page)?.label}</div>
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
          {page === "chat" ? <ChatPage /> : null}
          {page === "profile" ? <ProfilePage /> : null}
          {page === "audit" ? <TracePage /> : null}
        </div>
      </div>
    </div>
  );
}
