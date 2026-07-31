import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are loaded from disk via file:// by pywebview, not served
// from a domain root, so every reference must be relative.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
