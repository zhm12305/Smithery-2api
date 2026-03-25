"""
RikkaHub兼容API端点 - 修复版本
"""

import logging
import json

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse

from ...services.auth_manager import AuthManager
from ...config import Settings, get_settings
from .chat import get_auth_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rikkahub", tags=["RikkaHub兼容"])

# 创建额外的路由器用于不同的URL格式
openai_router = APIRouter(prefix="/api/v1/rikkahub", tags=["RikkaHub-OpenAI兼容"])
simple_router = APIRouter(prefix="/rikkahub", tags=["RikkaHub-简单"])
mirror_router = APIRouter(prefix="/rikkahub/v1", tags=["RikkaHub-镜像"])


def convert_openai_to_rikkahub(openai_response: dict) -> dict:
    """
    将OpenAI格式响应转换为RikkaHub格式

    Args:
        openai_response: OpenAI格式的响应

    Returns:
        RikkaHub格式的响应 {"output": "..."}
    """
    try:
        # 提取内容
        content = ""
        if isinstance(openai_response, dict):
            if "choices" in openai_response and openai_response["choices"]:
                choice = openai_response["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    content = choice["message"]["content"]

        # 返回RikkaHub格式
        rikkahub_response = {
            "output": content or ""
        }

        # 可选：添加模型信息
        if isinstance(openai_response, dict) and "model" in openai_response:
            rikkahub_response["model"] = openai_response["model"]

        logger.info(f"成功转换为RikkaHub格式，内容长度: {len(content)}")
        return rikkahub_response

    except Exception as e:
        logger.error(f"转换为RikkaHub格式失败: {e}")
        return {"output": "", "error": "格式转换失败"}


@router.post("/chat/completions")
async def rikkahub_chat_completions(
    http_request: Request,
    settings: Settings = Depends(get_settings),
    auth_manager: AuthManager = Depends(get_auth_manager)
):
    """
    RikkaHub兼容的聊天完成端点 - 简化版本

    直接调用现有的OpenAI端点，然后转换响应格式
    """

    try:
        logger.info("RikkaHub聊天完成请求开始")

        # 直接调用现有的OpenAI聊天完成端点
        from .chat import create_chat_completion

        # 调用现有的聊天完成逻辑
        openai_response = await create_chat_completion(
            http_request=http_request,
            settings=settings,
            auth_manager=auth_manager
        )

        logger.info(f"OpenAI响应类型: {type(openai_response)}")

        # 如果是JSONResponse，提取内容
        if hasattr(openai_response, 'body'):
            # 这是一个Response对象
            import json
            response_content = json.loads(openai_response.body.decode('utf-8'))
            logger.info("从Response对象提取内容成功")
        else:
            # 这可能是直接的字典
            response_content = openai_response
            logger.info("直接使用响应内容")

        # 转换为RikkaHub格式
        rikkahub_response = convert_openai_to_rikkahub(response_content)

        logger.info(f"RikkaHub转换成功，输出长度: {len(rikkahub_response.get('output', ''))}")

        return JSONResponse(
            content=rikkahub_response,
            headers={"Content-Type": "application/json"}
        )

    except HTTPException as e:
        logger.error(f"RikkaHub聊天完成HTTP错误: {e.detail}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": str(e.detail)},
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"RikkaHub聊天完成处理失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"内部服务器错误: {str(e)}"},
            headers={"Content-Type": "application/json"}
        )


@router.post("/predict")
async def rikkahub_predict(
    http_request: Request,
    settings: Settings = Depends(get_settings),
    auth_manager: AuthManager = Depends(get_auth_manager)
):
    """
    通用预测端点 - 简化版本

    接受 {input: "...", model: "..."} 格式，返回 {output: "..."} 格式
    """

    try:
        logger.info("RikkaHub预测请求开始")

        # 读取请求体
        body = await http_request.body()
        body_str = body.decode('utf-8')

        try:
            request_data = json.loads(body_str)
            logger.info(f"成功解析请求JSON: {list(request_data.keys())}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON"},
                headers={"Content-Type": "application/json"}
            )

        # 提取输入内容
        input_text = request_data.get("input", request_data.get("prompt", ""))
        if not input_text:
            logger.error("缺少input或prompt字段")
            return JSONResponse(
                status_code=400,
                content={"error": "Missing input or prompt"},
                headers={"Content-Type": "application/json"}
            )

        logger.info(f"输入文本长度: {len(input_text)}")

        # 构造标准的OpenAI请求格式
        openai_request_data = {
            "model": request_data.get("model", "claude-haiku-4.5"),
            "messages": [
                {"role": "user", "content": input_text}
            ],
            "stream": False
        }

        # 创建新的请求对象，模拟标准的OpenAI请求
        from starlette.requests import Request as StarletteRequest
        from starlette.datastructures import Headers

        # 构造新的请求
        new_body = json.dumps(openai_request_data).encode('utf-8')

        async def new_receive():
            return {
                "type": "http.request",
                "body": new_body,
                "more_body": False
            }

        # 复制原始scope并更新headers
        new_scope = http_request.scope.copy()
        new_headers = []
        for name, value in http_request.headers.items():
            if name.lower() != "content-length":
                new_headers.append((name.encode(), value.encode()))
        new_headers.append((b"content-type", b"application/json"))
        new_headers.append((b"content-length", str(len(new_body)).encode()))
        new_scope["headers"] = new_headers

        # 创建新的请求对象
        new_request = Request(new_scope, new_receive)

        # 调用现有的OpenAI聊天完成端点
        from .chat import create_chat_completion

        openai_response = await create_chat_completion(
            http_request=new_request,
            settings=settings,
            auth_manager=auth_manager
        )

        logger.info(f"OpenAI响应类型: {type(openai_response)}")

        # 提取响应内容
        if hasattr(openai_response, 'body'):
            response_content = json.loads(openai_response.body.decode('utf-8'))
        else:
            response_content = openai_response

        # 转换为RikkaHub格式
        rikkahub_response = convert_openai_to_rikkahub(response_content)

        logger.info(f"RikkaHub预测转换成功，输出长度: {len(rikkahub_response.get('output', ''))}")

        return JSONResponse(
            content=rikkahub_response,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"RikkaHub预测错误: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"处理失败: {str(e)}"},
            headers={"Content-Type": "application/json"}
        )


@router.post("/openai")
async def rikkahub_openai_compatible(
    request: Request,
    settings: Settings = Depends(get_settings),
    auth_manager: AuthManager = Depends(get_auth_manager)
):
    """
    RikkaHub OpenAI完全兼容端点

    强制使用application/json Content-Type，确保100%兼容
    """

    try:
        logger.info("RikkaHub OpenAI兼容请求开始")

        # 强制设置Content-Type为application/json
        headers = dict(request.headers)
        headers["content-type"] = "application/json"

        # 重建request
        scope = request.scope.copy()
        scope["headers"] = [
            (name.encode() if isinstance(name, str) else name,
             value.encode() if isinstance(value, str) else value)
            for name, value in headers.items()
        ]

        body = await request.body()

        async def new_receive():
            return {
                "type": "http.request",
                "body": body,
                "more_body": False
            }

        new_request = Request(scope, new_receive)

        # 调用标准OpenAI端点
        from .chat import create_chat_completion

        openai_response = await create_chat_completion(
            http_request=new_request,
            settings=settings,
            auth_manager=auth_manager
        )

        # 提取响应内容
        if hasattr(openai_response, 'body'):
            response_content = json.loads(openai_response.body.decode('utf-8'))
        else:
            response_content = openai_response

        # 转换为RikkaHub格式
        rikkahub_response = convert_openai_to_rikkahub(response_content)

        logger.info(f"RikkaHub OpenAI兼容转换成功")

        return JSONResponse(
            content=rikkahub_response,
            headers={
                "Content-Type": "application/json",
                "X-RikkaHub-Compatible": "true"
            }
        )

    except Exception as e:
        logger.error(f"RikkaHub OpenAI兼容处理失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"处理失败: {str(e)}"},
            headers={"Content-Type": "application/json"}
        )


@router.post("/simple")
async def rikkahub_simple(
    request: Request,
    settings: Settings = Depends(get_settings),
    auth_manager: AuthManager = Depends(get_auth_manager)
):
    """
    RikkaHub最简单调用端点

    接受任何格式，返回简单的{output: "..."}
    """

    try:
        logger.info("RikkaHub简单调用开始")

        # 读取请求体
        body = await request.body()
        body_str = body.decode('utf-8')

        try:
            request_data = json.loads(body_str)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON"},
                headers={"Content-Type": "application/json"}
            )

        # 提取消息内容
        messages = []
        if "messages" in request_data:
            messages = request_data["messages"]
        elif "input" in request_data:
            messages = [{"role": "user", "content": request_data["input"]}]
        elif "prompt" in request_data:
            messages = [{"role": "user", "content": request_data["prompt"]}]
        else:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing messages, input, or prompt"},
                headers={"Content-Type": "application/json"}
            )

        # 构造标准请求
        standard_request = {
            "model": request_data.get("model", "claude-haiku-4.5"),
            "messages": messages,
            "stream": False
        }

        # 创建新的请求对象
        new_body = json.dumps(standard_request).encode('utf-8')

        headers = dict(request.headers)
        headers["content-type"] = "application/json"
        headers["content-length"] = str(len(new_body))

        scope = request.scope.copy()
        scope["headers"] = [
            (name.encode() if isinstance(name, str) else name,
             value.encode() if isinstance(value, str) else value)
            for name, value in headers.items()
        ]

        async def new_receive():
            return {
                "type": "http.request",
                "body": new_body,
                "more_body": False
            }

        new_request = Request(scope, new_receive)

        # 调用OpenAI端点
        from .chat import create_chat_completion

        openai_response = await create_chat_completion(
            http_request=new_request,
            settings=settings,
            auth_manager=auth_manager
        )

        # 提取和转换响应
        if hasattr(openai_response, 'body'):
            response_content = json.loads(openai_response.body.decode('utf-8'))
        else:
            response_content = openai_response

        rikkahub_response = convert_openai_to_rikkahub(response_content)

        logger.info(f"RikkaHub简单调用成功")

        return JSONResponse(
            content=rikkahub_response,
            headers={
                "Content-Type": "application/json",
                "X-RikkaHub-Compatible": "true",
                "Access-Control-Allow-Origin": "*"
            }
        )

    except Exception as e:
        logger.error(f"RikkaHub简单调用失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"处理失败: {str(e)}"},
            headers={"Content-Type": "application/json"}
        )
