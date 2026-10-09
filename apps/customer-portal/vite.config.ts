import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: env.CONTROL_API_PROXY_TARGET ? { "/api": { target: env.CONTROL_API_PROXY_TARGET, changeOrigin: true } } : undefined,
    },
    build: { sourcemap: false },
  };
});