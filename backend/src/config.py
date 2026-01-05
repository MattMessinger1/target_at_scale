"""Application configuration."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Keys
    openai_api_key: str = ""
    firecrawl_api_key: str = ""
    perplexity_api_key: str = ""
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./wceps.db"
    
    # Environment
    environment: str = "development"
    debug: bool = True
    
    # Paths
    knowledge_base_path: str = "../data/knowledge-base-export-2026-01-05.json"
    pilot_districts_path: str = "../data/pilot_districts.json"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
