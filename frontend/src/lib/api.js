// ---------------------------------------------------------------------
// KSP CIAP API client
// Thin fetch wrapper around the FastAPI backend. Base URL comes from
// VITE_API_URL (see .env.example) so the same build works against local
// dev, staging, or production backends without code changes.
// ---------------------------------------------------------------------

export const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const TOKEN_KEY = "ciap_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

// Thrown when the backend rejects the current token so callers (AuthContext)
// can react by logging the user out.
export class UnauthorizedError extends Error {
  constructor(message) {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, { method = "GET", body, form = false, auth = true } = {}) {
  const headers = {};
  if (!form && body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    });
  } catch (err) {
    throw new ApiError(
      `Could not reach the CIAP backend at ${API_BASE_URL}. Is it running?`,
      0
    );
  }

  if (res.status === 401) {
    setToken(null);
    throw new UnauthorizedError("Session expired. Please sign in again.");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* response body wasn't JSON */
    }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
  }

  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------
export function login(badgeNumber, password) {
  const form = new URLSearchParams();
  form.set("username", badgeNumber);
  form.set("password", password);
  return request("/api/v1/auth/login", { method: "POST", body: form, form: true, auth: false });
}

export function whoami() {
  return request("/api/v1/auth/me");
}

// ---------------------------------------------------------------------
// Reference data
// ---------------------------------------------------------------------
export function getDistricts() {
  return request("/api/v1/districts");
}

// ---------------------------------------------------------------------
// Geospatial
// ---------------------------------------------------------------------
export function getHotspotMatrix(sinceHours = 240) {
  return request(`/api/v1/incidents/hotspots/matrix?since_hours=${sinceHours}`);
}

export function getIncidents({ district, sinceHours = 24, page = 1, pageSize = 50 } = {}) {
  const params = new URLSearchParams({ since_hours: sinceHours, page, page_size: pageSize });
  if (district) params.set("district", district);
  return request(`/api/v1/incidents?${params.toString()}`);
}

// ---------------------------------------------------------------------
// Predictive risk
// ---------------------------------------------------------------------
export function getRiskScores() {
  return request("/api/v1/risk/districts");
}

export function getIncidentsTrend(hours = 24) {
  return request(`/api/v1/incidents/trend?hours=${hours}`);
}

export function recomputeRisk() {
  return request("/api/v1/risk/recompute", { method: "POST" });
}

// ---------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------
export function getAlerts() {
  return request("/api/v1/alerts");
}

export function ackAlert(alertId) {
  return request(`/api/v1/alerts/${alertId}/ack`, { method: "POST" });
}

// ---------------------------------------------------------------------
// Link analysis
// ---------------------------------------------------------------------
export function getFullGraph() {
  return request("/api/v1/graph/full");
}

// ---------------------------------------------------------------------
// Ingestion
// ---------------------------------------------------------------------
export function getIngestStatus() {
  return request("/api/v1/ingest/status");
}

export function ingestCsvRows(rows) {
  return request("/api/v1/ingest/csv", { method: "POST", body: rows });
}
