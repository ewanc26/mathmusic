// JSON calls to the local server. Errors carry the server's message.

async function call(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(path, options);
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) throw new Error(data?.error || `${res.status} ${res.statusText}`);
  return data;
}

export const api = {
  get: (path) => call("GET", path),
  post: (path, body) => call("POST", path, body),
  put: (path, body) => call("PUT", path, body),
};

// Formula plots are cached: the same formula and range always give the same curve.
const plotCache = new Map();

export async function plot(formula, start, end, points = 200) {
  const key = `${formula}|${start}|${end}|${points}`;
  if (plotCache.has(key)) return plotCache.get(key);
  const data = await api.post("/api/plot", { formula, start, end, points });
  if (plotCache.size > 200) plotCache.delete(plotCache.keys().next().value);
  plotCache.set(key, data);
  return data;
}
