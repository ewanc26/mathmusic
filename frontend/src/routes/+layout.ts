// A single client-side page: the DAW talks to the local Python server, so there is
// nothing to render on a server. Prerendering produces the static index.html shell.
export const ssr = false;
export const prerender = true;
