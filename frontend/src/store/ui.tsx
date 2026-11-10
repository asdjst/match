/**
 * 顶栏级 UI 状态：页签（会话/轨迹）与 dark mode。
 * dark mode 走 <Theme mode> 持久化到 localStorage。
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type PageKey = "chat" | "trace";
export type ColorMode = "light" | "dark";

interface UiContextValue {
  page: PageKey;
  setPage: (p: PageKey) => void;
  mode: ColorMode;
  setMode: (m: ColorMode) => void;
}

const UiContext = createContext<UiContextValue | null>(null);

const MODE_STORAGE_KEY = "mrag.color-mode";

function initialMode(): ColorMode {
  try {
    const saved = localStorage.getItem(MODE_STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // ignore
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function UiProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageKey>("chat");
  const [mode, setMode] = useState<ColorMode>(initialMode);

  useEffect(() => {
    // 同步 <html data-theme>，保证刷新前无闪烁、浏览器原生控件跟随
    document.documentElement.dataset.theme = mode;
  }, [mode]);

  const value: UiContextValue = {
    page,
    setPage,
    mode,
    setMode: (m) => {
      setMode(m);
      try {
        localStorage.setItem(MODE_STORAGE_KEY, m);
      } catch {
        // ignore
      }
    },
  };

  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}

export function useUi(): UiContextValue {
  const ctx = useContext(UiContext);
  if (!ctx) throw new Error("useUi 必须在 UiProvider 内使用");
  return ctx;
}
