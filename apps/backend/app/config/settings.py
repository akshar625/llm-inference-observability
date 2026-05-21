from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    LLAMA_API_KEY: str = ""

    POSTGRES_URL: str = ""

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    REDIS_URL: str = "redis://localhost:6379"

    MAX_INPUT_TOKENS: int = 8000
    MAX_ESTIMATED_COST: float = 2.0

    class Config:
        env_file = ".env"


settings = Settings()
