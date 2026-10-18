import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// În dev, cererile /api merg la vedit-server (http://127.0.0.1:8000).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } } },
});
