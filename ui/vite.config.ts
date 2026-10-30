import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development, Vite serves the UI on :5173 and forwards API calls to `lab ui` on :8000.
// `npm run build:static` (mode "static") is the read-only demo (D-057): it copies the data that
// `lab export-static` wrote to ui/static/data into the site. The normal build leaves it out,
// since `lab ui` serves the API.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  publicDir: mode === "static" ? "static" : false,
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
}));
