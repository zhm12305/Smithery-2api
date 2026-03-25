"""
配置管理模块

使用pydantic-settings管理应用配置，支持环境变量和.env文件。
"""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # 域名配置
    domain: str = Field(default="localhost", description="服务域名")

    # 服务配置
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    port: int = Field(default=20179, description="服务监听端口")
    debug: bool = Field(default=False, description="调试模式")
    workers: int = Field(default=1, description="工作进程数")
    
    # Smithery.ai配置
    smithery_url: str = Field(
        default="https://smithery.ai",
        description="Smithery.ai服务地址"
    )
    smithery_auth_token: Optional[str] = Field(
        default="base64-YOUR_SMITHERY_AUTH_TOKEN_HERE",
        description="Smithery.ai 认证token（Supabase session JSON 的 base64 编码）"
    )
    smithery_wos_session: Optional[str] = Field(
        default=None,
        description="Smithery.ai wos-session（Hapi.js Iron 加密 session，真正的认证 cookie）"
    )

    @property
    def smithery_cookie(self) -> str:
        """
        构建发送给 Smithery 的完整 Cookie 字符串。
        核心认证是 wos-session（Hapi Iron session）。
        Supabase token 分段附加（.0 和 .1）。
        """
        CHUNK = 3180
        NAME = "sb-spjawbfpwezjfmicopsl-auth-token"
        token = self.smithery_auth_token or ""
        parts = []
        if token:
            if len(token) <= CHUNK:
                parts.append(f"{NAME}.0={token}")
            else:
                parts.append(f"{NAME}.0={token[:CHUNK]}")
                parts.append(f"{NAME}.1={token[CHUNK:]}")
        if self.smithery_wos_session:
            parts.append(f"wos-session={self.smithery_wos_session}")
        return "; ".join(parts)

    # 数据库配置
    database_url: str = Field(
        default="sqlite:///./users.db",
        description="数据库连接URL"
    )

    # JWT认证配置
    jwt_secret_key: str = Field(
        default="your-super-secret-jwt-key-change-this",
        description="JWT签名密钥"
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT签名算法"
    )
    jwt_access_token_expire_minutes: int = Field(
        default=43200,  # 30天
        description="JWT访问令牌过期时间(分钟)"
    )

    # 用户系统配置
    allow_registration: bool = Field(
        default=True,
        description="是否允许用户注册"
    )
    default_user_active: bool = Field(
        default=True,
        description="新用户默认是否激活"
    )

    # 客户端API密钥配置
    api_keys_file: str = Field(
        default="api_keys.json",
        description="客户端API密钥存储文件"
    )

    # MCP配置
    mcp_timeout: int = Field(
        default=30,
        description="MCP连接超时时间(秒)"
    )
    mcp_retry_attempts: int = Field(
        default=3,
        description="MCP连接重试次数"
    )

    # MCP Playground 配置
    enable_mcp_tools: bool = Field(
        default=True,
        description="启用MCP工具调用"
    )
    mcp_cache_ttl: int = Field(
        default=3600,
        description="MCP工具缓存时间(秒)"
    )
    mcp_max_concurrent_calls: int = Field(
        default=5,
        description="最大并发工具调用数"
    )
    mcp_tool_timeout: int = Field(
        default=30,
        description="工具调用超时时间(秒)"
    )
    mcp_search_page_size: int = Field(
        default=20,
        description="MCP服务器搜索每页大小"
    )
    
    # 日志配置
    log_level: str = Field(
        default="INFO",
        description="日志级别"
    )
    
    # 代理配置
    http_proxy: Optional[str] = Field(
        default=None,
        description="HTTP代理地址"
    )
    https_proxy: Optional[str] = Field(
        default=None,
        description="HTTPS代理地址"
    )

    # 工具配置
    google_search_api_key: str = Field(
        default="YOUR_GOOGLE_SEARCH_API_KEY",
        description="Google搜索API密钥"
    )
    google_search_cx: str = Field(
        default="YOUR_GOOGLE_SEARCH_CX",
        description="Google搜索CX"
    )
    tools_enabled: bool = Field(default=True, description="是否启用工具功能")
    code_execution_enabled: bool = Field(default=True, description="是否启用代码执行")
    code_execution_timeout: int = Field(default=30, description="代码执行超时时间(秒)")
    web_fetch_timeout: int = Field(default=10, description="网页获取超时时间(秒)")
    max_search_results: int = Field(default=5, description="最大搜索结果数")
    documents_directory: str = Field(default="documents", description="文档存储目录")
    gemini_api_key: Optional[str] = Field(default=None, description="Gemini/OpenAI-compatible vision API key")
    gemini_base_url: Optional[str] = Field(default=None, description="Gemini/OpenAI-compatible vision API base URL")

    # 图片分析配置
    image_analysis_enabled: bool = Field(default=True, description="是否启用图片分析功能")
    image_analysis_timeout: int = Field(default=60, description="图片分析超时时间(秒)")
    max_image_size: int = Field(default=10485760, description="最大图片大小(字节)，默认10MB")
    supported_image_formats: list = Field(
        default=["jpeg", "jpg", "png", "gif", "webp", "bmp"],
        description="支持的图片格式"
    )
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.debug
    
    @property
    def proxy_config(self) -> Optional[dict]:
        """代理配置字典"""
        if self.http_proxy or self.https_proxy:
            return {
                "http://": self.http_proxy,
                "https://": self.https_proxy,
            }
        return None


# 全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


def reload_settings(env_values: dict = None) -> Settings:
    """
    重新加载配置
    
    从 .env 文件重新读取配置并更新全局 settings 对象。
    这允许在运行时动态更新配置，例如更新 Smithery Token。
    
    Args:
        env_values: 可选的环境变量字典，会在重新加载前设置到 os.environ
    
    Returns:
        Settings: 更新后的配置实例
    """
    global settings
    import logging
    import os
    logger = logging.getLogger(__name__)
    
    try:
        # 如果提供了环境变量值，先更新到 os.environ
        # 这确保 Pydantic Settings 能读取到最新值（环境变量优先级 > .env 文件）
        if env_values:
            for key, value in env_values.items():
                if value is not None:
                    os.environ[key] = str(value)
                    logger.debug(f"更新环境变量: {key}")
        
        # 重新创建 Settings 实例，会重新读取 .env 文件和环境变量
        new_settings = Settings()
        
        # 更新全局 settings 对象的所有属性
        for field_name in settings.model_fields.keys():
            setattr(settings, field_name, getattr(new_settings, field_name))
        
        logger.info("✅ 配置已成功重新加载")
        return settings
    except Exception as e:
        logger.error(f"❌ 配置重载失败: {e}")
        raise

