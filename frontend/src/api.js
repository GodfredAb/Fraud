const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function get(path) {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) {
    throw new Error(`${path} -> ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => get("/api/health"),
  stats: () => get("/api/stats"),
  alerts: (limit = 25) => get(`/api/alerts?limit=${limit}`),
  recentTransactions: (limit = 25) => get(`/api/transactions/recent?limit=${limit}`),
  transaction: (txnId) => get(`/api/transactions/${txnId}`),
  suspended: () => get("/api/suspended"),
};
