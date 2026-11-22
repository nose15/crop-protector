import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend FastAPI: domyślnie :8000. Inny port: BACKEND_PORT=8001 npm run dev
const backend = `http://127.0.0.1:${process.env.BACKEND_PORT || 8000}`;

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": backend } },
});
