import { Button, Stack, Switch } from "@astryxdesign/core";
import { useUi } from "./store/ui";
import { ConversationList } from "./components/ConversationList";
import ChatPage from "./pages/ChatPage";

const CHAT_ICON = (
  <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4.5h12v8.5H8.5L5 16v-3H4z" />
  </svg>
);

export default function App() {
  const { mode, setMode } = useUi();

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
          <Button label="控糖工作台" variant="secondary" icon={CHAT_ICON} aria-current="page" width="100%" />
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
          <span className="top-page-icon">{CHAT_ICON}</span>
          <div className="top-title">控糖工作台</div>
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
          <ChatPage />
        </div>
      </div>
    </div>
  );
}
