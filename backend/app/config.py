from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    tavily_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./arbitrator.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    rag_index_dir: str = "/data/rag_index"

    model_config = {"env_file": ".env"}


settings = Settings()
