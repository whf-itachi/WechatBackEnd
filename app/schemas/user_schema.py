from sqlmodel import SQLModel, Field
from typing import Optional
from pydantic import EmailStr

# 用户基础模型
class UserBase(SQLModel):
    name: str = Field(..., description="用户名")
    phone: str = Field(..., description="手机号")
    email: EmailStr = Field(..., description="邮箱")
    is_active: bool = Field(default=True, description="是否激活")

# 用户创建模型
class UserCreate(UserBase):
    password: str = Field(..., description="密码")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "whf",
                "phone": "13157169068",
                "email": "itachi_ashes@163.com",
                "password": "123"
            }
        }

# 用户更新模型
class UserUpdate(SQLModel):
    name: Optional[str] = Field(None, description="用户名")
    phone: Optional[str] = Field(None, description="手机号")
    email: Optional[EmailStr] = Field(None, description="邮箱")
    password: Optional[str] = Field(None, description="密码")
    is_active: Optional[bool] = Field(None, description="是否激活")

class UserTypeUpdate(SQLModel):
    user_type: Optional[str] = Field(None, description="用户类型")

# 用户登录模型
class UserLogin(SQLModel):
    name: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "whf",
                "password": "123"
            }
        }

# 用户响应模型
class UserResponse(SQLModel):
    user: dict
    token: Optional[str] = Field(None, description="访问令牌")

    class Config:
        from_attributes = True
