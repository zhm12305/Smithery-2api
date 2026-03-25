"""
数据库管理器

处理数据库连接、初始化和操作
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext
import secrets
import string

from ..models.user_models import Base, User, UserAPIKey, UsageLog
from ..models.user_models import UserCreate, APIKeyCreate, UsageStats

# 密码加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, database_url: str = "sqlite:///./users.db"):
        """初始化数据库连接"""
        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # 创建表
        Base.metadata.create_all(bind=self.engine)
    
    def get_db(self) -> Session:
        """获取数据库会话"""
        db = self.SessionLocal()
        try:
            return db
        finally:
            pass  # 不在这里关闭，由调用者负责
    
    def close_db(self, db: Session):
        """关闭数据库会话"""
        db.close()
    
    # 用户管理
    def create_user(self, user_data: UserCreate) -> Optional[User]:
        """创建用户"""
        db = self.get_db()
        try:
            # 检查用户名和邮箱是否已存在
            existing_user = db.query(User).filter(
                (User.username == user_data.username) | 
                (User.email == user_data.email)
            ).first()
            
            if existing_user:
                return None
            
            # 创建新用户
            # bcrypt限制：密码不能超过72字节，自动截断
            password_bytes = user_data.password.encode('utf-8')[:72]
            password_truncated = password_bytes.decode('utf-8', errors='ignore')
            hashed_password = pwd_context.hash(password_truncated)
            db_user = User(
                username=user_data.username,
                email=user_data.email,
                hashed_password=hashed_password
            )
            
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
            return db_user
            
        except IntegrityError:
            db.rollback()
            return None
        finally:
            self.close_db(db)
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """验证用户"""
        db = self.get_db()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user:
                # bcrypt限制：密码不能超过72字节，自动截断
                password_bytes = password.encode('utf-8')[:72]
                password_truncated = password_bytes.decode('utf-8', errors='ignore')
                if pwd_context.verify(password_truncated, user.hashed_password):
                    return user
            return None
        finally:
            self.close_db(db)
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """根据ID获取用户"""
        db = self.get_db()
        try:
            return db.query(User).filter(User.id == user_id).first()
        finally:
            self.close_db(db)
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        db = self.get_db()
        try:
            return db.query(User).filter(User.username == username).first()
        finally:
            self.close_db(db)
    
    # API密钥管理
    def generate_api_key(self) -> str:
        """生成API密钥"""
        chars = string.ascii_lowercase + string.digits
        random_part = ''.join(secrets.choice(chars) for _ in range(32))
        return f"sk-{random_part}"
    
    def create_api_key(self, user_id: int, key_data: APIKeyCreate) -> Optional[UserAPIKey]:
        """为用户创建API密钥"""
        db = self.get_db()
        try:
            api_key = self.generate_api_key()
            
            db_api_key = UserAPIKey(
                user_id=user_id,
                api_key=api_key,
                name=key_data.name,
                description=key_data.description,
                model=key_data.model
            )
            
            db.add(db_api_key)
            db.commit()
            db.refresh(db_api_key)
            return db_api_key
            
        except IntegrityError:
            db.rollback()
            return None
        finally:
            self.close_db(db)
    
    def get_user_api_keys(self, user_id: int) -> List[UserAPIKey]:
        """获取用户的所有API密钥"""
        db = self.get_db()
        try:
            return db.query(UserAPIKey).filter(UserAPIKey.user_id == user_id).all()
        finally:
            self.close_db(db)
    
    def get_api_key_by_key(self, api_key: str) -> Optional[UserAPIKey]:
        """根据API密钥获取记录"""
        db = self.get_db()
        try:
            return db.query(UserAPIKey).filter(
                UserAPIKey.api_key == api_key,
                UserAPIKey.is_active == True
            ).first()
        finally:
            self.close_db(db)
    
    def update_api_key_usage(self, api_key: str):
        """更新API密钥使用记录"""
        db = self.get_db()
        try:
            db_api_key = db.query(UserAPIKey).filter(UserAPIKey.api_key == api_key).first()
            if db_api_key:
                db_api_key.last_used_at = datetime.utcnow()
                db_api_key.usage_count += 1
                db.commit()
        finally:
            self.close_db(db)
    
    def delete_api_key(self, user_id: int, api_key_id: int) -> bool:
        """删除API密钥"""
        db = self.get_db()
        try:
            db_api_key = db.query(UserAPIKey).filter(
                UserAPIKey.id == api_key_id,
                UserAPIKey.user_id == user_id
            ).first()
            
            if db_api_key:
                db.delete(db_api_key)
                db.commit()
                return True
            return False
        finally:
            self.close_db(db)
    
    # 使用日志
    def log_usage(self, user_id: int, api_key_id: int, endpoint: str, method: str, 
                  status_code: int, prompt_tokens: int = 0, completion_tokens: int = 0,
                  model: str = None):
        """记录使用日志"""
        db = self.get_db()
        try:
            usage_log = UsageLog(
                user_id=user_id,
                api_key_id=api_key_id,
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                model=model
            )
            
            db.add(usage_log)
            db.commit()
        finally:
            self.close_db(db)
    
    def get_user_usage_stats(self, user_id: int) -> UsageStats:
        """获取用户使用统计"""
        db = self.get_db()
        try:
            # 总统计
            total_logs = db.query(UsageLog).filter(UsageLog.user_id == user_id)
            total_requests = total_logs.count()
            total_tokens = sum(log.total_tokens for log in total_logs.all())
            prompt_tokens = sum(log.prompt_tokens for log in total_logs.all())
            completion_tokens = sum(log.completion_tokens for log in total_logs.all())
            
            # 今日统计
            today = datetime.utcnow().date()
            today_logs = total_logs.filter(
                UsageLog.created_at >= datetime.combine(today, datetime.min.time())
            )
            today_requests = today_logs.count()
            today_tokens = sum(log.total_tokens for log in today_logs.all())
            
            return UsageStats(
                total_requests=total_requests,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                today_requests=today_requests,
                today_tokens=today_tokens
            )
        finally:
            self.close_db(db)
    
    def get_user_usage_logs(self, user_id: int, limit: int = 100) -> List[UsageLog]:
        """获取用户使用日志"""
        db = self.get_db()
        try:
            return db.query(UsageLog).filter(
                UsageLog.user_id == user_id
            ).order_by(UsageLog.created_at.desc()).limit(limit).all()
        finally:
            self.close_db(db)

# 全局数据库管理器实例
_db_manager: Optional[DatabaseManager] = None

def get_database_manager() -> DatabaseManager:
    """获取全局数据库管理器实例"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
