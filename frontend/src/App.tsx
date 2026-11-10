/**
 * 应用外壳：顶栏（品牌 + 页签 + 后端状态 + 深色开关）与两页切换。
 */
import { Badge, SegmentedControl, SegmentedControlItem, Switch, TopNav } from "@astryxdesign/core";
import { useUi } from "./store/ui";
import { useRuns } from "./store/runs";
import ChatPage from "./pages/ChatPage";
import TracePage from "./pages/TracePage";

export default function App() {
  const { page, setPage, mode, setMode } = useUi();
  const { transportKind } = useRuns();

  return (
    <div className="app-shell">
      <TopNav
        heading="Multi-Agent RAG"
        startContent={
          <Badge
            variant={
              transportKind === "live" ? "success" : transportKind === "probing" ? "info" : "warning"
            }
            label={
              transportKind === "live"
                ? "后端已连接"
                : transportKind === "probing"
                  ? "探测后端…"
                  : "Mock 模式"
            }
          />
        }
        centerContent={
          <SegmentedControl
            label="页面切换"
            value={page}
            onChange={(v) => setPage(v === "trace" ? "trace" : "chat")}
          >
            <SegmentedControlItem value="chat" label="会话" />
            <SegmentedControlItem value="trace" label="轨迹" />
          </SegmentedControl>
        }
        endContent={
          <Switch
            label="深色模式"
            isLabelHidden
            value={mode === "dark"}
            onChange={(checked) => setMode(checked ? "dark" : "light")}
          />
        }
      />
      {page === "chat" ? <ChatPage /> : <TracePage />}
    </div>
  );
}
