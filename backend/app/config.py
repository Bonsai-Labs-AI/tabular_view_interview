from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    tavily_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./arbitrator.db"

    model_config = {"env_file": ".env"}


settings = Settings()
