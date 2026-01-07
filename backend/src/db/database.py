"""Database connection and session management."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from ..config import get_settings

settings = get_settings()

database_url = settings.database_url

# Ensure we use async drivers for supported DBs
# - SQLite: sqlite+aiosqlite://
# - Postgres: postgresql+asyncpg://
if database_url.startswith("sqlite://") and "+aiosqlite" not in database_url:
    database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
elif database_url.startswith("postgres://"):
    # Heroku/Railway sometimes use postgres://; SQLAlchemy expects postgresql://
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql+psycopg2://"):
    database_url = database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

# Create async engine
engine = create_async_engine(
    database_url,
    echo=settings.debug,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
