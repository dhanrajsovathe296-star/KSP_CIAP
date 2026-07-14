-- =====================================================================
-- KSP CIAP — PostgreSQL + PostGIS schema
-- Core spatial/relational store. Neo4j (separate) handles the
-- suspect/location/MO graph for link analysis.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- for gen_random_uuid()

-- ---------------------------------------------------------------------
-- Reference / org structure
-- ---------------------------------------------------------------------
CREATE TABLE districts (
    district_id     SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    state           TEXT NOT NULL DEFAULT 'Karnataka',
    population      NUMERIC,
    boundary        GEOMETRY(MULTIPOLYGON, 4326)
);

CREATE TABLE police_stations (
    station_id      SERIAL PRIMARY KEY,
    district_id     INTEGER REFERENCES districts(district_id),
    name            TEXT NOT NULL,
    location        GEOMETRY(POINT, 4326) NOT NULL
);

CREATE TYPE user_role AS ENUM ('officer', 'analyst', 'admin');

CREATE TABLE users (
    user_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    badge_number    TEXT UNIQUE,
    full_name       TEXT NOT NULL,
    role            user_role NOT NULL DEFAULT 'officer',
    station_id      INTEGER REFERENCES police_stations(station_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Core entities
-- ---------------------------------------------------------------------
CREATE TABLE crime_types (
    crime_type_id   SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,     -- Theft, Assault, Cyber Fraud...
    category        TEXT                       -- violent / property / cyber / narcotics
);

CREATE TABLE suspects (
    suspect_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       TEXT,
    aliases         TEXT[],
    dob             DATE,
    last_known_loc  GEOMETRY(POINT, 4326),
    risk_flag       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE incidents (
    incident_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fir_number      TEXT UNIQUE,
    district_id     INTEGER REFERENCES districts(district_id),
    station_id      INTEGER REFERENCES police_stations(station_id),
    crime_type_id   INTEGER REFERENCES crime_types(crime_type_id),
    location        GEOMETRY(POINT, 4326) NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL,
    reported_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    modus_operandi  TEXT,
    description     TEXT,
    source_file     TEXT,           -- traceability back to ingested CSV/Excel
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE incident_suspects (
    incident_id     UUID REFERENCES incidents(incident_id) ON DELETE CASCADE,
    suspect_id      UUID REFERENCES suspects(suspect_id) ON DELETE CASCADE,
    role            TEXT,            -- primary, accomplice, person_of_interest
    PRIMARY KEY (incident_id, suspect_id)
);

-- ---------------------------------------------------------------------
-- Predictive layer output (written by the FastAPI/AI service on a cron)
-- ---------------------------------------------------------------------
CREATE TABLE risk_scores (
    id              BIGSERIAL PRIMARY KEY,
    district_id     INTEGER REFERENCES districts(district_id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    score           NUMERIC NOT NULL CHECK (score >= 0 AND score <= 100),
    baseline        NUMERIC,
    is_anomaly      BOOLEAN DEFAULT FALSE,
    model_version   TEXT
);

CREATE TABLE alerts (
    alert_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    district_id     INTEGER REFERENCES districts(district_id),
    level           TEXT CHECK (level IN ('info','warning','critical')),
    message         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_by UUID REFERENCES users(user_id),
    acknowledged_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- Spatial + time indexes (hotspot queries filter heavily on both)
-- ---------------------------------------------------------------------
CREATE INDEX idx_incidents_geom       ON incidents USING GIST (location);
CREATE INDEX idx_incidents_occurred   ON incidents (occurred_at);
CREATE INDEX idx_incidents_district   ON incidents (district_id);
CREATE INDEX idx_stations_geom        ON police_stations USING GIST (location);
CREATE INDEX idx_suspects_geom        ON suspects USING GIST (last_known_loc);

-- Example hotspot query: incidents in the last 24h within a district, for the heatmap
-- SELECT ST_AsGeoJSON(location), crime_type_id, occurred_at
-- FROM incidents
-- WHERE district_id = $1 AND occurred_at > now() - interval '24 hours';
