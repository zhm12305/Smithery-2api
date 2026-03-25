"""
用户管理API

处理用户注册、登录、API密钥管理等
"""

from datetime import timedelta
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials

from ...models.user_models import (
    UserCreate, UserLogin, UserResponse, Token,
    APIKeyCreate, APIKeyResponse, APIKeyUpdate,
    UsageStats, UsageLogResponse
)
from ...services.database import get_database_manager
from ...services.auth_service import get_auth_service, get_current_active_user, ACCESS_TOKEN_EXPIRE_MINUTES
from ...models.user_models import User

router = APIRouter(prefix="/users", tags=["用户管理"])

# 依赖注入
def get_db_manager():
    return get_database_manager()

def get_auth():
    return get_auth_service()

@router.post("/register", response_model=UserResponse, summary="用户注册")
async def register_user(
    user_data: UserCreate,
    db_manager = Depends(get_db_manager)
):
    """用户注册"""
    user = db_manager.create_user(user_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名或邮箱已存在"
        )
    
    return UserResponse.from_orm(user)

@router.post("/login", response_model=Token, summary="用户登录")
async def login_user(
    login_data: UserLogin,
    db_manager = Depends(get_db_manager),
    auth_service = Depends(get_auth)
):
    """用户登录"""
    user = db_manager.authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户账户已被禁用"
        )
    
    # 创建访问token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth_service.create_access_token(
        data={"sub": user.username, "user_id": user.id},
        expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

@router.get("/profile", response_model=UserResponse, summary="获取用户信息")
async def get_user_profile(
    current_user: User = Depends(get_current_active_user)
):
    """获取当前用户信息"""
    return UserResponse.from_orm(current_user)

@router.get("/api-keys", response_model=List[APIKeyResponse], summary="获取API密钥列表")
async def get_api_keys(
    current_user: User = Depends(get_current_active_user),
    db_manager = Depends(get_db_manager)
):
    """获取用户的所有API密钥"""
    api_keys = db_manager.get_user_api_keys(current_user.id)
    return [APIKeyResponse.from_orm(key) for key in api_keys]

@router.post("/api-keys", response_model=APIKeyResponse, summary="创建API密钥")
async def create_api_key(
    key_data: APIKeyCreate,
    current_user: User = Depends(get_current_active_user),
    db_manager = Depends(get_db_manager)
):
    """为当前用户创建新的API密钥"""
    api_key = db_manager.create_api_key(current_user.id, key_data)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="创建API密钥失败"
        )
    
    return APIKeyResponse.from_orm(api_key)

@router.delete("/api-keys/{api_key_id}", summary="删除API密钥")
async def delete_api_key(
    api_key_id: int,
    current_user: User = Depends(get_current_active_user),
    db_manager = Depends(get_db_manager)
):
    """删除指定的API密钥"""
    success = db_manager.delete_api_key(current_user.id, api_key_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API密钥不存在"
        )
    
    return {"message": "API密钥删除成功"}

@router.get("/usage/stats", response_model=UsageStats, summary="获取使用统计")
async def get_usage_stats(
    current_user: User = Depends(get_current_active_user),
    db_manager = Depends(get_db_manager)
):
    """获取用户的使用统计"""
    return db_manager.get_user_usage_stats(current_user.id)

@router.get("/usage/logs", response_model=List[UsageLogResponse], summary="获取使用日志")
async def get_usage_logs(
    limit: int = 100,
    current_user: User = Depends(get_current_active_user),
    db_manager = Depends(get_db_manager)
):
    """获取用户的使用日志"""
    logs = db_manager.get_user_usage_logs(current_user.id, limit)
    return [UsageLogResponse.from_orm(log) for log in logs]
