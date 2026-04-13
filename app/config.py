from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL:         str
    SUPABASE_ANON_KEY:    str
    SUPABASE_SERVICE_KEY: str
    DATABASE_URL:         str = ""

    # AI Provider
    LLM_PROVIDER: str = "groq"
    LLM_MODEL_ID: str = "llama-3.3-70b-versatile"

    # Groq (free, fast — primary)
    GROQ_API_KEY: str = ""

    # HuggingFace (fallback)
    HUGGINGFACE_API_TOKEN: str = ""

    # Email
    RESEND_API_KEY: str = ""
    EMAIL_FROM:     str = "alerts@bbkb.app"

    # App
    APP_ENV:                    str = "development"
    SECRET_KEY:                 str = "change-me"
    ALLOWED_ORIGINS:            str = "http://localhost:3000"
    MAX_DAILY_AI_QUERIES_FREE:  int = 5
    MAX_DAILY_AI_QUERIES_PRO:   int = 50

    class Config:
        env_file     = ".env"
        env_file_encoding = "utf-8"
        extra        = "ignore"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()