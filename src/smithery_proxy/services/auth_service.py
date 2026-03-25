"""
用户认证服务

处理JWT token生成、验证和用户认证
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..models.user_models import User, TokenData
from .database import get_database_manager

# JWT配置
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30天

# HTTP Bearer认证
security = HTTPBearer()

class AuthService:
    """认证服务"""
    
    def __init__(self):
        self.db_manager = get_database_manager()
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """创建访问token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> TokenData:
        """验证token"""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            user_id: int = payload.get("user_id")
            
            if username is None or user_id is None:
                raise credentials_exception
                
            token_data = TokenData(username=username, user_id=user_id)
            return token_data
            
        except JWTError:
            raise credentials_exception
    
    def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
        """获取当前用户"""
        token = credentials.credentials
        token_data = self.verify_token(token)
        
        user = self.db_manager.get_user_by_username(token_data.username)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
        
        return user
    
    def get_current_active_user(self, current_user: User = Depends(get_current_user)) -> User:
        """获取当前活跃用户"""
        if not current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
        return current_user

# 全局认证服务实例
_auth_service: Optional[AuthService] = None

def get_auth_service() -> AuthService:
    """获取全局认证服务实例"""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

# 依赖注入函数
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """获取当前用户（依赖注入）"""
    auth_service = get_auth_service()
    return auth_service.get_current_user(credentials)

def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """获取当前活跃用户（依赖注入）"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user
