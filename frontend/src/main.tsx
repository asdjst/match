import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Astryx 样式三件套，顺序即 layer 级联顺序（reset → 组件 → 主题 token）
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@astryxdesign/theme-neutral/theme.css";

// React Flow 基础样式（DAG 页）
import "@xyflow/react/dist/style.css";

// 少量自定义 CSS（布局栅格 + React Flow 节点外观，全部走 Astryx token 适配深浅色）
import "./index.css";

import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { UiProvider, useUi } from "./store/ui";
import { RunsProvider } from "./store/runs";
import App from "./App";

function ThemedApp() {
  const { mode } = useUi();
  return (
    <Theme theme={neutralTheme} mode={mode}>
      <App />
    </Theme>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UiProvider>
      <RunsProvider>
        <ThemedApp />
      </RunsProvider>
    </UiProvider>
  </StrictMode>,
);
