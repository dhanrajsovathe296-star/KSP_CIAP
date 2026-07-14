# KSP CIAP — Deployment Guide

## 1. Run locally (fastest path, SQLite, zero setup)

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive Swagger UI. Demo data
seeds automatically on first boot. Log in at `/api/v1/auth/login` with any
of the demo accounts:

| Badge number | Password    | Role    |
|--------------|-------------|---------|
| KSP-1001     | officer123  | officer |
| KSP-2002     | analyst123  | analyst |
| KSP-3003     | admin123    | admin   |

## 2. Run the full stack with Docker Compose (Postgres + Neo4j + API)

```bash
docker compose up --build
```

This starts:
- **backend** on `:8000`
- **postgres** (PostGIS) on `:5432`, auto-loaded with `schema_postgis.sql`
- **neo4j** on `:7474` (browser) / `:7687` (bolt)

To point the API at Postgres instead of SQLite, uncomment `DATABASE_URL` in
`docker-compose.yml`, then re-run `docker compose up --build`.

## 3. Deploy the backend

### Option A — Railway / Render (simplest, free tier available)
1. Push this folder to a GitHub repo.
2. On Railway or Render: **New → Web Service → connect repo**.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add a managed Postgres add-on (both platforms offer one) and set
   `DATABASE_URL` to the connection string it gives you.
6. Set `SECRET_KEY` and `CORS_ORIGINS` in the service's environment tab.

### Option B — Docker on any VPS (DigitalOcean, AWS EC2, GCP Compute)
```bash
docker build -t ksp-ciap-backend .
docker run -d -p 8000:8000 \
  -e SECRET_KEY=your-real-secret \
  -e DATABASE_URL=postgresql://user:pass@your-db-host:5432/ciap \
  ksp-ciap-backend
```
Put nginx or Caddy in front for TLS termination and a custom domain.

### Option C — AWS ECS / Fargate (production-grade, auto-scaling)
1. Push the image to ECR: `docker build -t ciap . && docker push <ecr-repo>`
2. Create an ECS Fargate service from the image, target port `8000`.
3. Use RDS (Postgres, with the PostGIS extension enabled) for the database
   and set `DATABASE_URL` as a Secrets Manager–backed environment variable.
4. Put an Application Load Balancer in front for HTTPS + health checks
   (the `/health` endpoint is already wired for this).

### Option D — Google Cloud Run (serverless containers)
```bash
gcloud run deploy ksp-ciap-backend \
  --source . \
  --set-env-vars SECRET_KEY=your-real-secret \
  --set-env-vars DATABASE_URL=postgresql://... \
  --allow-unauthenticated
```

## 4. Deploy the frontend (React dashboard)

The dashboard is a self-contained React component. To ship it as a real
site:
1. Scaffold with Vite: `npm create vite@latest ciap-frontend -- --template react`
2. Copy `CIAP_Dashboard.jsx` in as `src/App.jsx`, install `recharts` and
   `lucide-react`.
3. `npm run build`, then deploy the `dist/` folder to **Vercel**, **Netlify**,
   or an S3 + CloudFront bucket.
4. Point it at the deployed backend by replacing the mock data calls with
   `fetch` calls to your backend's `/api/v1/...` routes, using the token
   returned from `/api/v1/auth/login`.

## 5. Run the test suite

```bash
pip install -r requirements.txt   # pytest + httpx are already listed
pytest tests/ -v
```

Tests spin up the app against a throwaway temp SQLite file (never your real
`ciap.db`) and cover: login + bad-password rejection, JWT identity, RBAC
(officer blocked from admin-only actions), seeded districts/incidents/risk
scores, the shared-location graph-neighbors endpoint, and CSV ingestion
including FIR-number deduplication. Wire this into CI (GitHub Actions,
GitLab CI, etc.) so every push is verified automatically.

## 6. Database migrations (once you outgrow auto-create)

This prototype uses `Base.metadata.create_all()` for simplicity. For real
schema evolution, add Alembic:
```bash
pip install alembic
alembic init migrations
# edit migrations/env.py to import Base from main.py
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

## 7. Production checklist

- [ ] Rotate `SECRET_KEY` to a long random value, store as a secret (not in git)
- [ ] Set `CORS_ORIGINS` to your real frontend domain, not `*`
- [ ] Switch `DATABASE_URL` to managed Postgres with PostGIS enabled
- [ ] Replace the in-memory rate limiter with `slowapi` + Redis if you scale
      past one instance
- [ ] Wire the Neo4j driver into `/api/v1/graph/neighbors/{suspect_name}`
- [ ] Put the risk-score job (`compute_risk_scores_job`) on a scheduler
      (APScheduler, Celery beat, or a platform cron hitting
      `POST /api/v1/risk/recompute`)
- [ ] Add HTTPS (Caddy/nginx reverse proxy, or the PaaS's built-in TLS)
- [ ] Turn on structured log shipping (e.g., to CloudWatch or Better Stack)
- [ ] Run `pytest tests/ -v` in CI on every push before deploying
- [ ] Replace the stdlib-csv `/api/v1/ingest/csv` body with the full Pandas
      cleaning pipeline (column normalization, geocoding, taxonomy mapping)
      once real district files are available
