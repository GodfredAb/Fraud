const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_KEY = "momo_auth_token";

let authToken = localStorage.getItem(TOKEN_KEY) || null;
let onUnauthorized = null;

export function setAuthToken(token) {
  authToken = token;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getAuthToken() {
  return authToken;
}

/** App.jsx registers a handler so a real 401 from any call (token expired,
 * revoked, or never set) drops the user back to the login screen instead of
 * just failing silently - the same enforcement point the API itself uses. */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (res.status === 401) {
    setAuthToken(null);
    onUnauthorized?.();
    throw new Error("Session expired - please log in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      // body wasn't JSON - keep statusText
    }
    throw new Error(`${path} -> ${res.status} ${detail}`);
  }
  return res.json();
}

const get = (path) => request(path);
const post = (path, body) =>
  request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => get("/api/health"),
  login: (username, password) => post("/api/login", { username, password }),
  logout: () => post("/api/logout", {}),
  me: () => get("/api/me"),
  stats: () => get("/api/stats"),
  alerts: (limit = 25) => get(`/api/alerts?limit=${limit}`),
  recentTransactions: (limit = 25) => get(`/api/transactions/recent?limit=${limit}`),
  transaction: (txnId) => get(`/api/transactions/${txnId}`),
  suspended: () => get("/api/suspended"),
  fraudLocations: (limit = 20) => get(`/api/fraud-locations?limit=${limit}`),
  reports: (range = "7d") => get(`/api/reports?range=${range}`),
  subscribers: (q = "", limit = 30) => get(`/api/subscribers?q=${encodeURIComponent(q)}&limit=${limit}`),
  subscriberProfile: (userId) => get(`/api/subscribers/${encodeURIComponent(userId)}`),
  search: (q) => get(`/api/search?q=${encodeURIComponent(q)}`),
  config: () => get("/api/config"),
  systemLog: (limit = 50) => get(`/api/system-log?limit=${limit}`),
};
