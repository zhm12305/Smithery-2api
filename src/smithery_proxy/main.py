"""
Smithery Claude Proxy主应用

FastAPI应用入口点，提供OpenAI兼容的Claude 4 Sonnet/Opus代理服务。
"""

import logging
import sys
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles


from .config import get_settings
from .api.v1.chat import router as chat_router
from .api.v1.users import router as users_router
from .api.v1.admin import router as admin_router
from .api.v1.rikkahub import router as rikkahub_router
from .api.v1.mcp import router as mcp_router
from .utils.logger import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理"""
    settings = get_settings()
    
    # 启动时初始化
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    
    logger.info("启动Smithery Claude Proxy服务")
    logger.info(f"配置: Debug={settings.debug}, Port={settings.port}")
    
    yield
    
    # 关闭时清理
    logger.info("关闭Smithery Claude Proxy服务")


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    settings = get_settings()
    
    app = FastAPI(
        title="Smithery Claude Proxy",
        description="OpenAI兼容的Claude 3.5 Sonnet代理服务",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan
    )
    
    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应该限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 添加Content-Type修复中间件 - 更强力的版本
    @app.middleware("http")
    async def fix_content_type_middleware(request: Request, call_next):
        """修复Content-Type中间件 - 强制修复版本"""

        # 如果是chat completions API请求
        if (request.url.path == "/v1/chat/completions" and
            request.method == "POST"):

            content_type = request.headers.get("content-type", "")

            # 强制修复所有非application/json的Content-Type
            if not content_type.startswith("application/json"):

                # 读取原始请求体
                body = await request.body()

                # 验证是否为有效JSON
                try:
                    json.loads(body.decode('utf-8'))

                    # 如果是有效JSON，强制设置正确的Content-Type
                    from starlette.requests import Request as StarletteRequest
                    from starlette.datastructures import Headers, MutableHeaders

                    # 创建新的headers
                    new_headers = MutableHeaders(request.headers)
                    new_headers["content-type"] = "application/json"

                    # 重新构建request
                    scope = request.scope.copy()
                    scope["headers"] = [
                        (name.encode(), value.encode())
                        for name, value in new_headers.items()
                    ]

                    # 创建新的receive函数来返回body
                    async def new_receive():
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False
                        }

                    # 创建新的request对象
                    request = Request(scope, new_receive)

                except (json.JSONDecodeError, UnicodeDecodeError):
                    # 如果不是有效JSON，让它正常失败
                    pass

        response = await call_next(request)
        return response
    
    # 注册路由
    app.include_router(chat_router)  # Claude API: /v1/chat/completions, /v1/models
    app.include_router(users_router, prefix="/api/v1")  # 用户管理API: /api/v1/users/*
    app.include_router(admin_router, prefix="/api/v1")  # 管理员API: /api/v1/admin/*
    app.include_router(rikkahub_router, prefix="/api/v1")  # RikkaHub兼容API: /api/v1/rikkahub/*
    app.include_router(mcp_router, prefix="/api/v1")  # MCP管理API: /api/v1/mcp/*

    # 静态文件服务
    from pathlib import Path
    web_dir = Path(__file__).parent.parent.parent / "web"
    if web_dir.exists():
        # 管理员界面
        app.mount("/admin", StaticFiles(directory=str(web_dir), html=True), name="admin")
        # 主要静态文件（用户界面）
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


    
    # HTML页面路由
    @app.get("/")
    async def serve_index():
        """主页"""
        return FileResponse(str(web_dir / "index.html"))

    @app.get("/dashboard.html")
    async def serve_dashboard():
        """用户控制台"""
        return FileResponse(str(web_dir / "dashboard.html"))

    @app.get("/admin.html")
    async def serve_admin():
        """管理员界面"""
        return FileResponse(str(web_dir / "admin.html"))

    # API健康检查
    @app.get("/v1/health")
    async def health_check():
        return {
            "service": "Smithery Claude Proxy",
            "version": "0.1.0",
            "status": "running",
            "docs": "/docs" if settings.debug else "disabled"
        }
    
    # 全局异常处理器
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger = logging.getLogger(__name__)
        logger.error(f"全局异常处理: {exc}", exc_info=True)
        
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "内部服务器错误",
                    "type": "internal_error",
                    "code": "500"
                }
            }
        )
    
    return app


# 创建应用实例
app = create_app()


def main():
    """主函数，用于命令行启动"""
    settings = get_settings()
    
    # 设置日志
    setup_logging(settings.log_level)
    
    # 启动服务器
    uvicorn.run(
        "smithery_proxy.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True,
        server_header=False,
        date_header=False
    )


if __name__ == "__main__":
    main()
