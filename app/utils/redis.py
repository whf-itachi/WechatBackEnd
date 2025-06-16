# app/utils/redis.py
import redis.asyncio as redis

_redis_db = None  # 用下划线避免直接导入

async def init_redis():
    global _redis_db
    _redis_db = redis.from_url("redis://localhost", decode_responses=True)
    await _redis_db.ping()

async def close_redis():
    global _redis_db
    if _redis_db:
        await _redis_db.close()

def get_redis():
    if _redis_db is None:
        raise RuntimeError("Redis 未初始化")
    return _redis_db
