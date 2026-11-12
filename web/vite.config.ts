import { defineConfig } from "vite";
import basicSsl from "@vitejs/plugin-basic-ssl";

// HTTPS is required so iPhone Safari treats the dev server as a secure context
// and allows getUserMedia over the LAN (architecture 02 §8). The certificate is
// self-signed and development-only.
export default defineConfig({
  plugins: [basicSsl()],
  server: {
    host: true,
    proxy: {
      "/sessions": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
