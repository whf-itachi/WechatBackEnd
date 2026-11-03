from fastapi import APIRouter, Depends, HTTPException
from app.utils.enveloping_route import EnvelopingRoute
from sqlalchemy.ext.asyncio import AsyncSession
from app.db_services.database import get_db
from app.services.user_service import (
    create_user_service,
    get_users_service,
    get_user_service,
    update_user_service,
    delete_user_service,
    verify_user_login,
    get_password_hash,
    verify_password
)
from app.schemas.user_schema import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserLogin,
    UserPublic,
    UserPasswordChange
)
from app.dependencies.auth import get_current_user, require_admin
from app.models.user import User
from datetime import datetime, timezone
from typing import List
from app.logger import get_logger

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger('user_router')

# 注册用户
# 账号统一由后台超管创建：本接口要求携带管理员 token，
# 移动端已不提供自助注册入口，这里再兜住"直接调接口建号"的路径。
@router.post("/register", response_model=UserResponse)
async def register_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """新建用户（仅管理员）

    - 必须由 user_type == "admin" 的账号调用，否则 403；
    - 密码长度 3-10 位，由 UserCreate 的 schema 统一校验；
    - 新账号默认 user_type=employee，需要管理员权限请在后台再调整角色。
    """
    logger.info(
        f"收到用户注册请求（操作人: {current_user.name}/{current_user.id}）: "
        f"{user_data.model_dump(exclude={'password'})}"
    )
    try:
        user, token = await create_user_service(db, user_data)
        logger.info(f"用户注册成功: {UserPublic.model_validate(user).model_dump()}")
        return {
            "user": UserPublic.model_validate(user),
            "token": token
        }
    except HTTPException as e:
        logger.error(f"用户注册失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"用户注册失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "注册失败",
                "errors": [str(e)]
            }
        )

# 用户登录
@router.post("/login", response_model=UserResponse)
async def login_user(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    logger.info(f"收到用户登录请求: {login_data.model_dump(exclude={'password'})}")
    try:
        user, token = await verify_user_login(db, login_data)
        logger.info(f"用户登录成功: {UserPublic.model_validate(user).model_dump()}")
        return {
            "user": UserPublic.model_validate(user),
            "token": token
        }
    except HTTPException as e:
        logger.error(f"用户登录失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"用户登录失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "登录失败",
                "errors": [str(e)]
            }
        )

# 获取所有用户列表
@router.get("/", response_model=List[UserResponse])
async def get_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取所有用户列表"""
    logger.info(f"收到获取用户列表请求，当前用户: {current_user.id}")
    try:
        users = await get_users_service(db)
        logger.info(f"成功获取用户列表，共 {len(users)} 条记录")
        return [{"user": UserPublic.model_validate(user)} for user in users]
    except HTTPException as e:
        logger.error(f"获取用户列表失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取用户列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "获取用户列表失败",
                "errors": [str(e)]
            }
        )

# 获取当前登录用户信息（必须放在 /{user_id} 之前，否则会被当成 user_id 解析）
@router.get("/info", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息：前端刷新后用它补齐姓名等资料"""
    return {"user": UserPublic.model_validate(current_user)}


# 修改自己的登录密码
# 必须声明在 /{user_id} 之前，否则 "password" 会被当成 user_id 去解析而报 422
@router.put("/password")
async def change_my_password(
    payload: UserPasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """当前登录用户自助修改密码

    - 必须校验原密码：否则手机被他人拿走、token 未过期时可直接改密锁死账号；
    - 长度 3-10 位，不做复杂度、字节数等额外限制；
    - 新密码不能与原密码相同，避免"改了跟没改一样"；
    - 只改 password 一个字段，不碰姓名/手机号/邮箱/角色；
    - JWT 中没有密码版本号，改密后其它设备上已登录的会话在 token 过期前仍有效，
      需要强制下线要另行处理（本次不做）。
    """
    old_pwd = payload.old_password or ""
    new_pwd = (payload.new_password or "").strip()

    if not old_pwd:
        raise HTTPException(status_code=400, detail="请输入原密码")
    if not new_pwd:
        raise HTTPException(status_code=400, detail="新密码不能为空")
    if len(new_pwd) < 3 or len(new_pwd) > 10:
        raise HTTPException(status_code=400, detail="新密码长度需为 3-10 位")
    if not verify_password(old_pwd, current_user.password):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if new_pwd == old_pwd:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    try:
        current_user.password = get_password_hash(new_pwd)
        current_user.updated_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(f"用户自助修改密码成功，用户ID: {current_user.id}")
        return {"message": "密码修改成功"}
    except Exception as e:
        await db.rollback()
        logger.error(f"修改密码失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "密码修改失败",
                "errors": [str(e)]
            }
        )


# 根据ID获取用户信息
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据ID获取用户信息"""
    logger.info(f"收到获取用户信息请求，用户ID: {user_id}，当前用户: {current_user.id}")
    try:
        user = await get_user_service(db, user_id)
        logger.info(f"成功获取用户信息: {UserPublic.model_validate(user).model_dump()}")
        return {"user": UserPublic.model_validate(user)}
    except HTTPException as e:
        logger.error(f"获取用户信息失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取用户信息失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "获取用户信息失败",
                "errors": [str(e)]
            }
        )

# 更新用户信息
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新用户信息"""
    logger.info(f"收到更新用户信息请求，用户ID: {user_id}，当前用户: {current_user.id}")
    try:
        user = await update_user_service(db, user_id, user_data)
        logger.info(f"成功更新用户信息: {UserPublic.model_validate(user).model_dump()}")
        return {"user": UserPublic.model_validate(user)}
    except HTTPException as e:
        logger.error(f"更新用户信息失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"更新用户信息失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "更新用户信息失败",
                "errors": [str(e)]
            }
        )

# 删除用户（软删除）
@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除用户 —— 软删除（is_active=False），历史数据保留

    只允许注销自己；管理员可停用任意账号（与后台删除行为一致）。
    """
    logger.info(f"收到删除用户请求，用户ID: {user_id}，当前用户: {current_user.id}")
    if current_user.id != user_id and current_user.user_type != "admin":
        raise HTTPException(status_code=403, detail="只能删除自己的账号")
    try:
        result = await delete_user_service(db, user_id)
        logger.info(f"成功停用用户，用户ID: {user_id}")
        return result
    except HTTPException as e:
        logger.error(f"删除用户失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"删除用户失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "删除用户失败",
                "errors": [str(e)]
            }
        )
