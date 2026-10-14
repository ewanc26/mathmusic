// Calls to the local server. Errors carry the server's message.

import type { Asset, PlotData } from "./types";

async function parse<T>(res: Response): Promise<T> {
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const message = (data as { error?: string } | null)?.error;
    throw new Error(message || `${res.status} ${res.statusText}`);
  }
  return data as T;
}

/** fetch, but a server that isn't running gets a message the user can act on. */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch {
    throw new Error("Can't reach the mathmusic server. Check that `mathmusic serve` is still running.");
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  return parse<T>(await send(path, init));
}

export const api = {
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body: unknown) => call<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => call<T>("PUT", path, body),
};

/** POST JSON and receive a file (e.g. MIDI). */
export async function postForBlob(path: string, body: unknown): Promise<Blob> {
  const res = await send(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parse(res);
  return res.blob();
}

/** Send an audio file to be imported as a sample. */
export async function uploadAudio(file: File): Promise<Asset> {
  const res = await send("/api/assets", {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
    body: file,
  });
  return parse<Asset>(res);
}

// Formula plots are cached: the same formula and range always give the same curve.
const plotCache = new Map<string, PlotData>();

export async function plot(formula: string, start: number, end: number, points = 200): Promise<PlotData> {
  const key = `${formula}|${start}|${end}|${points}`;
  const cached = plotCache.get(key);
  if (cached) return cached;
  const data = await api.post<PlotData>("/api/plot", { formula, start, end, points });
  if (plotCache.size > 300) {
    const oldest = plotCache.keys().next().value;
    if (oldest !== undefined) plotCache.delete(oldest);
  }
  plotCache.set(key, data);
  return data;
}
