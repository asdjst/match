import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 后端默认 uvicorn 端口 8000（见根 README 快速开始）；可用 BACKEND_ORIGIN 覆盖。
const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendOrigin,
        changeOrigin: true,
      },
    },
  },
});
