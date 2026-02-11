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

# Create async engine with connection pool settings.
# SQLite uses NullPool and does not accept pool sizing kwargs.
engine_kwargs = {"echo": settings.debug}
if is_postgres:
    engine_kwargs.update(
        {
            "pool_size": 10,  # Number of connections to keep open
            "max_overflow": 20,  # Allow up to 20 additional connections under load
            "pool_timeout": 30,  # Wait up to 30s for a connection
            "pool_recycle": 1800,  # Recycle connections after 30 minutes
        }
    )

engine = create_async_engine(database_url, **engine_kwargs)

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
        # Add saved_run_id to research_tasks for linking to saved runs
        ("research_tasks", "saved_run_id", "INTEGER"),
        # Add research options to saved_email_runs for re-research to remember settings
        ("saved_email_runs", "include_district_research", "BOOLEAN DEFAULT FALSE NOT NULL"),
        ("saved_email_runs", "include_conference_research", "BOOLEAN DEFAULT FALSE NOT NULL"),
        # Add purpose_prompt to golden_emails for training context
        ("golden_emails", "purpose_prompt", "TEXT"),
        # Add purpose_prompt to saved_email_runs for persistence
        ("saved_email_runs", "purpose_prompt", "TEXT"),
        # Add selected_cached_hook_ids to saved_email_runs for persistence
        ("saved_email_runs", "selected_cached_hook_ids", "JSON"),
        # Link edited runs to their auto-saved parent
        ("saved_email_runs", "parent_run_id", "INTEGER"),
        # Add evidence_chunks_used to email_improvement_reviews for tracking which chunks were used
        ("email_improvement_reviews", "evidence_chunks_used", "JSON"),
        # Add hook_types_used to golden_emails for flywheel context matching
        ("golden_emails", "hook_types_used", "JSON"),
        # Add hook_types_used to negative_email_examples for flywheel context matching
        ("negative_email_examples", "hook_types_used", "JSON"),
        # Add purpose_prompt to negative_email_examples for flywheel context matching
        ("negative_email_examples", "purpose_prompt", "TEXT"),
    ]
    
    async with engine.begin() as conn:
        # Table migration: hook_outcome_events
        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS hook_outcome_events (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                    product VARCHAR(200) NOT NULL,
                    product_key VARCHAR(100),
                    state_code VARCHAR(2) NOT NULL,
                    audience VARCHAR(200),
                    hook_link VARCHAR(800) NOT NULL,
                    hook_type VARCHAR(50),
                    outcome VARCHAR(30) NOT NULL,
                    note TEXT
                )
            """))
            logger.info("Migration: ensured table hook_outcome_events exists")
        except Exception as e:
            logger.warning(f"Migration failed for hook_outcome_events table: {e}")

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
