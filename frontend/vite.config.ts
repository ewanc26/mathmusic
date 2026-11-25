import { readFileSync } from "node:fs";
import adapter from "@sveltejs/adapter-static";
import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// `pnpm dev` proxies the API to a running `mathmusic serve --no-browser`.
// The server only accepts its own origin, so the proxy presents that origin.
const API = process.env.MATHMUSIC_API ?? "http://127.0.0.1:8765";

const proxy = {
  target: API,
  changeOrigin: true,
  headers: { origin: API },
};

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit({
      preprocess: vitePreprocess(),
      // SvelteKit's default version is the build time, which renames every hashed file on
      // each build. Naming the version after the package keeps a rebuild of the same source
      // byte-identical, so the committed bundle can be checked against the source.
      version: { name: pkg.version },
      // The app is a single client-side page; the Python server (mathmusic serve)
      // serves the built files from the package so no Node is needed at runtime.
      adapter: adapter({ pages: "../src/mathmusic/web", assets: "../src/mathmusic/web", strict: true }),
    }),
  ],
  server: { proxy: { "/api": proxy, "/audio": proxy } },
});
