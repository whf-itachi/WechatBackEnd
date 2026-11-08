"""小程序登录与「双向唯一」微信绑定。

规则：
- 一个 user 只有一个 wx_openid，一个 wx_openid 也只属于一个 user（数据库唯一索引兜底）；
- 首次登录 / 换微信号：wx-login 查不到绑定 -> 前端要求输入账号密码 -> wx-bind 校验并写入绑定；
- 日常启动：wx-login 查到绑定 -> 直接签发 JWT，不再输密码；
- 任何一次新的密码绑定都会覆盖双方旧绑定：
  账号原来的微信号解绑，该微信号原来绑定的账号也解绑。
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.logger import get_logger
from app.models.user import User
from app.schemas.user_schema import UserLogin
from app.services.user_service import verify_user_login
from app.utils.jwt import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token

logger = get_logger("wx_auth_service")


def _issue_token(user: User) -> str:
    return create_access_token(
        data={"user_id": str(user.id), "user_type": str(user.user_type)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


async def wx_login(session, openid: str):
    """已绑定返回 (user, token)，未绑定返回 (None, None)。"""
    result = await session.execute(
        select(User).where(User.wx_openid == openid, User.is_active == True)  # noqa: E712
    )
    user = result.scalars().first()
    if not user:
        # 停用账号即使还留着绑定，也不能静默登录
        return None, None
    return user, _issue_token(user)


async def wx_bind(session, name: str, password: str, openid: str):
    """校验账号密码后，把该 openid 绑定到这个账号（双向覆盖旧绑定）。"""
    # 复用现有登录校验：用户名/手机号登录、停用账号、密码错误都走同一套口径
    user, token = await verify_user_login(session, UserLogin(name=name, password=password))

    # 先把这个微信号原先绑的其它账号解绑（双向唯一的另一半）
    others = (
        await session.execute(
            select(User).where(User.wx_openid == openid, User.id != user.id)
        )
    ).scalars().all()
    for other in others:
        logger.info(f"微信绑定替换：解绑原账号 {other.id}/{other.name}")
        other.wx_openid = None

    # 覆盖本账号原来的绑定（换微信号的场景）
    old_openid = user.wx_openid
    user.wx_openid = openid
    user.updated_at = datetime.now(timezone.utc)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.error("微信绑定写入冲突（并发绑定同一个 openid）")
        raise HTTPException(status_code=409, detail="绑定冲突，请重试")
    await session.refresh(user)
    logger.info(
        f"微信绑定成功: user={user.id}/{user.name}, "
        f"旧openid={'有' if old_openid else '无'}, 替换账号数={len(others)}"
    )
    return user, token


async def wx_unbind(session, user: User) -> bool:
    """解绑当前账号的微信；返回是否真的改动过。"""
    if not user.wx_openid:
        return False
    user.wx_openid = None
    user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    logger.info(f"微信解绑成功: user={user.id}/{user.name}")
    return True


async def admin_unbind(session, user_id: int) -> User:
    """管理员按 user_id 解绑（微信号被封 / 员工离职兜底）。"""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.wx_openid = None
    user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(user)
    logger.info(f"管理员解绑微信: user={user.id}/{user.name}")
    return user
