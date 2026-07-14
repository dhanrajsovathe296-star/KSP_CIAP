"""
KSP CIAP — Production FastAPI backend
======================================
Runs out of the box on SQLite (zero setup) and switches to Postgres/PostGIS
in one env var for production. Auto-seeds demo data on first boot so the
API is immediately explorable.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload
    open http://127.0.0.1:8000/docs

Switch to Postgres in production:
    export DATABASE_URL=postgresql://user:pass@host:5432/ciap
"""

import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
    create_engine, select, func
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ---------------------------------------------------------------------
# Configuration (12-factor: everything overridable via env vars)
# ---------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ciap.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("ciap")

def utcnow() -> datetime:
    """Naive UTC timestamp — SQLite's DATETIME type doesn't round-trip
    timezone-aware values, so every stored timestamp in this app is naive
    UTC by convention (Postgres deployments should use TIMESTAMPTZ and can
    switch this back to timezone-aware if desired)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------
# ORM models
# NOTE: lat/lon are plain floats here for SQLite portability. On Postgres,
# swap to GeoAlchemy2's Geometry(POINT, 4326) to match schema_postgis.sql
# 1:1 and get GIST-indexed spatial queries.
# ---------------------------------------------------------------------
class District(Base):
    __tablename__ = "districts"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    population_lakhs = Column(Float, default=0)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    badge_number = Column(String, unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="officer")  # officer | analyst | admin
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    fir_number = Column(String, unique=True)
    district_id = Column(Integer, ForeignKey("districts.id"))
    crime_type = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    modus_operandi = Column(Text)
    district = relationship("District")


class Suspect(Base):
    __tablename__ = "suspects"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String)
    risk_flag = Column(Boolean, default=False)


class IncidentSuspect(Base):
    """
    Join table linking suspects to incidents (mirrors incident_suspects in
    schema_postgis.sql). This is what powers the SQL-based shared-location
    fallback for /api/v1/graph/neighbors — the same relationship also gets
    mirrored into Neo4j in production for deeper multi-hop traversal.
    """
    __tablename__ = "incident_suspects"
    incident_id = Column(String, ForeignKey("incidents.id"), primary_key=True)
    suspect_id = Column(String, ForeignKey("suspects.id"), primary_key=True)
    role = Column(String, default="person_of_interest")  # primary | accomplice | person_of_interest


class RiskScore(Base):
    __tablename__ = "risk_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(Integer, ForeignKey("districts.id"))
    score = Column(Float, nullable=False)
    baseline = Column(Float, nullable=False)
    is_anomaly = Column(Boolean, default=False)
    computed_at = Column(DateTime, default=utcnow)
    district = relationship("District")


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    district_id = Column(Integer, ForeignKey("districts.id"))
    level = Column(String, nullable=False)  # info | warning | critical
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    acknowledged_by = Column(String, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    district = relationship("District")


class IngestLog(Base):
    """
    Records one row per district ingestion run (CSV upload or seed) so the
    Data Ingestion tab can show real last-sync times / row counts / status
    instead of client-side mock data.
    """
    __tablename__ = "ingest_logs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    district_id = Column(Integer, ForeignKey("districts.id"))
    rows_received = Column(Integer, default=0)
    rows_inserted = Column(Integer, default=0)
    rows_skipped = Column(Integer, default=0)
    status = Column(String, default="synced")  # synced | schema_drift
    synced_at = Column(DateTime, default=utcnow)
    district = relationship("District")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------
# Password hashing (stdlib pbkdf2 — no bcrypt/passlib binary dependency,
# keeps the container image small and avoids native-build failures on
# constrained hosts).
# ---------------------------------------------------------------------
def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or uuid.uuid4().hex
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return hmac.compare_digest(check, digest)


# ---------------------------------------------------------------------
# JWT auth
# ---------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


class TokenPayload(BaseModel):
    sub: str
    role: str
    full_name: str


def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenPayload(sub=payload["sub"], role=payload["role"], full_name=payload["full_name"])
    except (JWTError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


ROLE_PERMS = {
    "officer": {"view"},
    "analyst": {"view", "annotate", "export"},
    "admin": {"view", "annotate", "export", "assign", "dismiss"},
}


def require_permission(perm: str):
    def _dep(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if perm not in ROLE_PERMS.get(user.role, set()):
            raise HTTPException(status_code=403, detail=f"Role '{user.role}' lacks '{perm}' permission")
        return user
    return _dep


# ---------------------------------------------------------------------
# Very small fixed-window rate limiter (per client IP) — dependency-free.
# Swap for slowapi + Redis in a multi-instance deployment.
# ---------------------------------------------------------------------
_rate_buckets: dict[str, list[float]] = {}


def rate_limit(max_requests: int = 60, window_seconds: int = 60):
    def _dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = _rate_buckets.setdefault(ip, [])
        bucket[:] = [t for t in bucket if now - t < window_seconds]
        if len(bucket) >= max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded, slow down")
        bucket.append(now)
    return _dep


# ---------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fir_number: Optional[str]
    crime_type: str
    lat: float
    lon: float
    occurred_at: datetime
    modus_operandi: Optional[str] = None


class PaginatedIncidents(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[IncidentOut]


class RiskScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    district: str
    score: float
    baseline: float
    is_anomaly: bool
    computed_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    district: str
    level: str
    message: str
    created_at: datetime
    acknowledged: bool


class HealthOut(BaseModel):
    status: str
    db: str
    time: datetime


# ---------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------
app = FastAPI(
    title="KSP Crime Intelligence & Analytical Platform",
    version="1.0.0",
    description=(
        "Geospatial hotspot, graph-based link analysis, and predictive risk "
        "scoring API for the Karnataka State Police CIAP."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.1f}ms)")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------
# Seed data — runs once at startup if the DB is empty, so /docs is
# explorable immediately with zero manual setup.
# ---------------------------------------------------------------------
DEMO_DISTRICTS = [
    ("Bengaluru Urban", 96, 12.9716, 77.5946),
    ("Mysuru", 32, 12.2958, 76.6394),
    ("Mangaluru", 21, 12.9141, 74.8560),
    ("Hubballi-Dharwad", 19, 15.3647, 75.1240),
    ("Belagavi", 25, 15.8497, 74.4977),
    ("Kalaburagi", 26, 17.3297, 76.8343),
]
CRIME_TYPES = ["Theft", "Assault", "Cyber Fraud", "Narcotics", "Burglary", "MV Theft"]
DEMO_USERS = [
    ("KSP-1001", "Asha Rao", "officer", "officer123"),
    ("KSP-2002", "Vikram Shetty", "analyst", "analyst123"),
    ("KSP-3003", "Admin User", "admin", "admin123"),
]


def seed_if_empty(db: Session):
    if db.query(District).count() > 0:
        return
    logger.info("Seeding demo data...")
    districts = []
    for name, pop, lat, lon in DEMO_DISTRICTS:
        d = District(name=name, population_lakhs=pop, lat=lat, lon=lon)
        db.add(d)
        districts.append((d, lat, lon))
    db.commit()

    for u_badge, u_name, u_role, u_pw in DEMO_USERS:
        db.add(User(badge_number=u_badge, full_name=u_name, role=u_role, hashed_password=hash_password(u_pw)))
    db.commit()

    import random
    random.seed(42)
    now = utcnow()

    # Demo suspects, seeded once, referenced across districts to create
    # realistic shared-location patterns for the link-analysis endpoint.
    suspect_names = [
        "R. Naik", "S. Gowda", "A. Khan", "V. Shetty", "P. Reddy", "M. Iyer",
        "K. Patil", "D. Hegde",
    ]
    suspects = [Suspect(full_name=n, risk_flag=random.random() > 0.75) for n in suspect_names]
    db.add_all(suspects)
    db.commit()

    all_incidents = []
    for idx, (d, lat, lon) in enumerate(districts):
        district_rows = 0
        for _ in range(40):
            occurred = now - timedelta(hours=random.randint(0, 240))
            inc = Incident(
                fir_number=f"FIR{random.randint(10000,99999)}",
                district_id=d.id,
                crime_type=random.choice(CRIME_TYPES),
                lat=lat + random.uniform(-0.15, 0.15),
                lon=lon + random.uniform(-0.15, 0.15),
                occurred_at=occurred,
                modus_operandi=random.choice([
                    "Night-time forced entry", "Distraction theft in crowd",
                    "Phishing call impersonating bank", "Vehicle break-in near transit hub",
                ]),
            )
            db.add(inc)
            all_incidents.append(inc)
            district_rows += 1
        base = 40 + idx * 8
        score = min(97, base + random.randint(-5, 25))
        db.add(RiskScore(district_id=d.id, score=score, baseline=base, is_anomaly=score - base > 15))

        # Seed one ingestion-log entry per district so the Data Ingestion tab
        # shows real sync history from first boot (occasional schema-drift
        # status kept for demo realism, matching the original mock ratio).
        drift = random.random() < 0.18
        db.add(IngestLog(
            district_id=d.id,
            rows_received=district_rows,
            rows_inserted=0 if drift else district_rows,
            rows_skipped=district_rows if drift else 0,
            status="schema_drift" if drift else "synced",
            synced_at=now - timedelta(minutes=random.randint(2, 55)),
        ))
    db.commit()

    # Link 1-3 suspects to a subset of incidents so shared-location queries
    # return real results out of the box (rather than an always-empty demo).
    for inc in random.sample(all_incidents, k=min(80, len(all_incidents))):
        for s in random.sample(suspects, k=random.randint(1, 2)):
            db.add(IncidentSuspect(incident_id=inc.id, suspect_id=s.id,
                                     role=random.choice(["primary", "accomplice", "person_of_interest"])))
    db.commit()

    db.add(Alert(district_id=districts[0][0].id, level="critical",
                  message="Assault reports 3.2x baseline in Whitefield zone"))
    db.add(Alert(district_id=districts[1][0].id, level="warning",
                  message="Cyber fraud cluster detected — 6 linked complaints"))
    db.commit()
    logger.info("Seed complete: %d districts, %d incidents, %d suspects",
                len(districts), len(all_incidents), len(suspects))


@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


# ---------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------
@app.post("/api/v1/auth/login", response_model=Token, tags=["auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db),
          _rl=Depends(rate_limit(10, 60))):
    user = db.query(User).filter(User.badge_number == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect badge number or password")
    token = create_access_token({"sub": user.id, "role": user.role, "full_name": user.full_name})
    return Token(access_token=token, role=user.role, full_name=user.full_name)


# ---------------------------------------------------------------------
# Health check (for load balancers / uptime monitors)
# ---------------------------------------------------------------------
@app.get("/health", response_model=HealthOut, tags=["ops"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(select(func.count()).select_from(District))
        db_status = "ok"
    except Exception:
        db_status = "unreachable"
    return HealthOut(status="ok", db=db_status, time=datetime.now(timezone.utc))


# ---------------------------------------------------------------------
# Geospatial hotspot endpoints
# ---------------------------------------------------------------------
@app.get("/api/v1/incidents", response_model=PaginatedIncidents, tags=["geospatial"])
def list_incidents(
    district: Optional[str] = None,
    since_hours: int = Query(24, ge=1, le=24 * 30),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_permission("view")),
):
    q = db.query(Incident).join(District)
    cutoff = utcnow() - timedelta(hours=since_hours)
    q = q.filter(Incident.occurred_at >= cutoff)
    if district:
        q = q.filter(District.name == district)
    total = q.count()
    items = q.order_by(Incident.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedIncidents(total=total, page=page, page_size=page_size, items=items)


@app.get("/api/v1/incidents/hotspots", tags=["geospatial"])
def hotspot_density(hour: Optional[int] = Query(None, ge=0, le=23), db: Session = Depends(get_db),
                     user: TokenPayload = Depends(require_permission("view"))):
    """Incident count per district, optionally bucketed to a single hour-of-day (for the time-slider heatmap)."""
    rows = db.query(District.name, func.count(Incident.id)).join(Incident, isouter=True)
    if hour is not None:
        rows = rows.filter(func.extract("hour", Incident.occurred_at) == hour)
    rows = rows.group_by(District.name).all()
    return [{"district": name, "count": count} for name, count in rows]


@app.get("/api/v1/incidents/hotspots/matrix", tags=["geospatial"])
def hotspot_matrix(
    since_hours: int = Query(24 * 10, ge=24, le=24 * 60),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_permission("view")),
):
    """
    Returns per-district incident counts bucketed by hour-of-day (0-23) in a
    single response, so the frontend's 24H time-slider/animation can index
    into a local array instead of issuing a request per hour tick.
    """
    cutoff = utcnow() - timedelta(hours=since_hours)
    rows = (
        db.query(District.id, District.name, func.extract("hour", Incident.occurred_at), func.count(Incident.id))
        .join(Incident, Incident.district_id == District.id)
        .filter(Incident.occurred_at >= cutoff)
        .group_by(District.id, District.name, func.extract("hour", Incident.occurred_at))
        .all()
    )
    by_district: dict[int, dict] = {}
    for did, name, hour, count in rows:
        entry = by_district.setdefault(did, {"district_id": did, "district": name, "hours": [0] * 24})
        entry["hours"][int(hour)] = count
    # include districts with zero incidents too, so the map never drops a marker
    all_districts = db.query(District).all()
    for d in all_districts:
        by_district.setdefault(d.id, {"district_id": d.id, "district": d.name, "hours": [0] * 24})
    return list(by_district.values())


# ---------------------------------------------------------------------
# Predictive risk endpoints
# ---------------------------------------------------------------------
@app.get("/api/v1/risk/districts", response_model=list[RiskScoreOut], tags=["predictive"])
def get_risk_scores(db: Session = Depends(get_db), user: TokenPayload = Depends(require_permission("view"))):
    rows = db.query(RiskScore).join(District).order_by(RiskScore.computed_at.desc()).all()
    return [
        RiskScoreOut(district=r.district.name, score=r.score, baseline=r.baseline,
                      is_anomaly=r.is_anomaly, computed_at=r.computed_at)
        for r in rows
    ]


@app.get("/api/v1/incidents/trend", tags=["predictive"])
def incidents_trend(
    hours: int = Query(24, ge=1, le=24 * 7),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_permission("view")),
):
    """
    24 hour-of-day buckets: `actual` is the incident count in that bucket
    within the trailing `hours` window; `baseline` is the historical average
    count for that same hour-of-day across all seeded/ingested history, so
    spikes are visible against a real (not fabricated) baseline.
    """
    cutoff = utcnow() - timedelta(hours=hours)
    actual_rows = (
        db.query(func.extract("hour", Incident.occurred_at), func.count(Incident.id))
        .filter(Incident.occurred_at >= cutoff)
        .group_by(func.extract("hour", Incident.occurred_at))
        .all()
    )
    actual_map = {int(h): c for h, c in actual_rows}

    baseline_rows = (
        db.query(func.extract("hour", Incident.occurred_at), func.count(Incident.id))
        .group_by(func.extract("hour", Incident.occurred_at))
        .all()
    )
    baseline_totals = {int(h): c for h, c in baseline_rows}

    oldest = db.query(func.min(Incident.occurred_at)).scalar()
    newest = db.query(func.max(Incident.occurred_at)).scalar()
    span_days = max(1.0, (newest - oldest).total_seconds() / 86400) if oldest and newest else 1.0

    return [
        {
            "hour": f"{h:02d}:00",
            "actual": actual_map.get(h, 0),
            "baseline": round(baseline_totals.get(h, 0) / span_days, 1),
        }
        for h in range(24)
    ]


def compute_risk_scores_job():
    """
    Real anomaly-detection job — swap the naive z-score below for
    sklearn.ensemble.IsolationForest once enough history has accumulated.
    Intended to run on a schedule (APScheduler, Celery beat, or a cron
    hitting POST /api/v1/risk/recompute).
    """
    db = SessionLocal()
    try:
        districts = db.query(District).all()
        for d in districts:
            counts = db.query(func.count(Incident.id)).filter(Incident.district_id == d.id).scalar() or 0
            baseline = max(5, counts * 0.7)
            score = min(100, max(0, (counts / max(baseline, 1)) * 45))
            db.add(RiskScore(district_id=d.id, score=score, baseline=baseline, is_anomaly=score > 75))
        db.commit()
    finally:
        db.close()


@app.post("/api/v1/risk/recompute", tags=["predictive"])
def recompute_risk(user: TokenPayload = Depends(require_permission("annotate"))):
    compute_risk_scores_job()
    return {"status": "recomputed"}


# ---------------------------------------------------------------------
# Alerts (RBAC-gated acknowledgement)
# ---------------------------------------------------------------------
@app.get("/api/v1/alerts", response_model=list[AlertOut], tags=["alerts"])
def list_alerts(db: Session = Depends(get_db), user: TokenPayload = Depends(require_permission("view"))):
    rows = db.query(Alert).join(District).order_by(Alert.created_at.desc()).all()
    return [
        AlertOut(id=a.id, district=a.district.name, level=a.level, message=a.message,
                  created_at=a.created_at, acknowledged=a.acknowledged_at is not None)
        for a in rows
    ]


@app.post("/api/v1/alerts/{alert_id}/ack", response_model=AlertOut, tags=["alerts"])
def ack_alert(alert_id: str, db: Session = Depends(get_db),
              user: TokenPayload = Depends(require_permission("dismiss"))):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged_by = user.sub
    alert.acknowledged_at = utcnow()
    db.commit()
    db.refresh(alert)
    return AlertOut(id=alert.id, district=alert.district.name, level=alert.level, message=alert.message,
                      created_at=alert.created_at, acknowledged=True)


# ---------------------------------------------------------------------
# Link analysis — proxied to Neo4j in production (see neo4j_graph.cypher).
# This demo endpoint returns a shaped response so the frontend contract
# is stable before Neo4j is wired in.
# ---------------------------------------------------------------------
@app.get("/api/v1/suspects", tags=["link-analysis"])
def list_suspects(db: Session = Depends(get_db), user: TokenPayload = Depends(require_permission("view"))):
    rows = db.query(Suspect).all()
    return [{"id": s.id, "full_name": s.full_name, "risk_flag": s.risk_flag} for s in rows]


@app.get("/api/v1/graph/neighbors/{suspect_name}", tags=["link-analysis"])
def graph_neighbors(suspect_name: str, within_days: int = 30, db: Session = Depends(get_db),
                     user: TokenPayload = Depends(require_permission("view"))):
    """
    Working demo implementation: finds suspects who share a district/incident
    with the named suspect within the lookback window, using plain SQL joins
    against IncidentSuspect. This is the *fallback* path — at Neo4j-scale
    with deep multi-hop traversal, the production path is the Cypher query
    in neo4j_graph.cypher:

        MATCH (target:Suspect {full_name: $name})-[:INVOLVED_IN]->(:Incident)-[:OCCURRED_AT]->(loc)
        MATCH (other:Suspect)-[:INVOLVED_IN]->(i2:Incident)-[:OCCURRED_AT]->(loc)
        WHERE other.full_name <> $name AND i2.occurred_at >= datetime() - duration({days: $within_days})
        RETURN DISTINCT other.full_name, loc.name, i2.occurred_at

    Swap this function's body for a neo4j.GraphDatabase driver session.run()
    call once Neo4j is wired in — the response shape below is already the
    contract the frontend expects, so nothing else needs to change.
    """
    target = db.query(Suspect).filter(Suspect.full_name == suspect_name).first()
    if not target:
        raise HTTPException(status_code=404, detail=f"Suspect '{suspect_name}' not found")

    cutoff = utcnow() - timedelta(days=within_days)
    target_incident_ids = [
        row.incident_id for row in
        db.query(IncidentSuspect).filter(IncidentSuspect.suspect_id == target.id).all()
    ]
    if not target_incident_ids:
        return {"suspect": suspect_name, "neighbors": []}

    target_districts = {
        i.district_id for i in db.query(Incident).filter(Incident.id.in_(target_incident_ids)).all()
    }

    neighbors = (
        db.query(Suspect, Incident)
        .join(IncidentSuspect, IncidentSuspect.suspect_id == Suspect.id)
        .join(Incident, Incident.id == IncidentSuspect.incident_id)
        .filter(Incident.district_id.in_(target_districts))
        .filter(Suspect.id != target.id)
        .filter(Incident.occurred_at >= cutoff)
        .all()
    )
    seen = {}
    for suspect, incident in neighbors:
        entry = seen.setdefault(suspect.id, {
            "full_name": suspect.full_name, "risk_flag": suspect.risk_flag,
            "shared_district": incident.district.name, "shared_incidents": 0,
        })
        entry["shared_incidents"] += 1

    return {"suspect": suspect_name, "within_days": within_days, "neighbors": list(seen.values())}


@app.get("/api/v1/graph/full", tags=["link-analysis"])
def graph_full(db: Session = Depends(get_db), user: TokenPayload = Depends(require_permission("view"))):
    """
    Full suspect/location graph for the Link Analysis force-graph view:
    suspect->location edges (weighted by shared incident count) and
    suspect<->suspect association edges (weighted by co-occurrence on the
    same incident). SQL-joins today; swap for a Neo4j Cypher traversal
    (see neo4j_graph.cypher) once the graph DB is wired in — the response
    shape is already the contract the frontend expects.
    """
    suspects = db.query(Suspect).all()
    nodes = [
        {"id": f"S-{s.id}", "label": s.full_name, "type": "suspect",
         "group": abs(hash(s.id)) % 3, "risk_flag": s.risk_flag}
        for s in suspects
    ]

    location_rows = (
        db.query(Suspect.id, District.id, District.name, func.count(IncidentSuspect.incident_id))
        .join(IncidentSuspect, IncidentSuspect.suspect_id == Suspect.id)
        .join(Incident, Incident.id == IncidentSuspect.incident_id)
        .join(District, District.id == Incident.district_id)
        .group_by(Suspect.id, District.id, District.name)
        .all()
    )
    links = []
    used_district_ids = set()
    for suspect_id, district_id, district_name, weight in location_rows:
        used_district_ids.add(district_id)
        links.append({"source": f"S-{suspect_id}", "target": f"L-{district_id}", "weight": int(weight)})

    for d in db.query(District).filter(District.id.in_(used_district_ids)).all():
        nodes.append({"id": f"L-{d.id}", "label": d.name, "type": "location", "group": d.id % 3})

    # Suspect<->suspect association: co-occurrence on the same incident.
    incident_suspects = db.query(IncidentSuspect.incident_id, IncidentSuspect.suspect_id).all()
    by_incident: dict[str, list[str]] = {}
    for inc_id, suspect_id in incident_suspects:
        by_incident.setdefault(inc_id, []).append(suspect_id)
    assoc_weight: dict[tuple, int] = {}
    for suspect_ids in by_incident.values():
        uniq = sorted(set(suspect_ids))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                key = (uniq[i], uniq[j])
                assoc_weight[key] = assoc_weight.get(key, 0) + 1
    for (a, b), weight in assoc_weight.items():
        links.append({"source": f"S-{a}", "target": f"S-{b}", "weight": weight, "assoc": True})

    return {"nodes": nodes, "links": links}


# ---------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------
@app.get("/api/v1/districts", tags=["reference"])
def list_districts(db: Session = Depends(get_db), user: TokenPayload = Depends(require_permission("view"))):
    rows = db.query(District).all()
    return [
        {"id": d.id, "name": d.name, "population_lakhs": d.population_lakhs, "lat": d.lat, "lon": d.lon}
        for d in rows
    ]


@app.get("/api/v1/auth/me", tags=["auth"])
def whoami(user: TokenPayload = Depends(get_current_user)):
    return {"user_id": user.sub, "role": user.role, "full_name": user.full_name,
             "permissions": sorted(ROLE_PERMS.get(user.role, set()))}


# ---------------------------------------------------------------------
# Ingestion endpoint — Pandas-based in production, stdlib csv here to
# keep the demo dependency-free. Cleans a dropped CSV, dedupes on FIR
# number, and upserts into the incidents table.
# ---------------------------------------------------------------------
class IngestResult(BaseModel):
    rows_received: int
    rows_inserted: int
    rows_skipped_duplicate: int
    errors: list[str]


@app.post("/api/v1/ingest/csv", response_model=IngestResult, tags=["ingestion"])
def ingest_csv(rows: list[dict], db: Session = Depends(get_db),
               user: TokenPayload = Depends(require_permission("assign"))):
    """
    Accepts pre-parsed CSV rows (as the frontend would send after reading a
    district's file client-side, or as a staging script would after a
    Pandas cleaning pass). Each row is expected to have:
    fir_number, district, crime_type, lat, lon, occurred_at, modus_operandi.

    Production version replaces this with the full Pandas pipeline
    described in DEPLOYMENT.md: column normalization, geocoding of missing
    coordinates, crime-type taxonomy mapping, then the same upsert logic.
    """
    import csv as _csv  # noqa: F401  (kept for parity with the production import path)

    inserted, skipped, errors = 0, 0, []
    per_district_counts: dict[str, dict[str, int]] = {}

    def touch_district(name: str, key: str):
        stats = per_district_counts.setdefault(name, {"received": 0, "inserted": 0, "skipped": 0, "errors": 0})
        stats[key] += 1

    for i, row in enumerate(rows):
        district_name = row.get("district", "")
        touch_district(district_name, "received")
        try:
            fir = row.get("fir_number")
            if fir and db.query(Incident).filter(Incident.fir_number == fir).first():
                skipped += 1
                touch_district(district_name, "skipped")
                continue
            district = db.query(District).filter(District.name == row["district"]).first()
            if not district:
                errors.append(f"Row {i}: unknown district '{row.get('district')}'")
                touch_district(district_name, "errors")
                continue
            db.add(Incident(
                fir_number=fir or f"FIR{uuid.uuid4().hex[:8].upper()}",
                district_id=district.id,
                crime_type=row.get("crime_type", "Unclassified"),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                occurred_at=datetime.fromisoformat(row["occurred_at"]).replace(tzinfo=None),
                modus_operandi=row.get("modus_operandi"),
            ))
            inserted += 1
            touch_district(district_name, "inserted")
        except (KeyError, ValueError) as e:
            errors.append(f"Row {i}: {e}")
            touch_district(district_name, "errors")
    db.commit()

    # One IngestLog entry per district touched by this upload, so
    # GET /api/v1/ingest/status reflects the real outcome of this run.
    now = utcnow()
    for name, stats in per_district_counts.items():
        district = db.query(District).filter(District.name == name).first()
        if not district:
            continue
        db.add(IngestLog(
            district_id=district.id,
            rows_received=stats["received"],
            rows_inserted=stats["inserted"],
            rows_skipped=stats["skipped"] + stats["errors"],
            status="schema_drift" if stats["errors"] > 0 else "synced",
            synced_at=now,
        ))
    db.commit()

    return IngestResult(rows_received=len(rows), rows_inserted=inserted,
                         rows_skipped_duplicate=skipped, errors=errors)


@app.get("/api/v1/ingest/status", tags=["ingestion"])
def ingest_status(db: Session = Depends(get_db), user: TokenPayload = Depends(require_permission("view"))):
    """Latest ingestion-log entry per district, for the Data Ingestion tab."""
    districts = db.query(District).all()
    result = []
    for d in districts:
        latest = (
            db.query(IngestLog)
            .filter(IngestLog.district_id == d.id)
            .order_by(IngestLog.synced_at.desc())
            .first()
        )
        if latest:
            minutes_ago = max(0, int((utcnow() - latest.synced_at).total_seconds() // 60))
            result.append({
                "district": d.name,
                "status": "SYNCED" if latest.status == "synced" else "SCHEMA DRIFT",
                "minutes_ago": minutes_ago,
                "rows": latest.rows_inserted,
            })
        else:
            result.append({"district": d.name, "status": "NO DATA", "minutes_ago": None, "rows": 0})
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
