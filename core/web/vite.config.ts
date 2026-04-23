import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_PORT = process.env.ZENWIKI_API_PORT || "3334";
const API_TARGET = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/zenwiki/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/tree": API_TARGET,
      "/doc": API_TARGET,
      "/search": API_TARGET,
      "/query": API_TARGET,
      "/status": API_TARGET,
      "/crystallize": API_TARGET,
      "/rebuild-index": API_TARGET,
      "/refresh-index": API_TARGET,
    },
  },
});
