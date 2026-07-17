/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev-only: the browser talks same-origin, Vite forwards to the backend.
    // In Docker, nginx plays this role (see Dockerfile + nginx.conf).
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "node",
    passWithNoTests: true,
  },
});
