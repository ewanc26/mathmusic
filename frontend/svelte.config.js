import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // The app is a single client-side page; the Python server (mathmusic serve)
    // serves the built files from the package so no Node is needed at runtime.
    adapter: adapter({ pages: "../src/mathmusic/web", assets: "../src/mathmusic/web", strict: true }),
  },
};

export default config;
