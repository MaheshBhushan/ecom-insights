import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies /api to the FastAPI dashboard app (uvicorn on :8001).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.DASHBOARD_API ?? "http://localhost:8001" } },
});
