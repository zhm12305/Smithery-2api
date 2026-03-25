"""
管理员API

管理所有用户、API密钥和系统统计
"""

import logging
import asyncio
import os
import signal
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ...models.user_models import (
    User, UserAPIKey, UsageLog,
    UserResponse, APIKeyResponse, UsageLogResponse, APIKeyUpdate
)
from ...services.database import get_database_manager
from ...services.auth_service import get_current_active_user
from ...config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["管理员"])

# 自动重启开关（已禁用，使用配置热重载代替）
# 说明：自动重启在容器中会导致服务关闭而不会重新启动
# 现在使用 reload_settings() 实现配置热重载，无需重启服务
AUTO_RESTART_ON_TOKEN_UPDATE = os.getenv("AUTO_RESTART_ON_TOKEN_UPDATE", "false").lower() == "true"
RESTART_DELAY_SECONDS = float(os.getenv("TOKEN_UPDATE_RESTART_DELAY", "1"))


async def _schedule_app_restart():
    """延迟触发应用重启，确保响应返回给前端。"""
    await asyncio.sleep(RESTART_DELAY_SECONDS)
    logger.warning("🔁 Smithery token 更新完成，自动重启服务以立即生效")
    pid = os.getpid()
    try:
        if hasattr(signal, "SIGTERM"):
            os.kill(pid, signal.SIGTERM)
        else:
            os._exit(0)
    except Exception as exc:
        logger.error(f"自动重启失败: {exc}")
# 依赖注入
def get_db_manager():
    return get_database_manager()

def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:
    """获取当前管理员用户"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="需要管理员权限"
        )
    return current_user

@router.get("/users", response_model=List[UserResponse], summary="获取所有用户")
async def get_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """获取所有用户列表"""
    db = db_manager.get_db()
    try:
        users = db.query(User).offset(skip).limit(limit).all()
        return [UserResponse.from_orm(user) for user in users]
    finally:
        db_manager.close_db(db)

@router.get("/users/{user_id}", response_model=UserResponse, summary="获取用户详情")
async def get_user_detail(
    user_id: int,
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """获取指定用户的详细信息"""
    user = db_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )
    return UserResponse.from_orm(user)

@router.put("/users/{user_id}/status", summary="更新用户状态")
async def update_user_status(
    user_id: int,
    is_active: bool,
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """激活或禁用用户"""
    db = db_manager.get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=404,
                detail="用户不存在"
            )

        user.is_active = is_active
        db.commit()

        return {
            "message": f"用户已{'激活' if is_active else '禁用'}",
            "user_id": user_id,
            "is_active": is_active
        }
    finally:
        db_manager.close_db(db)

@router.delete("/users/{user_id}", summary="删除用户")
async def delete_user(
    user_id: int,
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """删除用户及其所有相关数据"""
    db = db_manager.get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=404,
                detail="用户不存在"
            )

        # 防止删除管理员账户
        if user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="不能删除管理员账户"
            )

        # 防止删除当前登录的管理员
        if user.id == admin_user.id:
            raise HTTPException(
                status_code=403,
                detail="不能删除当前登录的账户"
            )

        username = user.username

        # 删除用户的所有API密钥
        db.query(UserAPIKey).filter(UserAPIKey.user_id == user_id).delete()

        # 删除用户的所有使用记录
        db.query(UsageLog).filter(UsageLog.user_id == user_id).delete()

        # 删除用户
        db.delete(user)
        db.commit()

        return {
            "message": f"用户 '{username}' 及其所有相关数据已删除",
            "user_id": user_id,
            "username": username
        }
    finally:
        db_manager.close_db(db)

@router.get("/users/{user_id}/api-keys", response_model=List[APIKeyResponse], summary="获取用户的API密钥")
async def get_user_api_keys(
    user_id: int,
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """获取指定用户的所有API密钥"""
    api_keys = db_manager.get_user_api_keys(user_id)
    return [APIKeyResponse.from_orm(key) for key in api_keys]

@router.put("/api-keys/{api_key_id}", summary="更新API密钥状态")
async def update_api_key_status(
    api_key_id: int,
    update_data: APIKeyUpdate,
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """更新API密钥的状态或信息"""
    db = db_manager.get_db()
    try:
        api_key = db.query(UserAPIKey).filter(UserAPIKey.id == api_key_id).first()
        if not api_key:
            raise HTTPException(
                status_code=404,
                detail="API密钥不存在"
            )
        
        if update_data.name is not None:
            api_key.name = update_data.name
        if update_data.description is not None:
            api_key.description = update_data.description
        if update_data.is_active is not None:
            api_key.is_active = update_data.is_active
        
        db.commit()
        
        return {
            "message": "API密钥更新成功",
            "api_key_id": api_key_id
        }
    finally:
        db_manager.close_db(db)

@router.delete("/api-keys/{api_key_id}", summary="删除API密钥")
async def delete_api_key(
    api_key_id: int,
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """删除指定的API密钥"""
    db = db_manager.get_db()
    try:
        api_key = db.query(UserAPIKey).filter(UserAPIKey.id == api_key_id).first()
        if not api_key:
            raise HTTPException(
                status_code=404,
                detail="API密钥不存在"
            )
        
        user_id = api_key.user_id
        db.delete(api_key)
        db.commit()
        
        return {
            "message": "API密钥删除成功",
            "api_key_id": api_key_id,
            "user_id": user_id
        }
    finally:
        db_manager.close_db(db)

@router.get("/usage/stats", summary="获取系统使用统计")
async def get_system_stats(
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """获取系统整体使用统计"""
    db = db_manager.get_db()
    try:
        # 用户统计
        total_users = db.query(User).count()
        active_users = db.query(User).filter(User.is_active == True).count()
        
        # API密钥统计
        total_api_keys = db.query(UserAPIKey).count()
        active_api_keys = db.query(UserAPIKey).filter(UserAPIKey.is_active == True).count()
        
        # 使用统计
        total_requests = db.query(UsageLog).count()
        total_tokens = db.query(UsageLog).with_entities(
            func.sum(UsageLog.total_tokens)
        ).scalar() or 0
        
        # 今日统计
        from datetime import datetime, date
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        
        today_requests = db.query(UsageLog).filter(
            UsageLog.created_at >= today_start
        ).count()
        
        today_tokens = db.query(UsageLog).filter(
            UsageLog.created_at >= today_start
        ).with_entities(
            func.sum(UsageLog.total_tokens)
        ).scalar() or 0
        
        return {
            "users": {
                "total": total_users,
                "active": active_users,
                "inactive": total_users - active_users
            },
            "api_keys": {
                "total": total_api_keys,
                "active": active_api_keys,
                "inactive": total_api_keys - active_api_keys
            },
            "usage": {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "today_requests": today_requests,
                "today_tokens": today_tokens
            }
        }
    finally:
        db_manager.close_db(db)

@router.get("/usage/logs", response_model=List[UsageLogResponse], summary="获取使用日志")
async def get_usage_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user_id: Optional[int] = Query(None),
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """获取系统使用日志"""
    db = db_manager.get_db()
    try:
        query = db.query(UsageLog)
        
        if user_id:
            query = query.filter(UsageLog.user_id == user_id)
        
        logs = query.order_by(UsageLog.created_at.desc()).offset(skip).limit(limit).all()
        return [UsageLogResponse.from_orm(log) for log in logs]
    finally:
        db_manager.close_db(db)

@router.get("/api-keys", response_model=List[APIKeyResponse], summary="获取所有API密钥")
async def get_all_api_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user_id: Optional[int] = Query(None),
    admin_user: User = Depends(get_current_admin_user),
    db_manager = Depends(get_db_manager)
):
    """获取所有API密钥"""
    db = db_manager.get_db()
    try:
        query = db.query(UserAPIKey)
        
        if user_id:
            query = query.filter(UserAPIKey.user_id == user_id)
        
        api_keys = query.order_by(UserAPIKey.created_at.desc()).offset(skip).limit(limit).all()
        return [APIKeyResponse.from_orm(key) for key in api_keys]
    finally:
        db_manager.close_db(db)


# ============================================================================
# Token 管理 API
# ============================================================================

from pydantic import BaseModel
import httpx
from pathlib import Path
import re

class SmitheryTokenUpdate(BaseModel):
    """Smithery Token 更新模型"""
    token: str

class SmitheryTokenResponse(BaseModel):
    """Smithery Token 响应模型"""
    current_token: Optional[str] = None
    token_preview: Optional[str] = None
    is_valid: Optional[bool] = None
    last_updated: Optional[str] = None


@router.get("/config/smithery-token", response_model=SmitheryTokenResponse, summary="获取当前 Smithery Token")
async def get_smithery_token(
    admin_user: User = Depends(get_current_admin_user)
):
    """获取当前的 Smithery Token（脱敏显示）"""
    from ...config import settings
    
    current_token = settings.smithery_auth_token
    
    if not current_token:
        return SmitheryTokenResponse(
            current_token=None,
            token_preview="未配置",
            is_valid=False
        )
    
    # 脱敏显示：只显示前50字符和后20字符
    if len(current_token) > 70:
        token_preview = f"{current_token[:50]}...{current_token[-20:]}"
    else:
        token_preview = current_token[:50] + "..."
    
    return SmitheryTokenResponse(
        current_token=current_token,  # 完整 token（管理员可见）
        token_preview=token_preview,
        is_valid=None  # 需要单独验证
    )


@router.post("/config/smithery-token/verify", summary="验证 Smithery Token")
async def verify_smithery_token(
    token_data: SmitheryTokenUpdate,
    admin_user: User = Depends(get_current_admin_user)
):
    """验证 Smithery Token 是否有效"""
    token = token_data.token.strip()
    
    if not token:
        raise HTTPException(status_code=400, detail="Token 不能为空")
    
    import base64, json, time, secrets, string
    
    # ── 第一步：检查 Supabase token 格式和过期时间 ──────────────────────────
    token_email = None
    try:
        raw = token.replace("base64-", "", 1) + "=="
        sess = json.loads(base64.b64decode(raw))
        token_exp = sess.get("expires_at", 0)
        token_email = sess.get("user", {}).get("email", "")
        now = int(time.time())
        if now > token_exp:
            hours_ago = (now - token_exp) // 3600
            return {
                "is_valid": False,
                "message": f"Supabase Token 已过期 {hours_ago} 小时（账号: {token_email}）。"
                           f"请重新从浏览器复制最新 Cookie。",
                "status_code": 401
            }
    except Exception:
        if not token.startswith("base64-"):
            return {
                "is_valid": False,
                "message": "Token 格式无效：应以 'base64-eyJ...' 开头（Supabase session 的 base64 编码）",
                "status_code": 400
            }
    
    # ── 第二步：测试 wos-session 连通性 ─────────────────────────────────────
    if not settings.smithery_wos_session:
        return {
            "is_valid": False,
            "message": "wos-session 未配置，无法调用 Smithery API。"
                       "请从浏览器 Network 请求里复制 wos-session cookie 值并更新 .env。",
            "status_code": 401
        }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            chat_id = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            adjectives = ["loose", "happy", "clever", "swift", "bright"]
            animals = ["rodent", "falcon", "tiger", "dolphin", "eagle"]
            profile_slug = f"{secrets.choice(adjectives)}-{secrets.choice(animals)}-{secrets.token_hex(3)}"
            
            # 用输入的 token + 当前 wos-session 构建 cookie
            CHUNK = 3180
            NAME = "sb-spjawbfpwezjfmicopsl-auth-token"
            if len(token) <= CHUNK:
                cookie_str = f"{NAME}.0={token}; wos-session={settings.smithery_wos_session}"
            else:
                cookie_str = (f"{NAME}.0={token[:CHUNK]}; {NAME}.1={token[CHUNK:]}; "
                              f"wos-session={settings.smithery_wos_session}")
            
            response = await client.post(
                "https://smithery.ai/api/chat",
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie_str,
                    "Origin": "https://smithery.ai",
                    "Referer": "https://smithery.ai/chat",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                },
                json={
                    "messages": [{"id": "verify_msg", "role": "user",
                                  "parts": [{"type": "text", "text": "hi"}]}],
                    "chatId": chat_id,
                    "model": "anthropic/claude-haiku-4.5",
                    "profileSlug": profile_slug,
                    "systemPrompt": "",
                    "timezone": "Asia/Shanghai"
                }
            )
            
            email_hint = f"（账号: {token_email}）" if token_email else ""
            
            if response.status_code == 401:
                return {"is_valid": False,
                        "message": f"认证失败 (401) — wos-session 已过期{email_hint}，"
                                   "请从浏览器重新复制 wos-session 并更新 .env。",
                        "status_code": 401}
            elif response.status_code in [200, 201]:
                return {"is_valid": True,
                        "message": f"Token 验证成功{email_hint}，API 正常响应。",
                        "status_code": response.status_code}
            elif response.status_code == 426:
                return {"is_valid": True,
                        "message": f"Token 有效{email_hint}（Smithery 要求流式连接，属正常响应）",
                        "status_code": 426}
            elif response.status_code == 429:
                return {
                    "is_valid": True,
                    "message": "Token 有效，但请求频率超限 (429 Rate Limited)，请稍后再试",
                    "status_code": 429
                }
            elif response.status_code == 500:
                return {
                    "is_valid": False,
                    "message": "Smithery 服务异常 (500)，Token 可能无效",
                    "status_code": 500
                }
            else:
                return {
                    "is_valid": False,
                    "message": f"未知响应码: {response.status_code}",
                    "status_code": response.status_code
                }
                
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="请求超时，请检查网络连接")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")


@router.post("/config/smithery-token", summary="更新 Smithery Token")
async def update_smithery_token(
    token_data: SmitheryTokenUpdate,
    admin_user: User = Depends(get_current_admin_user)
):
    """
    更新 Smithery Token
    会同时更新：
    1. .env 文件
    2. .env.example 文件
    3. config.py 的默认值
    4. 运行时配置
    """
    token = token_data.token.strip()
    
    if not token:
        raise HTTPException(status_code=400, detail="Token 不能为空")
    
    # 先验证 token 是否有效
    try:
        import time
        import secrets
        import string
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 生成随机chatId和profileSlug
            chat_id = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            adjectives = ["loose", "happy", "clever", "swift", "bright"]
            animals = ["rodent", "falcon", "tiger", "dolphin", "eagle"]
            profile_slug = f"{secrets.choice(adjectives)}-{secrets.choice(animals)}-{secrets.token_hex(3)}"
            
            # 使用新的 Smithery API 请求格式
            response = await client.post(
                "https://smithery.ai/api/chat",
                headers={
                    "Content-Type": "application/json",
                    "Cookie": settings.smithery_cookie,
                    "Origin": "https://smithery.ai",
                    "Referer": "https://smithery.ai/chat",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                },
                json={
                    "messages": [
                        {
                            "id": "update_msg",
                            "role": "user",
                            "parts": [
                                {
                                    "type": "text",
                                    "text": "hi"
                                }
                            ]
                        }
                    ],
                    "chatId": chat_id,
                    "model": "anthropic/claude-haiku-4.5",
                    "profileSlug": profile_slug,
                    "systemPrompt": "",
                    "timezone": "Asia/Shanghai"
                }
            )

            
            if response.status_code == 401:
                raise HTTPException(status_code=400, detail="Token 无效或已过期，请提供有效的 Token")
            elif response.status_code in [426, 429]:
                # 426: Smithery 要求 WebSocket/SSE，Token 已通过认证
                # 429: 请求频率超限，Token 本身有效
                logger.info(f"Token 预验证通过 (HTTP {response.status_code})，继续保存")
                
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="验证超时，请检查网络连接")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token 验证失败: {str(e)}")
    
    # 获取项目根目录
    project_root = Path(__file__).parent.parent.parent.parent.parent
    env_file = project_root / ".env"
    env_example_file = project_root / ".env.example"
    config_file = project_root / "src" / "smithery_proxy" / "config.py"
    
    updated_files = []
    
    # 1. 更新 .env 文件
    try:
        if env_file.exists():
            content = env_file.read_text(encoding='utf-8')
            # 使用正则替换 SMITHERY_AUTH_TOKEN
            if "SMITHERY_AUTH_TOKEN=" in content:
                content = re.sub(
                    r'^SMITHERY_AUTH_TOKEN=.*$',
                    f'SMITHERY_AUTH_TOKEN={token}',
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f'\nSMITHERY_AUTH_TOKEN={token}\n'
            
            env_file.write_text(content, encoding='utf-8')
            updated_files.append(".env")
        else:
            # 创建新的 .env 文件
            env_file.write_text(f'SMITHERY_AUTH_TOKEN={token}\n', encoding='utf-8')
            updated_files.append(".env (新建)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新 .env 文件失败: {str(e)}")
    
    # 2. 更新 .env.example 文件
    try:
        # 使用脱敏的示例 token
        example_token = "base64-YOUR_SMITHERY_AUTH_TOKEN_HERE"
        
        if env_example_file.exists():
            content = env_example_file.read_text(encoding='utf-8')
            if "SMITHERY_AUTH_TOKEN=" in content:
                content = re.sub(
                    r'^SMITHERY_AUTH_TOKEN=.*$',
                    f'SMITHERY_AUTH_TOKEN={example_token}',
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f'\nSMITHERY_AUTH_TOKEN={example_token}\n'
            
            env_example_file.write_text(content, encoding='utf-8')
            updated_files.append(".env.example")
        else:
            # 创建示例配置
            example_content = f"""# Smithery Claude Proxy 配置示例
# 复制此文件为 .env 并填入真实值

# Smithery.ai 认证 Token
# 获取方式：访问 https://smithery.ai/playground，登录后从浏览器 Cookie 中获取
# Cookie 名称：sb-spjawbfpwezjfmicopsl-auth-token.0
SMITHERY_AUTH_TOKEN={example_token}

# 服务配置
HOST=0.0.0.0
PORT=20179
DEBUG=False

# 数据库配置
DATABASE_URL=sqlite:///./users.db

# JWT 配置
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=43200

# Google 搜索 API（可选）
GOOGLE_SEARCH_API_KEY=your-google-api-key
GOOGLE_SEARCH_CX=your-google-cx
"""
            env_example_file.write_text(example_content, encoding='utf-8')
            updated_files.append(".env.example (新建)")
    except Exception as e:
        # 记录失败但不中断
        import logging
        logging.getLogger(__name__).warning(f".env.example 更新失败: {e}")
    
    # 3. ⚠️ 跳过更新 config.py（会触发自动重载导致环境变量丢失）
    # 说明：
    # - config.py 的默认值不重要，只是fallback
    # - .env 文件和环境变量才是实际使用的配置源
    # - 更新 config.py 会触发 uvicorn 重载，重启进程会丢失刚才设置的环境变量
    logger.info("跳过更新 config.py，避免触发自动重载")

    # 4. 先更新环境变量（Pydantic Settings 优先读取环境变量）
    import os
    os.environ["SMITHERY_AUTH_TOKEN"] = token
    logger.info(f"✅ 环境变量已更新: SMITHERY_AUTH_TOKEN")
    
    # 5. 🔥 热重载配置 - 传入新的环境变量值确保生效
    from ...config import reload_settings
    try:
        # 传入新的 token 值，确保能被正确加载
        reload_settings(env_values={"SMITHERY_AUTH_TOKEN": token})
        updated_files.append("✅ 运行时配置已热重载")
        logger.info(f"✅ Token 更新后配置已热重载，立即生效！")
        logger.info(f"新 Token 前50字符: {token[:50]}...")
    except Exception as e:
        logger.error(f"配置热重载失败: {e}")
        # 降级方案：手动更新
        from ...config import settings
        settings.smithery_auth_token = token
        updated_files.append("⚠️ 运行时配置已手动更新")
    
    # 5. 清除 Python 缓存
    try:
        import shutil
        pycache_dirs = list(project_root.glob("**/__pycache__"))
        for pycache_dir in pycache_dirs:
            try:
                shutil.rmtree(pycache_dir)
            except:
                pass
        updated_files.append("Python 缓存已清除")
    except:
        pass
    
    # 6. 检测部署模式并提示
    is_docker = Path("/.dockerenv").exists()
    src_is_mounted = (project_root / "src" / "smithery_proxy" / "api").exists()
    docker_restarted = False
    docker_note = None
    
    if is_docker:
        # Docker 环境，配置已通过热重载立即生效
        docker_note = (
            "✅ 配置已通过热重载立即生效！\n\n"
            "💡 说明：\n"
            "- ✅ .env 文件已更新并重新加载\n"
            "- ✅ 运行时配置已立即生效\n"
            "- ✅ 无需重启容器！\n\n"
            "如果遇到问题，可以手动重启容器：\n"
            "docker-compose restart smithery-claude-proxy"
        )
    else:
        # 非 Docker 环境，配置已立即生效
        docker_note = "✅ 配置已热重载并立即生效！"
    
    response_payload = {
        "message": "Token 更新成功",
        "updated_files": updated_files,
        "token_preview": f"{token[:50]}..." if len(token) > 50 else token,
        "is_docker": is_docker,
        "docker_restarted": docker_restarted,
        "note": docker_note
    }

    if AUTO_RESTART_ON_TOKEN_UPDATE:
        updated_files.append("⏳ 即将自动重启服务")
        try:
            asyncio.create_task(_schedule_app_restart())
        except RuntimeError:
            # 无事件循环时 fallback
            loop = asyncio.get_event_loop()
            loop.create_task(_schedule_app_restart())

    return response_payload


# ─────────────────────────────────────────────────────────────────────────────
# wos-session 管理接口（与 smithery-token 完全对称）
# ─────────────────────────────────────────────────────────────────────────────

class WosSessionUpdate(BaseModel):
    session: str


@router.get("/config/wos-session", summary="获取当前 wos-session")
async def get_wos_session(
    admin_user: User = Depends(get_current_admin_user)
):
    """获取当前配置的 wos-session（脱敏显示）"""
    session = settings.smithery_wos_session or ""
    preview = (session[:30] + "...") if len(session) > 30 else session
    return {
        "current_session": session,
        "session_preview": preview,
        "is_configured": bool(session)
    }


@router.post("/config/wos-session/verify", summary="验证 wos-session 是否有效")
async def verify_wos_session(
    session_data: WosSessionUpdate,
    admin_user: User = Depends(get_current_admin_user)
):
    """验证 wos-session 是否能成功调用 Smithery API"""
    import secrets, string
    session = session_data.session.strip()

    if not session:
        raise HTTPException(status_code=400, detail="wos-session 不能为空")
    if not session.startswith("Fe26.2*"):
        return {
            "is_valid": False,
            "message": "wos-session 格式无效：应以 'Fe26.2*' 开头（Hapi Iron 加密格式）",
            "status_code": 400
        }

    # 用当前 Supabase token + 待测试的 wos-session 组合发请求
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            chat_id = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            adjectives = ["loose", "happy", "clever", "swift", "bright"]
            animals = ["rodent", "falcon", "tiger", "dolphin", "eagle"]
            profile_slug = f"{secrets.choice(adjectives)}-{secrets.choice(animals)}-{secrets.token_hex(3)}"

            CHUNK = 3180
            NAME = "sb-spjawbfpwezjfmicopsl-auth-token"
            token = settings.smithery_auth_token or ""
            if len(token) <= CHUNK:
                cookie_str = f"{NAME}.0={token}; wos-session={session}" if token else f"wos-session={session}"
            else:
                cookie_str = f"{NAME}.0={token[:CHUNK]}; {NAME}.1={token[CHUNK:]}; wos-session={session}"

            response = await client.post(
                "https://smithery.ai/api/chat",
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookie_str,
                    "Origin": "https://smithery.ai",
                    "Referer": "https://smithery.ai/chat",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                },
                json={
                    "messages": [{"id": "verify_session", "role": "user",
                                  "parts": [{"type": "text", "text": "hi"}]}],
                    "chatId": chat_id,
                    "model": "anthropic/claude-haiku-4.5",
                    "profileSlug": profile_slug,
                    "systemPrompt": "",
                    "timezone": "Asia/Shanghai"
                }
            )

            if response.status_code == 401:
                return {"is_valid": False,
                        "message": "wos-session 无效或已过期 (401 Unauthorized)，请从浏览器重新复制。",
                        "status_code": 401}
            elif response.status_code in [200, 201]:
                return {"is_valid": True,
                        "message": "✅ wos-session 验证成功，API 正常响应。",
                        "status_code": response.status_code}
            elif response.status_code == 426:
                return {"is_valid": True,
                        "message": "✅ wos-session 有效（Smithery 要求流式连接，属正常响应）",
                        "status_code": 426}
            elif response.status_code == 429:
                return {"is_valid": True,
                        "message": "✅ wos-session 有效，请求频率超限 (429 Rate Limited)，实际使用不受影响。",
                        "status_code": 429}
            else:
                return {"is_valid": False,
                        "message": f"未知响应码: {response.status_code}",
                        "status_code": response.status_code}

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="请求超时，请检查网络连接")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")


@router.post("/config/wos-session", summary="更新 wos-session")
async def update_wos_session(
    session_data: WosSessionUpdate,
    admin_user: User = Depends(get_current_admin_user)
):
    """更新 wos-session，写入 .env 并热重载配置"""
    import re, os
    session = session_data.session.strip()

    if not session:
        raise HTTPException(status_code=400, detail="wos-session 不能为空")
    if not session.startswith("Fe26.2*"):
        raise HTTPException(status_code=400, detail="wos-session 格式无效，应以 'Fe26.2*' 开头")

    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent.parent.parent
    env_file = project_root / ".env"
    updated_files = []

    # 1. 写入 .env
    try:
        if env_file.exists():
            content = env_file.read_text(encoding='utf-8')
            if "SMITHERY_WOS_SESSION=" in content:
                content = re.sub(
                    r'^SMITHERY_WOS_SESSION=.*$',
                    f'SMITHERY_WOS_SESSION={session}',
                    content,
                    flags=re.MULTILINE
                )
            else:
                content += f'\nSMITHERY_WOS_SESSION={session}\n'
            env_file.write_text(content, encoding='utf-8')
        else:
            env_file.write_text(f'SMITHERY_WOS_SESSION={session}\n', encoding='utf-8')
        updated_files.append(".env")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新 .env 文件失败: {str(e)}")

    # 2. 更新环境变量并热重载
    os.environ["SMITHERY_WOS_SESSION"] = session
    from ...config import reload_settings
    try:
        reload_settings(env_values={"SMITHERY_WOS_SESSION": session})
        updated_files.append("✅ 运行时配置已热重载")
        logger.info("✅ wos-session 更新后配置已热重载，立即生效！")
    except Exception as e:
        logger.error(f"配置热重载失败: {e}")
        settings.smithery_wos_session = session
        updated_files.append("⚠️ 运行时配置已手动更新")

    is_docker = Path("/.dockerenv").exists()
    if is_docker:
        note = (
            "✅ wos-session 已通过热重载立即生效！\n\n"
            "💡 说明：\n"
            "- ✅ .env 文件已更新并重新加载\n"
            "- ✅ 运行时配置已立即生效\n"
            "- ✅ 无需重启容器！\n\n"
            "如果遇到问题，可以手动重启容器：\n"
            "docker-compose restart smithery-claude-proxy"
        )
    else:
        note = "✅ wos-session 已热重载并立即生效！"

    return {
        "message": "wos-session 更新成功",
        "updated_files": updated_files,
        "session_preview": f"{session[:30]}...",
        "is_docker": is_docker,
        "note": note
    }
