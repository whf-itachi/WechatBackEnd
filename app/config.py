from pydantic_settings import BaseSettings
from pathlib import Path


# 获取项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    # 数据库配置
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    
    # 数据库连接池配置
    POOL_SIZE: int = 5
    MAX_OVERFLOW: int = 10
    
    @property
    def DB_ASYNC_URL(self) -> str:
        """获取异步数据库URL"""
        # 确保密码中的特殊字符被正确编码
        encoded_password = self.DB_PASSWORD.replace('@', '%40')
        return f"mysql+aiomysql://{self.DB_USER}:{encoded_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # JWT配置
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = True
        
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 打印配置信息（注意：生产环境中应该移除这些打印语句）
        print(f"Loading settings from: {self.Config.env_file}")
        print(f"Database URL: {self.DB_ASYNC_URL}")
        print(f"Database Host: {self.DB_HOST}")
        print(f"Database Port: {self.DB_PORT}")
        print(f"Database Name: {self.DB_NAME}")
        print(f"Database User: {self.DB_USER}")
        print(f"JWT Secret Key: {self.JWT_SECRET_KEY}")
        print(f"JWT Algorithm: {self.JWT_ALGORITHM}")
        print(f"JWT Access Token Expire Minutes: {self.JWT_ACCESS_TOKEN_EXPIRE_MINUTES}")

settings = Settings()