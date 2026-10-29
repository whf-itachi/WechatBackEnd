from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一响应信封：所有成功响应与错误响应共用此结构。

    - code: 0 表示成功；非 0 时等于 HTTP 状态码或业务码
    - message: 成功时为 "ok"，错误时为可读信息
    - data: 业务负载（成功时）；错误时为 null
    """

    code: int = 0
    message: str = "ok"
    data: Any = None


def success(data: Any = None, message: str = "ok") -> dict:
    """构造成功响应信封（供少数需要手动返回的场景使用）。"""
    return ApiResponse(code=0, message=message, data=data).model_dump()


class BusinessError(Exception):
    """业务异常：可被全局异常处理器捕获并统一封装。

    code 用作信封内的业务码，status_code 用作 HTTP 状态码（默认与 code 一致）。
    """

    def __init__(self, message: str, code: int = 400, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
