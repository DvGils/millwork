import path from "path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build lands inside the Python package so the wheel carries it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // Relative: the font files and lazy chunks resolve next to the stylesheet and
  // the entry, wherever the server mounts the assets (under a path prefix too).
  base: "./",
  build: {
    outDir: path.resolve(__dirname, "../src/millwork/_bundle/dist"),
    emptyOutDir: true,
    assetsDir: ".",
    manifest: true,
    sourcemap: false,
    rollupOptions: { input: path.resolve(__dirname, "src/main.tsx") },
  },
});
