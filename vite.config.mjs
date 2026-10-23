import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

export default defineConfig({
  resolve: { alias: { "@": resolve(import.meta.dirname, "frontend/react") } },
  plugins: [tailwindcss()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "frontend/assets",
    emptyOutDir: false,
    target: "es2020",
    modulePreload: false,
    chunkSizeWarningLimit: 520,
    cssCodeSplit: false,
    rollupOptions: {
      input: resolve(import.meta.dirname, "frontend/react/entry.jsx"),
      output: {
        entryFileNames: "atlas-interactions.js",
        assetFileNames: "atlas-interactions.[ext]",
        codeSplitting: false,
      },
      onwarn(warning, warn) {
        // This is a browser-only bundle; React server directives have no runtime role.
        if (
          warning.code === "MODULE_LEVEL_DIRECTIVE" &&
          warning.message.includes("use client")
        )
          return;
        warn(warning);
      },
    },
  },
});
