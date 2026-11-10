/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 置为 "1" 时强制使用内置 Mock 数据（无后端演示模式） */
  readonly VITE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
