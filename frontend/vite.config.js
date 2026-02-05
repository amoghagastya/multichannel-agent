import { defineConfig } from "vite";

export default defineConfig({
  base: "/webrtc/",
  build: {
    outDir: "dist",
    emptyOutDir: true
  },
  server: {
    port: 5173
  }
});
