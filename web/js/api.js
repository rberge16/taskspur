export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code || null; }
}

function describe(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const field = (item.loc || []).filter((p) => !['body', 'query'].includes(p)).join(' › ');
      return field ? `${field}: ${item.msg}` : item.msg;
    }).join(' · ');
  }
  return 'Unbekannter Fehler.';
}

export async function api(method, url, body) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: { 'X-Requested-With': 'taktspur', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('Taktspur ist nicht erreichbar. Läuft das Programm noch?', 0);
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(describe(data.detail), response.status, data.code);
  return data;
}

export const get = (url) => api('GET', url);
export const post = (url, body = {}) => api('POST', url, body);
export const put = (url, body) => api('PUT', url, body);
export const del = (url) => api('DELETE', url);

/** Roher Datei-Upload (z. B. FIT). Der Body ist die Datei selbst, kein JSON. */
export async function upload(url, bytes) {
  let response;
  try {
    response = await fetch(url, { method: 'POST', headers: { 'X-Requested-With': 'taktspur', 'Content-Type': 'application/octet-stream' }, body: bytes });
  } catch {
    throw new ApiError('Taktspur ist nicht erreichbar. Läuft das Programm noch?', 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(describe(data.detail), response.status, data.code);
  return data;
}
