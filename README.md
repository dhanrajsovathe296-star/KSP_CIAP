# KSP CIAP — Crime Intelligence & Analytical Platform

Full-stack prototype for Karnataka State Police: geospatial hotspot
detection, graph-based link analysis, predictive risk scoring, and
role-based alerting.

## Folder guide

```
backend/          FastAPI service — runs on SQLite out of the box,
                   Postgres/PostGIS in production via one env var.
  main.py          The API: auth, RBAC, incidents, risk scoring, alerts,
                   suspects/graph-neighbors, CSV ingestion.
  tests/test_api.py   Automated pytest smoke tests (auth, RBAC, seeded
                       data, ingestion, dedup) — run before every deploy.
  schema_postgis.sql  Full Postgres/PostGIS schema (production data model).
  neo4j_graph.cypher  Graph model + link-analysis Cypher queries.
  Dockerfile, docker-compose.yml, .env.example   Local + containerized run.
  requirements.txt    Python dependencies (core + commented production extras).

frontend/
  src/CIAP_Dashboard.jsx  Interactive React dashboard (hotspot map, link-analysis
                       graph, predictive risk panel, alert center, ingestion status)
                       — now fully wired to the FastAPI backend, no mock data.
  src/LoginScreen.jsx  Badge-number/password login screen (JWT auth).
  src/lib/api.js       Typed fetch wrapper for every backend endpoint.
  src/lib/AuthContext.jsx  Login/logout/session state, token persistence.
  src/lib/geo.js        Projects real district lat/lon onto the map view.
  .env.example          VITE_API_URL — point the build at any backend.

docs/
  KSP_CIAP_Technical_Architecture.pdf   Architecture, methodology, API
                                        summary, security, deployment options.
  KSP_CIAP_Pitch_Deck.pptx              10-slide pitch deck with the demo
                                        script in each slide's speaker notes.
  DEMO_SCRIPT.md                        Standalone 6-minute live-demo script.
  DEPLOYMENT.md                         Step-by-step deploy guide (Railway,
                                         Render, Docker/VPS, AWS ECS, Cloud Run)
                                         plus a production checklist.
```

## Quickest path to running it

Backend:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs`. Demo logins:

| Badge number | Password    | Role    |
|--------------|-------------|---------|
| KSP-1001     | officer123  | officer |
| KSP-2002     | analyst123  | analyst |
| KSP-3003     | admin123    | admin   |

Frontend (in a second terminal):

```bash
cd frontend
cp .env.example .env    # VITE_API_URL defaults to http://localhost:8000
npm install
npm run dev
```

Open `http://localhost:5173` and sign in with any of the badge numbers above
— the dashboard is now driven entirely by the backend you just started.

Run the tests:

```bash
pytest tests/ -v
```

Run the full stack (API + PostGIS + Neo4j) with Docker:

```bash
docker compose up --build
```

Full deployment instructions (Railway, a VPS, AWS ECS, Google Cloud Run)
are in `docs/DEPLOYMENT.md`.

## What changed in this audit pass (frontend↔backend integration)

The backend was already production-shaped; the frontend was a disconnected,
100%-client-side mock. This pass wires them together end to end:

- Added a JWT login screen (`LoginScreen.jsx`) and `AuthContext` — the
  dashboard is now gated on a real `/api/v1/auth/login` session instead of
  a fake local role-switcher dropdown.
- Added `src/lib/api.js`, a typed fetch client for every backend route
  (auth, districts, hotspots, risk, trend, alerts, graph, ingestion), with
  401 handling that logs the user out and surfaces backend error messages.
- Replaced every mock data generator in `CIAP_Dashboard.jsx`
  (`districtHourlySeries`, `buildSuspectGraph`, `seedAlerts`, hardcoded risk
  gauges, fake ingestion sync status) with live API data. No client-side
  random data generation remains.
- Backend additions needed to support the real UI (previously missing):
  - `GET /api/v1/incidents/hotspots/matrix` — one-shot 24-hour-bucket
    incident matrix per district, so the time-slider/animation reads a
    local array instead of firing a request per hour tick.
  - `GET /api/v1/incidents/trend` — real actual-vs-historical-baseline
    series for the predictive dashboard's area chart.
  - `GET /api/v1/graph/full` — full suspect/location graph (SQL joins over
    `incident_suspects`) for the Link Analysis force-graph, replacing the
    client-side `buildSuspectGraph()` mock.
  - `GET /api/v1/ingest/status` / new `ingest_logs` table — real per-district
    last-sync time, row counts, and status for the Data Ingestion tab; the
    CSV ingestion endpoint now writes a log entry on every run.
  - `District.lat` / `District.lon` columns (were computed at seed time but
    never persisted) plus `src/lib/geo.js` on the frontend to project them
    onto the existing 0–100 hotspot map, replacing hand-picked mock x/y.
- Role permissions and alert-acknowledge visibility are now driven by the
  authenticated user's actual JWT permissions, not a client-side dropdown
  that could claim any role.
- Added regression tests for all five new endpoints.

See prior pass notes below for backend-only fixes made before this round.



- `/api/v1/graph/neighbors/{suspect_name}` previously returned a hard
  `501 Not Implemented`. It now runs a real SQL-based shared-location query
  against seeded suspect/incident data, with the Neo4j production path
  documented inline for when that's wired in.
- The `suspects` table existed but was never populated or exposed — seed
  data now links suspects to incidents, and `/api/v1/suspects` /
  `/api/v1/districts` list endpoints were added.
- The CSV ingestion endpoint (present in the original skeleton) had been
  dropped from the production rewrite — it's back as `/api/v1/ingest/csv`,
  with FIR-number deduplication and per-row error reporting.
- All stored timestamps were switched to a single naive-UTC convention
  (`utcnow()` helper) instead of mixing timezone-aware and naive datetimes
  across models.
- The dashboard's risk-by-district bar chart was nesting invalid `<Bar>`
  elements instead of `<Cell>` for per-bar coloring — fixed, so high-risk
  districts now render in red, mid in amber, low in teal.
- A pytest suite (`tests/test_api.py`) was added covering auth, RBAC
  enforcement, seeded data, graph neighbors, and ingestion — there were no
  automated tests before this pass.
