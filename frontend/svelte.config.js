import { readFileSync } from "node:fs";
import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // SvelteKit's default version is the build time, which renames every hashed file on
    // each build. Naming the version after the package keeps a rebuild of the same source
    // byte-identical, so the committed bundle can be checked against the source.
    version: { name: pkg.version },
    // The app is a single client-side page; the Python server (mathmusic serve)
    // serves the built files from the package so no Node is needed at runtime.
    adapter: adapter({ pages: "../src/mathmusic/web", assets: "../src/mathmusic/web", strict: true }),
  },
};

export default config;
