import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5194,
    strictPort: true,
    hmr: {
      protocol: "ws",
      host: "127.0.0.1",
      clientPort: 5194
    }
  }
});
