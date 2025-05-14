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

    # 阿里百炼秘钥
    ALI_ACCESS_KEY_ID: str
    ALI_ACCESS_KEY_SECRET: str
    
    @property
    def DB_ASYNC_URL(self) -> str:
        """获取异步数据库URL"""
        # 确保密码中的特殊字符被正确编码
        encoded_password = self.DB_PASSWORD.replace('@', '%40')
        return f"mysql+aiomysql://{self.DB_USER}:{encoded_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # JWT配置
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 开发中，暂时设置30分钟过期
    
    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = True
        
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


# pydantic_settings 会自动将 .env 文件中定义的变量赋值给 Settings 类的对应配置项，并进行类型检查和验证
settings = Settings()