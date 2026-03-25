"""
日志配置模块

配置结构化日志系统。
"""

import logging
import sys
from typing import Any, Dict

import structlog
from pythonjsonlogger import jsonlogger


def setup_logging(log_level: str = "INFO") -> None:
    """设置日志配置"""
    
    # 配置标准库日志
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )
    
    # 配置structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # 设置第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


class StructuredLogger:
    """结构化日志器包装类"""
    
    def __init__(self, name: str):
        self.logger = structlog.get_logger(name)
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """调试日志"""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs: Any) -> None:
        """信息日志"""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """警告日志"""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs: Any) -> None:
        """错误日志"""
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs: Any) -> None:
        """严重错误日志"""
        self.logger.critical(message, **kwargs)
    
    def bind(self, **kwargs: Any) -> "StructuredLogger":
        """绑定上下文信息"""
        bound_logger = self.logger.bind(**kwargs)
        new_instance = StructuredLogger.__new__(StructuredLogger)
        new_instance.logger = bound_logger
        return new_instance


def get_logger(name: str) -> StructuredLogger:
    """获取结构化日志器"""
    return StructuredLogger(name)


# 请求日志中间件
class RequestLoggingMiddleware:
    """请求日志中间件"""
    
    def __init__(self, app):
        self.app = app
        self.logger = get_logger("request")
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request_logger = self.logger.bind(
                method=scope["method"],
                path=scope["path"],
                query_string=scope.get("query_string", b"").decode(),
                client=scope.get("client", ["unknown", 0])[0]
            )
            
            request_logger.info("请求开始")
            
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    request_logger.bind(
                        status_code=message["status"]
                    ).info("请求完成")
                await send(message)
            
            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)
