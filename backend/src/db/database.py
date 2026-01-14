"""Database connection and session management."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from ..config import get_settings

logger = logging.getLogger(__name__)
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

# Detect if we're using PostgreSQL
is_postgres = "postgresql" in database_url or "postgres" in database_url

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


async def run_migrations():
    """Run schema migrations to add missing columns.
    
    This is a simple migration system for adding new columns to existing tables.
    It's idempotent - safe to run multiple times.
    """
    if not is_postgres:
        # SQLite doesn't support ADD COLUMN IF NOT EXISTS well, skip
        logger.info("Skipping migrations for non-PostgreSQL database")
        return
    
    migrations = [
        # Add created_by to research_tasks
        ("research_tasks", "created_by", "VARCHAR(100)"),
        # Add conferences_json to research_tasks  
        ("research_tasks", "conferences_json", "JSON"),
        # Add created_by to saved_email_runs
        ("saved_email_runs", "created_by", "VARCHAR(100)"),
        # Add include_conference_research to research_tasks
        ("research_tasks", "include_conference_research", "BOOLEAN DEFAULT FALSE"),
        # Add include_district_research and include_conference_research to batch_jobs
        ("batch_jobs", "include_district_research", "BOOLEAN DEFAULT FALSE"),
        ("batch_jobs", "include_conference_research", "BOOLEAN DEFAULT FALSE"),
        # Add is_archived to cache tables for archiving old research
        ("deep_research_cache", "is_archived", "BOOLEAN DEFAULT FALSE NOT NULL"),
        ("district_research_cache", "is_archived", "BOOLEAN DEFAULT FALSE NOT NULL"),
    ]
    
    async with engine.begin() as conn:
        for table, column, col_type in migrations:
            try:
                # Check if column exists
                check_sql = text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table AND column_name = :column
                """)
                result = await conn.execute(check_sql, {"table": table, "column": column})
                exists = result.fetchone() is not None
                
                if not exists:
                    # Add the column
                    alter_sql = text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
                    await conn.execute(alter_sql)
                    logger.info(f"Migration: Added column {column} to {table}")
                else:
                    logger.debug(f"Migration: Column {column} already exists in {table}")
            except Exception as e:
                logger.warning(f"Migration failed for {table}.{column}: {e}")
                # Continue with other migrations


async def get_db():
    """Get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
