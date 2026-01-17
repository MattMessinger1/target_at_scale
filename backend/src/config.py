"""Application configuration."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Keys
    openai_api_key: str = ""
    # OpenAI model for parsing + email generation (override via OPENAI_MODEL)
    openai_model: str = "gpt-5.2"
    # Pro model for email generation with extended reasoning (uses Responses API)
    openai_pro_model: str = "gpt-5.2-pro"
    # Email generation: False = Chat Completions (cheap), True = Responses API (expensive)
    # Default to True since gpt-5.2-pro requires Responses API
    use_email_reasoning: bool = True
    firecrawl_api_key: str = ""
    perplexity_api_key: str = ""
    admin_token: str = ""

    # Outreach CTA
    calendly_url: str = "calendly.com/wceps"
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./wceps.db"
    
    # Environment
    environment: str = "development"
    # Defaults to false; enable only by setting DEBUG=1/true in env.
    debug: bool = False
    
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
