import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// `pnpm dev` proxies the API to a running `mathmusic serve --no-browser`.
// The server only accepts its own origin, so the proxy presents that origin.
const API = process.env.MATHMUSIC_API ?? "http://127.0.0.1:8765";

const proxy = {
  target: API,
  changeOrigin: true,
  headers: { origin: API },
};

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: { proxy: { "/api": proxy, "/audio": proxy } },
});
