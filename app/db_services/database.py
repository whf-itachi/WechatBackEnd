from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator
from sqlalchemy.pool import NullPool

from app.config import settings


# 异步引擎
engine = create_async_engine(
    settings.DB_ASYNC_URL,
    poolclass=NullPool,  # 使用 NullPool 避免连接池问题
    pool_pre_ping=True,
    echo=False  # 设置为 True 则会在控制台输出执行的 SQL 语句，方便调试
)

# 异步会话工厂
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 禁用过期提交
    autoflush=False  # 禁用自动刷新
)

# 获取数据库会话的依赖函数
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# 数据库会话类型
AsyncSessionDep = Annotated[AsyncSession, Depends(get_db)]
