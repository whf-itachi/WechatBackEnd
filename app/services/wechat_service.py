# 微信处理服务

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int

app = FastAPI()

@app.post("/register/")
async def register_user(user: User):
    # 如果数据通过验证，这里的`user`就是一个已验证且类型正确的`User`实例
    # 你可以安全地使用`user.name`和`user.age`，它们已经被验证为`str`和`int`类型
    return {"name": user.name, "age": user.age}