export async function apiFetch(url, initOrMethod = "GET", maybeBody = undefined) {
  // Support both apiFetch(url, 'POST', body) and apiFetch(url, { method, headers, body })
  let init = {};
  if (typeof initOrMethod === 'string') {
    init.method = initOrMethod;
    if (maybeBody !== undefined) init.body = maybeBody;
  } else if (initOrMethod && typeof initOrMethod === 'object') {
    init = { ...initOrMethod };
  } else {
    init.method = 'GET';
  }

  // Default headers
  const headers = new Headers(init.headers || {});
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');

  // Normalize body: if body is provided as object, JSON-encode it and set Content-Type
  if (init.body !== undefined && init.method && init.method.toUpperCase() !== 'GET' && init.method.toUpperCase() !== 'HEAD') {
    const hasContentType = headers.has('Content-Type');
    if (typeof init.body !== 'string') {
      init.body = JSON.stringify(init.body);
      if (!hasContentType) headers.set('Content-Type', 'application/json');
    } else if (!hasContentType) {
      // If body is already a string but no content-type specified, default to JSON
      headers.set('Content-Type', 'application/json');
    }
  }
  init.headers = headers;

  const res = await fetch(url, init);
  let resBody = {};
  try { resBody = await res.json(); } catch (_) { /* ignore non-JSON */ }
  return { body: resBody, status: res.status, ok: res.ok, success: res.status >= 200 && res.status < 400 };
}
