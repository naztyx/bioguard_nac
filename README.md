# BioGuard API v2.0

**Unified Healthcare Trust Infrastructure — FastAPI + Async PostgreSQL**

---

## What Changed in v2 (Async Upgrade)

| Area | Before (v1) | After (v2) |
|---|---|---|
| DB driver | `psycopg2` (sync) | `asyncpg` (fully async) |
| DB engine | `create_engine` | `create_async_engine` |
| Sessions | `SessionLocal()` | `AsyncSession` via `async_sessionmaker` |
| All DB queries | `db.query(Model)` | `await db.execute(select(Model))` |
| CAMARA calls | sync functions | `async def` with `await` |
| Parallel CAMARA | sequential | `asyncio.gather()` — concurrent |
| Logging | `print()` | Structured JSON + coloured console |
| App startup | `@app.on_event` | `asynccontextmanager lifespan` |
| Error handling | none | global exception handler + middleware |

---

## Quick Start

```bash
# 1. Extract and install
tar -xzf bioguard_final.tar.gz && cd bioguard
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit DATABASE_URL with your asyncpg connection string:
# postgresql+asyncpg://user:password@localhost:5432/bioguard_db

# 3. Create Postgres database
createdb bioguard_db

# 4. Run
uvicorn app.main:app --reload --port 8000

# 5. Seed demo data
python seed_demo.py
```

API docs → http://localhost:8000/docs

---

## Project Structure

```
bioguard/
├── app/
│   ├── main.py                  # FastAPI app + lifespan + global error handler
│   ├── config.py                # Pydantic settings (.env loader)
│   ├── database.py              # Async engine, AsyncSession, init_db/close_db
│   ├── models.py                # SQLAlchemy ORM models (8 tables)
│   ├── schemas.py               # Pydantic v2 request/response schemas
│   ├── logger.py                # Structured logging (JSON file + coloured console)
│   ├── middleware/
│   │   └── logging.py           # HTTP request/response logging middleware
│   ├── routers/
│   │   ├── ussd.py              # Africa's Talking webhook + /ussd/test
│   │   ├── identity.py          # Identity Trust Module
│   │   ├── drugs.py             # Drug Safety Module
│   │   └── emergency.py        # Emergency Response Module (route-order safe)
│   └── services/
│       ├── camara.py            # Nokia NAC CAMARA layer (async, real + simulated)
│       ├── trust.py             # Dynamic trust score engine (async)
│       └── ussd_flow.py         # USSD state machine (fully async)
├── seed_demo.py                 # Async demo data seed (20 workers, 20 patients, 13 drugs...)
├── logs/                        # Log output directory (auto-created)
├── requirements.txt
├── alembic.ini
└── .env
```

---

## Logging

Every component logs at the right level with structured context.

**Console output (coloured):**
```
[INFO    ] 14:32:01 | bioguard.routers.emergency | Emergency dispatched
[WARNING ] 14:32:01 | bioguard.camara            | SIM swap detected (simulated)
[ERROR   ] 14:32:05 | bioguard.database          | DB session rolled back
```

**File output (JSON, `logs/bioguard.log`):**
```json
{"timestamp":"2025-01-01T14:32:01Z","level":"WARNING","logger":"bioguard.routers.emergency",
 "message":"Emergency dispatched","emergency_id":42,"phone":"1001","type":"ambulance",
 "assigned":"LUTH Lagos","distance_km":2.1,"qos_session":"QOS-001001-143201"}
```

**What is logged:**
| Module | What | Level |
|---|---|---|
| HTTP middleware | Every request — method, path, status, ms | INFO/WARNING |
| CAMARA | SIM swaps, device inactive, geofence fails | WARNING |
| Trust engine | Score changes, fraud signals | WARNING/INFO |
| Drug verify | Counterfeit/recalled/expired catches | WARNING |
| Emergency | Every dispatch with full metadata | WARNING |
| USSD | Every session in + out | INFO |
| Database | Rollbacks and errors | ERROR |

## CAMARA Simulation Rules (last digit of phone)

| Digit | Effect |
|---|---|
| `9` | SIM swap detected (2 days ago) → trust **−40** |
| `0` | Number verification fails → trust **−20** |
| `8` | Device inactive → trust **−15** |
| `7` | Geofence / location check fails → trust **−25** |
| other | All checks pass ✅ |

---

## Trust Score Reference

| Score | Level | Action |
|---|---|---|
| 90–100 | HIGH | Allow — proceed normally |
| 70–89 | MEDIUM | Allow — logged for review |
| 40–69 | LOW | Flag — require secondary confirmation |
| 0–39 | CRITICAL | Block — escalate immediately |

---

## Demo Scenarios

| Scenario | Input |
|---|---|
| ✅ Authentic drug | `ACT-MALARIA-001` |
| ⚠️ Expired drug | `EXP-AMOX-001` |
| 🚫 Recalled/counterfeit | `FAKE-PARA-001` |
| ❄️ Cold-chain vaccine | `CC-HEPB-001` |
| ✅ Trusted doctor | Worker ID `HW-001` |
| 🚨 SIM swap fraud | Worker ID `HW-006` (trust: 38) |
| 🚨 Live emergencies | `GET /emergency?status_filter=pending` |
