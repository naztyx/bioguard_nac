from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import init_db, close_db
from app.logger import setup_logging, get_logger
from app.middleware.logging import RequestLoggingMiddleware
from app.routers import identity, drugs, emergency, agent

settings = get_settings()
setup_logging(log_level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger   = get_logger("main")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("BioGuard API starting up", extra={
        "env":      settings.APP_ENV,
        "simulate": settings.NAC_SIMULATE,
    })
    await init_db()
    yield
    logger.info("BioGuard API shutting down")
    await close_db()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "BioGuard API",
    description = (
        "Unified Healthcare Trust Infrastructure for Sub-Saharan Africa.\n\n"
        "Verifies drug authenticity, healthcare worker identity, and coordinates "
        "emergency response using Nokia CAMARA network APIs across 4G/5G networks."
    ),
    version     = "2.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

# ── Middleware (order matters — outermost first) ───────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)
app.add_middleware(RequestLoggingMiddleware)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", extra={
        "path":   request.url.path,
        "method": request.method,
    }, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. It has been logged."},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(identity.router)
app.include_router(drugs.router)
app.include_router(emergency.router)
app.include_router(agent.router)


# ── Root & Health ─────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {
        "service":  "BioGuard API",
        "version":  "2.0.0",
        "status":   "running",
        "db":       "async (asyncpg)",
        "simulate": settings.NAC_SIMULATE,
        "modules": {
            "identity_trust": "/identity",
            "drug_safety":    "/drugs",
            "emergency":      "/emergency",
        },
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
