"""
认证管理器

负责管理Smithery.ai的认证token，自动刷新和错误处理。
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass
class AuthToken:
    """认证token数据类"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    created_at: float = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
    
    @property
    def is_expired(self) -> bool:
        """检查token是否过期"""
        if self.expires_in is None:
            return False
        
        expiry_time = self.created_at + self.expires_in - 60  # 提前60秒刷新
        return time.time() > expiry_time
    
    @property
    def authorization_header(self) -> str:
        """获取Authorization头部值"""
        return f"{self.token_type} {self.access_token}"


class AuthenticationError(Exception):
    """认证错误"""
    pass


class AuthManager:
    """认证管理器类"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: Optional[AuthToken] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._refresh_lock = asyncio.Lock()
        
    async def initialize(self) -> None:
        """初始化认证管理器"""
        # 创建HTTP客户端，处理代理配置
        client_kwargs = {"timeout": httpx.Timeout(30.0)}
        if self.settings.proxy_config:
            client_kwargs["proxies"] = self.settings.proxy_config

        self._http_client = httpx.AsyncClient(**client_kwargs)
        
        # 如果配置了认证token，直接使用
        if self.settings.smithery_auth_token:
            self._token = AuthToken(
                access_token=self.settings.smithery_auth_token,
                token_type="Bearer"
            )
            logger.info("使用配置的认证token进行认证")
        else:
            logger.warning("未配置Smithery认证token")
    
    async def get_auth_header(self) -> Dict[str, str]:
        """获取认证头部"""
        token = await self.get_valid_token()
        if token:
            return {"Authorization": token.authorization_header}
        return {}
    
    async def get_valid_token(self) -> Optional[AuthToken]:
        """获取有效的认证token"""
        if not self._token:
            return None
        
        # 检查token是否过期
        if self._token.is_expired:
            logger.info("Token已过期，尝试刷新")
            await self._refresh_token()
        
        return self._token
    
    async def _refresh_token(self) -> None:
        """刷新认证token"""
        async with self._refresh_lock:
            # 双重检查，避免重复刷新
            if self._token and not self._token.is_expired:
                return
            
            if not self._token or not self._token.refresh_token:
                logger.warning("无法刷新token：缺少refresh_token")
                return
            
            try:
                await self._perform_token_refresh()
            except Exception as e:
                logger.error(f"刷新token失败: {e}")
                raise AuthenticationError(f"Token刷新失败: {e}")
    
    async def _perform_token_refresh(self) -> None:
        """执行token刷新请求"""
        if not self._http_client:
            raise AuthenticationError("HTTP客户端未初始化")
        
        refresh_url = f"{self.settings.smithery_url}/api/auth/refresh"
        
        data = {
            "refresh_token": self._token.refresh_token,
            "grant_type": "refresh_token"
        }
        
        try:
            response = await self._http_client.post(
                refresh_url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self._token = AuthToken(
                    access_token=token_data["access_token"],
                    token_type=token_data.get("token_type", "Bearer"),
                    expires_in=token_data.get("expires_in"),
                    refresh_token=token_data.get("refresh_token", self._token.refresh_token)
                )
                logger.info("Token刷新成功")
            else:
                error_msg = f"Token刷新失败: HTTP {response.status_code}"
                if response.headers.get("content-type", "").startswith("application/json"):
                    error_data = response.json()
                    error_msg += f" - {error_data.get('error', 'Unknown error')}"
                raise AuthenticationError(error_msg)
                
        except httpx.RequestError as e:
            raise AuthenticationError(f"Token刷新请求失败: {e}")
    
    async def authenticate_with_credentials(
        self, 
        username: str, 
        password: str
    ) -> None:
        """使用用户名密码进行认证"""
        if not self._http_client:
            raise AuthenticationError("HTTP客户端未初始化")
        
        auth_url = f"{self.settings.smithery_url}/api/auth/login"
        
        data = {
            "username": username,
            "password": password,
            "grant_type": "password"
        }
        
        try:
            response = await self._http_client.post(
                auth_url,
                json=data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self._token = AuthToken(
                    access_token=token_data["access_token"],
                    token_type=token_data.get("token_type", "Bearer"),
                    expires_in=token_data.get("expires_in"),
                    refresh_token=token_data.get("refresh_token")
                )
                logger.info("用户名密码认证成功")
            else:
                error_msg = f"认证失败: HTTP {response.status_code}"
                if response.headers.get("content-type", "").startswith("application/json"):
                    error_data = response.json()
                    error_msg += f" - {error_data.get('error', 'Invalid credentials')}"
                raise AuthenticationError(error_msg)
                
        except httpx.RequestError as e:
            raise AuthenticationError(f"认证请求失败: {e}")
    
    async def validate_token(self) -> bool:
        """验证当前token是否有效"""
        if not self._token:
            return False
        
        if not self._http_client:
            return False
        
        validate_url = f"{self.settings.smithery_url}/api/auth/validate"
        
        try:
            response = await self._http_client.get(
                validate_url,
                headers={"Authorization": self._token.authorization_header}
            )
            
            return response.status_code == 200
            
        except httpx.RequestError:
            return False
    
    async def logout(self) -> None:
        """登出并清除token"""
        if self._token and self._http_client:
            logout_url = f"{self.settings.smithery_url}/api/auth/logout"
            
            try:
                await self._http_client.post(
                    logout_url,
                    headers={"Authorization": self._token.authorization_header}
                )
            except httpx.RequestError:
                pass  # 忽略登出请求错误
        
        self._token = None
        logger.info("已登出")
    
    async def close(self) -> None:
        """关闭认证管理器"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器出口"""
        # 忽略异常信息，总是关闭客户端
        await self.close()
