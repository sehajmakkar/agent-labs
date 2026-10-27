import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development, Vite serves the UI on :5173 and forwards API calls to `lab ui` on :8000.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
});
