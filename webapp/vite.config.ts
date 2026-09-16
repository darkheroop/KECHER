import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Served by the bot at /miniapp/ (absolute base so assets always resolve).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/miniapp/",
  build: { outDir: "dist", emptyOutDir: true },
});
