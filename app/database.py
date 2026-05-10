from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings
from app.logger import get_logger

logger   = get_logger("database")
settings = get_settings()


class Base(DeclarativeBase):
    pass


# ── Engine ────────────────────────────────────────────────────────────────────
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,           # set True to log every SQL statement (dev only)
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # verify connection health before use
    pool_recycle=1800,    # recycle connections every 30 min
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keep objects usable after commit
    autocommit=False,
    autoflush=False,
)


# ── Dependency ────────────────────────────────────────────────────────────────
async def get_db() -> AsyncSession:
    """
    FastAPI dependency — yields an async DB session.
    Rolls back automatically on exception, always closes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            logger.error("DB session rolled back due to exception", exc_info=exc)
            raise
        finally:
            await session.close()


# ── Startup / Shutdown ────────────────────────────────────────────────────────
async def init_db() -> None:
    """Create all tables on startup (development convenience)."""
    from app import models   # noqa: F401 — ensures models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified / created")


async def close_db() -> None:
    """Dispose engine connection pool on shutdown."""
    await engine.dispose()
    logger.info("Database connection pool closed")
