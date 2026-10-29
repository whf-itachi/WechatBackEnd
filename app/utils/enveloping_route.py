import json

from fastapi import Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.routing import APIRoute

from app.utils.responses import ApiResponse


class EnvelopingRoute(APIRoute):
    """自定义路由：把成功的 JSON 响应统一包成 {code, message, data} 信封。

    说明：
    - 流式（StreamingResponse）、文件（FileResponse）、重定向（RedirectResponse）
      不属于 JSON 业务响应，原样返回，不做包裹。
    - 异常会向上抛出，交给全局异常处理器统一封装（见 main.py）。
    """

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def custom_handler(request):
            try:
                response = await original_handler(request)
            except Exception:
                # 交给全局异常处理器统一封装
                raise

            # 流式 / 文件 / 重定向响应不包裹
            if isinstance(response, (StreamingResponse, FileResponse, RedirectResponse)):
                return response

            if isinstance(response, Response):
                # 仅对 JSON 业务响应包裹
                if response.media_type == "application/json":
                    try:
                        body = json.loads(response.body)
                    except (ValueError, TypeError):
                        return response
                    enveloped = ApiResponse(code=0, message="ok", data=body)
                    # 复制原响应头，但去掉已过期的 content-length（body 已变化）
                    headers = {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() != "content-length"
                    }
                    return Response(
                        content=enveloped.model_dump_json(),
                        status_code=response.status_code,
                        media_type="application/json",
                        headers=headers,
                    )
                return response

            # 兜底（理论上 handler 不会返回非 Response 对象）
            enveloped = ApiResponse(code=0, message="ok", data=response)
            return Response(
                content=enveloped.model_dump_json(),
                media_type="application/json",
            )

        return custom_handler
