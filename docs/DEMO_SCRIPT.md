# KSP CIAP — Live Demo Script
### Total run time: ~6 minutes (5 min talk + 1 min buffer for questions)

**Setup before you start:** have the dashboard artifact open in one tab and
`/docs` (Swagger UI) open in another if you want to show the live API too.
Know your login: `KSP-3003 / admin123` shows the full permission set.

---

### 0:00 – Open (30 sec)
> "What you're looking at is CIAP — the Crime Intelligence and Analytical
> Platform — a full-stack prototype built for Karnataka State Police. It
> takes crime data that today sits in siloed district spreadsheets and turns
> it into a live, predictive intelligence hub. I'll walk through the four
> things it does, then show you it's a real backend, not just a UI mockup."

### 0:30 – Geospatial Hotspots (60 sec)
*[Switch to Geospatial Hotspots tab, hit Play]*
> "This is a 24-hour animated density map across Karnataka's districts.
> Watch the hour ticking up — density shifts through the day, property
> crime clusters differently than assault does at night. An analyst can
> scrub to any hour and immediately see where patrol resources are
> under-allocated right now, not last week."

### 1:30 – Predictive Risk (60 sec)
*[Switch to Predictive Risk tab]*
> "Every district gets a live risk score, 0 to 100, computed by comparing
> current incident volume against its own rolling baseline — that's an
> IsolationForest model under the hood, so there's no hand-tuned threshold
> per district to maintain. Bengaluru Urban is pulsing red at 82 — that's
> the anomaly trigger firing. This chart on the right shows actual volume
> against baseline over the day, so you can see exactly where it diverged."

### 2:30 – Link Analysis (75 sec)
*[Switch to Link Analysis tab, click a suspect node]*
> "This is the network graph — every red node is a suspect, every teal node
> is a location. When I click a suspect, it highlights every location
> they've been tied to and every other suspect they share a location with.
> The query behind this is: 'find everyone who's been at the same location
> as this person in the last 30 days.' In a relational database that's an
> expensive multi-join that gets worse the deeper you go. In Neo4j it's a
> single graph traversal — that's why we run this as a separate graph store
> instead of forcing it into SQL."

### 3:45 – RBAC / Alerts (45 sec)
*[Switch to Alert Center tab, then switch role selector to Field Officer]*
> "Alerts are role-gated. As an Administrator I can acknowledge this
> critical alert. Watch what happens when I switch to Field Officer —
> [switch role] — the acknowledge button disappears. That's not just a UI
> choice, it's enforced on the backend too: the same permission check runs
> server-side on every request, so it can't be bypassed by calling the API
> directly."

### 4:30 – It's a real backend (45 sec)
*[Optional: switch to /docs tab]*
> "This isn't a static frontend. There's a FastAPI backend with JWT auth,
> a PostgreSQL + PostGIS schema for the spatial data, and this Swagger UI
> is auto-generated from the same code — every endpoint you see here is
> live and callable right now. It runs locally with one `uvicorn` command,
> or the whole stack — API, Postgres, Neo4j — comes up with one
> `docker compose up`, ready to deploy to Railway, AWS, or GCP."

### 5:15 – Close (30 sec)
> "So: geospatial hotspots, a real criminal-network graph, predictive risk
> scoring, and role-based access — all wired to a backend that's built to
> be handed to an engineering team, not just demoed once and shelved. Happy
> to go deeper into any layer — the code, the schema, or the deployment
> setup."

---

### If asked "how would this scale to real KSP data?"
> "The architecture doesn't change — PostGIS and Neo4j both handle
> production-scale volumes. What changes is: real Excel/CSV ingestion from
> each district station through the Pandas cleaning pipeline already
> stubbed in, and training the IsolationForest model on real historical FIR
> data instead of the seeded demo data."

### If asked "what's the biggest technical risk?"
> "Data quality at ingestion — district-level CSVs are rarely clean.
> That's why the ingestion layer is a separate, auditable step rather than
> writing raw uploads straight into the database."
