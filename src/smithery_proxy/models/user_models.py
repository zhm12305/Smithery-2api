"""
用户管理数据模型

定义用户、API密钥、使用统计等数据模型
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# SQLAlchemy 数据库模型
class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联关系
    api_keys = relationship("UserAPIKey", back_populates="user")
    usage_logs = relationship("UsageLog", back_populates="user")

class UserAPIKey(Base):
    """用户API密钥表"""
    __tablename__ = "user_api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    api_key = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)  # 密钥名称
    description = Column(Text, nullable=True)
    model = Column(String(50), default="claude-haiku-4.5", nullable=False)  # 支持的模型
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)
    
    # 关联关系
    user = relationship("User", back_populates="api_keys")
    usage_logs = relationship("UsageLog", back_populates="api_key")

class UsageLog(Base):
    """使用日志表"""
    __tablename__ = "usage_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    api_key_id = Column(Integer, ForeignKey("user_api_keys.id"), nullable=False)
    endpoint = Column(String(100), nullable=False)  # /v1/chat/completions, /v1/models
    method = Column(String(10), nullable=False)  # GET, POST
    status_code = Column(Integer, nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    model = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关联关系
    user = relationship("User", back_populates="usage_logs")
    api_key = relationship("UserAPIKey", back_populates="usage_logs")

# Pydantic 请求/响应模型
class UserCreate(BaseModel):
    """用户创建请求"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserLogin(BaseModel):
    """用户登录请求"""
    username: str
    password: str

class UserResponse(BaseModel):
    """用户响应"""
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class APIKeyCreate(BaseModel):
    """API密钥创建请求"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    model: str = Field(default="claude-haiku-4.5", description="支持的模型")

class APIKeyResponse(BaseModel):
    """API密钥响应"""
    id: int
    api_key: str
    name: str
    description: Optional[str]
    model: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]
    usage_count: int
    
    class Config:
        from_attributes = True

class APIKeyUpdate(BaseModel):
    """API密钥更新请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class UsageStats(BaseModel):
    """使用统计"""
    total_requests: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    today_requests: int
    today_tokens: int

class UsageLogResponse(BaseModel):
    """使用日志响应"""
    id: int
    endpoint: str
    method: str
    status_code: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    """JWT Token响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class TokenData(BaseModel):
    """Token数据"""
    username: Optional[str] = None
    user_id: Optional[int] = None
