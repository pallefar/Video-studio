import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Single origin in production: FastAPI serves the built bundle as static
// files. The dev server proxies API calls so there is never any CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/jobs": "http://localhost:8000",
      "/loops": "http://localhost:8000",
      "/voices": "http://localhost:8000",
      "/assets": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
