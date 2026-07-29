import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Single origin in production: FastAPI serves the built bundle as static
// files. The dev server proxies API calls so there is never any CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/jobs": "http://localhost:8000",
      "/loops": "http://localhost:8000",
      "/voices": "http://localhost:8000",
      "/assets": "http://localhost:8000",
      "/generations": "http://localhost:8000",
      "/presets": "http://localhost:8000",
      "/storyboards": "http://localhost:8000",
      "/styles": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
