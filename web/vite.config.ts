import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Single origin in production: FastAPI serves the built bundle as static
// files. The dev server proxies API calls so there is never any CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      [
        "/jobs", "/loops", "/voices", "/assets", "/generations", "/presets",
        "/storyboards", "/styles", "/projects", "/timelines", "/healthz",
        "/identities", "/images", "/effects", "/emotions", "/music", "/metrics", "/stats",
        "/config", "/prompts", "/rentals",
      ].map((route) => [route, "http://localhost:8000"]),
    ),
  },
});
