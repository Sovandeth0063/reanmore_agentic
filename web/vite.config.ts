import { defineConfig } from "vite";
import basicSsl from "@vitejs/plugin-basic-ssl";

// HTTPS gives the laptop browser a secure context for the webcam and
// microphone (getUserMedia). The certificate is self-signed and development
// only; the dev server proxies the session API on the same origin.
export default defineConfig({
  plugins: [basicSsl()],
  server: {
    host: true,
    proxy: {
      "/sessions": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/tts": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
});
