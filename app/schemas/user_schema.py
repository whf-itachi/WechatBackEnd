from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

# 用户创建模型
class UserCreate(BaseModel):
    name_en: str
    name_zh: str
    phone: str
    email: str
    password: str  # 这里是明文密码，后面要加密处理


# 用户更新模型
class UserUpdate(BaseModel):
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    email: Optional[EmailStr] = None
    password: str
    is_active: Optional[bool] = None

# 用户响应模型
class UserResponse(BaseModel):
    id: int
    name_en: str
    name_zh: str
    email: EmailStr
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
