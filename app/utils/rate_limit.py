from fastapi import HTTPException
from datetime import datetime, timezone

from app.logger import get_logger
from app.utils.redis import get_redis

logger = get_logger('limit_router')

async def rate_limit(ip: str):
    hour_key = f"rate_limit:{ip}:hour:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
    day_key = f"rate_limit:{ip}:day:{datetime.now(timezone.utc).strftime('%Y%m%d')}"

    redis_db = get_redis()
    # 获取当前值并递增
    hour_count = await redis_db.incr(hour_key)
    day_count = await redis_db.incr(day_key)

    # 设置过期时间（仅首次递增时）
    if hour_count == 1:
        await redis_db.expire(hour_key, 3600)  # 1 小时
    if day_count == 1:
        await redis_db.expire(day_key, 86400)  # 1 天

    if hour_count > 20:
        logger.error(f"{ip}:请求超过每小时20次")
        raise HTTPException(status_code=429, detail="Rate limit exceeded: more than 20 requests per hour.")
    if day_count > 100:
        logger.error(f"{ip}:请求超过每天100次")
        raise HTTPException(status_code=429, detail="Rate limit exceeded: more than 100 requests per day.")
