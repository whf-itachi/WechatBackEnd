from urllib.parse import quote_plus

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_ASYNC_URL: str = f"mysql+aiomysql://root:{quote_plus('agent@123')}@localhost/ics_db?charset=utf8mb4"  # 异步驱动
    POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 50

    class Config:
        env_file = ".env"

settings = Settings()