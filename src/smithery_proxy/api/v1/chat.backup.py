"""
聊天完成API端点

实现OpenAI兼容的/v1/chat/completions接口。
"""

import logging
import json
import re
from typing import Union, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends, Request, Body
from fastapi.responses import StreamingResponse, Response
from starlette.responses import StreamingResponse as StarletteStreamingResponse

from ...config import Settings, get_settings
from ...models.openai_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamResponse,
)
from ...models.mcp_models import MCPConnectionParams
from ...services.mcp_client import MCPClient, MCPClientError
from ...services.protocol_converter import ProtocolConverter
from ...services.auth_manager import AuthManager, AuthenticationError
from ...services.tool_manager import get_tool_manager, ToolManager
from ...services.mcp_playground_client import MCPPlaygroundClient
from ...services.unified_prompt_manager import UnifiedPromptManager
from ...models.tool_models import ToolConfig, ToolCall, ToolCallResult
from ...models.mcp_playground_models import OpenAITool

logger = logging.getLogger(__name__)

def get_vision_system_prompt() -> str:
    """获取统一的视觉能力系统提示词"""
    return """You are Claude 4, a helpful AI assistant with powerful native capabilities and access to additional tools when needed.

🖼️ **Native Visual Capabilities**: I can directly analyze, describe, and understand images without external tools. I have built-in vision capabilities for:
- Image content analysis and description
- OCR (text recognition from images)
- Object detection and scene understanding
- Color, composition, and style analysis
- Multi-modal conversations combining text and images

🛠️ **Additional Tools**: When users need capabilities beyond image analysis, I have access to tools including web search, code execution, web content fetching, document management, and data analysis.

**Important**: For image analysis tasks, I use my native vision capabilities directly. I only use external tools when users specifically request web search, code execution, or other non-visual tasks."""

def ensure_system_prompt(messages: List) -> List:
    """确保消息列表包含正确的系统提示词，但只在有图片时添加视觉能力描述"""
    from ...models.openai_models import ChatMessage

    # 检查是否包含图片内容
    has_image = False
    for msg in messages:
        if hasattr(msg, 'content') and isinstance(msg.content, list):
            for item in msg.content:
                if isinstance(item, dict) and item.get('type') == 'image_url':
                    has_image = True
                    break
        if has_image:
            break

    # 如果没有图片，保持原有的系统提示词不变
    if not has_image:
        return list(messages)

    # 只有在有图片时才处理系统提示词
    has_system_message = any(msg.role == "system" for msg in messages)

    if not has_system_message:
        # 添加系统提示词到开头
        system_message = ChatMessage(
            role="system",
            content=get_vision_system_prompt()
        )
        return [system_message] + list(messages)
    else:
        # 如果已有系统消息，检查是否包含视觉能力描述
        for i, msg in enumerate(messages):
            if msg.role == "system":
                if "Native Visual Capabilities" not in msg.content:
                    # 用户角色设定优先，视觉能力描述作为补充
                    user_content = msg.content
                    combined_content = f"{user_content}\n\n{get_vision_system_prompt()}"
                    updated_messages = list(messages)
                    updated_messages[i] = ChatMessage(
                        role="system",
                        content=combined_content
                    )
                    return updated_messages
                break

    return list(messages)

router = APIRouter(prefix="/v1", tags=["chat"])


async def get_auth_manager(settings: Settings = Depends(get_settings)) -> AuthManager:
    """获取认证管理器依赖"""
    auth_manager = AuthManager(settings)
    await auth_manager.initialize()
    return auth_manager


async def parse_chat_request(request: Request) -> ChatCompletionRequest:
    """解析聊天请求，完全忽略Content-Type"""
    content_type = request.headers.get("content-type", "")

    try:
        # 读取原始请求体
        body = await request.body()
        body_str = body.decode('utf-8')

        # 记录Content-Type信息（用于调试）
        if not content_type.startswith("application/json"):
            logger.info(f"接收到Content-Type: '{content_type}'，但将尝试解析为JSON")

        # 尝试解析JSON（不管Content-Type是什么）
        try:
            request_data = json.loads(body_str)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"请求体不是有效的JSON格式: {str(e)}"
            )

        # 验证并创建ChatCompletionRequest对象
        try:
            chat_request = ChatCompletionRequest(**request_data)

            # 成功解析后的日志
            logger.info(f"成功解析聊天请求，模型: {chat_request.model}，消息数: {len(chat_request.messages)}")

            return chat_request

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"请求格式无效: {str(e)}"
            )

    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"解析请求失败: {str(e)}"
        )


async def validate_request_auth(request: Request) -> str:
    """验证请求认证"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
        )

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization format. Expected 'Bearer <token>'"
        )

    token = auth_header[7:]  # 移除"Bearer "前缀
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Empty token"
        )

    # 尝试使用新的数据库API密钥系统验证
    try:
        from ...services.database import get_database_manager
        db_manager = get_database_manager()
        api_key_record = db_manager.get_api_key_by_key(token)

        if api_key_record:
            # 更新使用记录
            db_manager.update_api_key_usage(token)
            logger.info(f"数据库API密钥验证成功: {token[:10]}...")
            return token
    except Exception as e:
        logger.debug(f"数据库API密钥验证失败: {e}")

    # 回退到旧的API密钥管理器
    from ...services.api_key_manager import get_api_key_manager
    api_key_manager = get_api_key_manager()

    # 检查格式
    if not api_key_manager.is_valid_format(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key format. Expected format: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        )

    # 验证密钥是否有效
    if not api_key_manager.validate_api_key(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    logger.info(f"API密钥验证成功: {token[:10]}...")
    return token


@router.post(
    "/chat/completions",
    response_model=Union[ChatCompletionResponse, ChatCompletionStreamResponse]
)
async def create_chat_completion(
    http_request: Request,
    settings: Settings = Depends(get_settings),
    auth_manager: AuthManager = Depends(get_auth_manager)
):
    logger.info("🚀 === 开始处理create_chat_completion请求 ===")

    # 检查请求体大小
    try:
        body = await http_request.body()
        body_size = len(body)
        logger.info(f"🔍 原始HTTP请求体长度: {body_size} 字节 ({body_size/1024:.1f} KB)")

        if body_size > 1024 * 1024:  # 1MB
            logger.warning(f"⚠️ 请求体过大: {body_size / 1024 / 1024:.2f} MB")

        # 检查是否有大的 base64 图片
        try:
            request_data = json.loads(body.decode('utf-8'))
            for i, msg in enumerate(request_data.get('messages', [])):
                if isinstance(msg.get('content'), list):
                    for item in msg['content']:
                        if item.get('type') == 'image_url':
                            image_url = item.get('image_url', {}).get('url', '')
                            if image_url.startswith('data:image'):
                                base64_size = len(image_url)
                                logger.info(f"🔍 消息{i}包含base64图片: {base64_size} 字符 ({base64_size/1024:.1f} KB)")
                                if base64_size > 500000:  # 500KB
                                    logger.warning(f"⚠️ base64图片过大: {base64_size/1024:.1f} KB，可能导致413错误")
        except:
            pass

    except Exception as e:
        logger.error(f"❌ 检查请求体大小失败: {e}")
    """
    创建聊天完成 - 支持多种Content-Type

    兼容OpenAI的/v1/chat/completions接口，支持流式和非流式响应。
    """

    # 添加原始HTTP请求调试
    try:
        body = await http_request.body()
        body_str = body.decode('utf-8')
        logger.info(f"🔍 原始HTTP请求体长度: {len(body_str)}")
        logger.info(f"🔍 原始HTTP请求体前500字符: {body_str[:500]}...")

        # 尝试解析JSON看看是否包含图片信息
        import json
        try:
            request_json = json.loads(body_str)
            if 'messages' in request_json:
                logger.info(f"🔍 原始JSON消息数: {len(request_json['messages'])}")
                for i, msg in enumerate(request_json['messages']):
                    logger.info(f"🔍 原始JSON消息 {i}: {msg}")
        except Exception as json_e:
            logger.info(f"🔍 原始JSON解析失败: {json_e}")
    except Exception as e:
        logger.info(f"🔍 原始请求体读取失败: {e}")

    # 手动验证认证
    auth_token = await validate_request_auth(http_request)

    # 解析请求（支持多种Content-Type）
    request = await parse_chat_request(http_request)

    # 先尝试修复空消息，再进行验证
    for i, message in enumerate(request.messages):
        # 检查消息内容是否为空（支持多模态格式）
        is_empty = False

        if not message.content:
            is_empty = True
        elif isinstance(message.content, str):
            # 字符串格式
            if message.content.strip() == "":
                is_empty = True
        elif isinstance(message.content, list):
            # 多模态格式 - 检查是否有实际内容
            has_content = False
            for item in message.content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text", "").strip():
                        has_content = True
                        break
                    elif item.get("type") in ["image", "image_url"]:
                        has_content = True
                        break
            is_empty = not has_content

        if is_empty:
            if message.role == "user":
                message.content = "..."  # 用户空消息用省略号
            elif message.role == "assistant":
                message.content = "好的。"  # 助手空消息用简单回复
            else:  # system
                message.content = "请继续对话。"  # 系统空消息用提示
            logger.info(f"第{i+1}条消息内容为空，已自动填充: '{message.content}'")

    # 验证请求格式（现在空消息已经被修复）
    validation_error = ProtocolConverter.validate_openai_request(request)
    if validation_error:
        raise HTTPException(
            status_code=400,
            detail=validation_error
        )

    # 记录原始请求是否包含tools参数（在自动添加之前）
    original_has_tools = bool(request.tools)
    logger.info(f"🎯 原始请求包含tools参数: {original_has_tools}")

    # 添加ChatBox原始请求调试
    logger.info(f"🔍 ChatBox原始请求调试 - 消息数: {len(request.messages)}")
    for i, msg in enumerate(request.messages):
        logger.info(f"🔍 ChatBox请求消息 {i}: role={msg.role}, content类型={type(msg.content)}")
        if isinstance(msg.content, list):
            logger.info(f"🔍 ChatBox请求消息 {i} 多模态内容: {msg.content}")
            for j, item in enumerate(msg.content):
                logger.info(f"🔍 ChatBox请求消息 {i} 项目 {j}: {item}")
        elif isinstance(msg.content, str):
            logger.info(f"🔍 ChatBox请求消息 {i} 文本内容: {msg.content[:100]}...")
        else:
            logger.info(f"🔍 ChatBox请求消息 {i} 其他类型内容: {msg.content}")

        # 检查消息对象的所有属性
        try:
            msg_dict = msg.dict() if hasattr(msg, 'dict') else vars(msg)
            logger.info(f"🔍 ChatBox请求消息 {i} 所有属性: {list(msg_dict.keys())}")
            for key, value in msg_dict.items():
                if key != 'content':
                    if isinstance(value, (str, int, float, bool, type(None))):
                        logger.info(f"🔍 ChatBox请求消息 {i} {key}: {value}")
                    else:
                        logger.info(f"🔍 ChatBox请求消息 {i} {key} (类型{type(value)}): {str(value)[:200]}...")
        except Exception as e:
            logger.info(f"🔍 ChatBox请求消息 {i} 属性检查失败: {e}")

    # 在处理系统提示词之前，保存原始的用户系统提示词
    original_user_system_prompt = ""
    for msg in request.messages:
        if msg.role == "system":
            original_user_system_prompt = msg.content
            break
    logger.info(f"🔍 保存原始用户系统提示词: {original_user_system_prompt}")

    # 检查最后一条用户消息是否是角色切换请求
    last_user_msg = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    role_switch_detected = False
    if last_user_msg and "Write your next reply from the point of view of User" in last_user_msg:
        logger.info("🔄 检测到角色切换请求，将修改系统提示词")
        role_switch_detected = True

    # 确保所有请求都有正确的系统提示词
    logger.info("🔧 确保系统提示词包含视觉能力描述")
    request.messages = ensure_system_prompt(request.messages)

    # 如果检测到角色切换，修改系统提示词
    if role_switch_detected:
        for msg in request.messages:
            if msg.role == "system":
                msg.content = "You are now writing from the User's perspective in this roleplay conversation. Write naturally as the User character based on the conversation history. Use internet RP style and be authentic to the User's established personality and speaking patterns from the previous messages."
                logger.info("🔄 已修改系统提示词以支持角色切换")
                break

    logger.info(f"🔧 系统提示词处理完成，消息数: {len(request.messages)}")

    # 检查是否启用工具功能并需要工具调用
    tool_manager = None
    mcp_client = None

    if settings.tools_enabled:
        # 初始化 MCP 客户端（如果启用）
        if settings.enable_mcp_tools and settings.smithery_auth_token:
            try:
                mcp_client = MCPPlaygroundClient(settings)
                await mcp_client.initialize()
                logger.info("MCP 客户端初始化成功")
            except Exception as e:
                logger.warning(f"MCP 客户端初始化失败: {e}")
                mcp_client = None

        # 创建工具配置
        tool_config = ToolConfig(
            google_search_api_key=settings.google_search_api_key,
            google_search_cx=settings.google_search_cx,
            code_execution_enabled=settings.code_execution_enabled,
            code_execution_timeout=settings.code_execution_timeout,
            web_fetch_timeout=settings.web_fetch_timeout,
            max_search_results=settings.max_search_results,
            smithery_auth_token=settings.smithery_auth_token,
            smithery_url=settings.smithery_url,
            api_timeout=getattr(settings, 'api_timeout', 60),
            image_analysis_enabled=getattr(settings, 'image_analysis_enabled', True),
            image_analysis_timeout=getattr(settings, 'image_analysis_timeout', 60),
            max_image_size=getattr(settings, 'max_image_size', 10485760),
            supported_image_formats=getattr(settings, 'supported_image_formats', ["jpeg", "jpg", "png", "gif", "webp", "bmp"])
        )

        # 获取工具管理器（传入 MCP 客户端）
        tool_manager = get_tool_manager(tool_config, mcp_client)

        # 检查消息中是否包含图片内容
        has_image_content = False
        for msg in request.messages:
            if msg.role == "user":
                try:
                    from ...utils.image_detector import ImageDetector
                    if ImageDetector.has_images(msg.content):
                        has_image_content = True
                        logger.info(f"检测到用户消息中包含图片内容")
                        break
                except Exception as e:
                    logger.warning(f"图片检测失败: {e}")

        # 检查是否需要工具调用 - 分离工具定义和工具执行逻辑
        # 注意：即使请求已包含工具定义，也需要检测是否需要执行工具
        should_add_tools = False

        # 提取所有用户消息文本用于关键词检测 - 过滤用户ID元数据
        messages_text = ""
        for msg in request.messages:
            if msg.role == "user":
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    content = ""
                    for item in msg.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            content += item.get("text", "") + " "
                else:
                    content = ""

                # 过滤掉用户ID元数据
                import re
                user_id_pattern = r'\[User ID: \d+, Nickname: [^\]]+\]\s*'
                content = re.sub(user_id_pattern, '', content, flags=re.IGNORECASE).strip()
                messages_text += content.lower() + " "

        logger.info(f"🔍 提取的用户消息文本: {messages_text[:200]}...")

        # 首先检查是否包含Cursor IDE/Cline上下文标签，如果有则跳过所有工具
        cursor_patterns = [
            r"<user_info>",
            r"<rules>",
            r"<project_layout>",
            r"<user_query>",
            r"<task>",
            r"<environment_details>",
            r"# VSCode Visible Files",
            r"# VSCode Open Tabs",
            r"# Current Working Directory",
            r"# Current Mode"
        ]

        has_cursor_context = any(re.search(pattern, messages_text) for pattern in cursor_patterns)
        if has_cursor_context:
            logger.info("🚫 检测到Cursor IDE上下文，跳过所有工具")
            has_tool_keywords = False
        else:
            # 检查是否包含工具相关关键词
            tool_keywords = [
                "搜索", "search", "查找", "find", "寻找",
                "网页", "webpage", "网站", "website", "url", "获取",
                "代码", "code", "执行", "run", "计算", "calculate", "python",
                "文档", "document", "创建", "create", "保存", "save",
                "分析", "analyze", "数据", "data", "统计", "statistics", "平均", "mean", "最高", "最低"
            ]

            has_tool_keywords = any(keyword in messages_text for keyword in tool_keywords)
            logger.info(f"🔍 检测到工具关键词: {has_tool_keywords}")

        # 决定是否需要添加工具
        if not request.tools:
            # 如果请求没有工具定义，检查是否需要添加
            if has_tool_keywords or has_image_content:
                should_add_tools = True
                logger.info(f"🔧 请求无工具定义，但检测到需要工具，将自动添加")
        else:
            # 如果请求已有工具定义，记录但不重复添加
            logger.info(f"🔧 请求已包含工具定义，工具数量: {len(request.tools)}")

        if has_image_content:
            logger.info(f"🖼️ 检测到图片分析请求，启用图片分析工具")

        if should_add_tools:
            try:
                # 获取所有可用工具（包括 MCP 工具）
                available_tools = await tool_manager.get_all_available_tools()
                request.tools = [tool.model_dump() for tool in available_tools]
                logger.info(f"自动添加 {len(request.tools)} 个工具到请求中（包括MCP工具）")
            except Exception as e:
                logger.warning(f"获取MCP工具失败，使用内置工具: {e}")
                # 回退到仅使用内置工具
                request.tools = [tool.model_dump() for tool in tool_manager.get_available_tools()]
                logger.info(f"自动添加 {len(request.tools)} 个内置工具到请求中")

    # 创建MCP连接参数
    connection_params = MCPConnectionParams(
        server_url=settings.smithery_url,
        api_key=auth_token,  # 使用请求中的token
        timeout=settings.mcp_timeout,
        retry_attempts=settings.mcp_retry_attempts,
        headers=await auth_manager.get_auth_header()
    )
    
    try:
        # 创建MCP客户端（不进行连接，只用于Smithery API调用）
        mcp_client = MCPClient(settings)
        # 设置连接参数但不连接
        await mcp_client.initialize(connection_params)

        if request.stream:
            # 流式响应
            return await _handle_stream_response(
                mcp_client, request, tool_manager, original_user_system_prompt, auth_token
            )
        else:
            # 非流式响应
            return await _handle_normal_response(
                mcp_client, request, auth_token, tool_manager, original_has_tools, original_user_system_prompt
            )
                
    except MCPClientError as e:
        logger.error(f"MCP客户端错误: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"MCP服务器错误: {str(e)}"
        )
    except AuthenticationError as e:
        logger.error(f"认证错误: {e}")
        raise HTTPException(
            status_code=401,
            detail=f"认证失败: {str(e)}"
        )
    except Exception as e:
        logger.error(f"处理请求时发生未知错误: {e}")
        raise HTTPException(
            status_code=500,
            detail="内部服务器错误"
        )


async def _handle_normal_response(
    mcp_client,
    openai_request: ChatCompletionRequest,
    auth_token: str,
    tool_manager: ToolManager = None,
    original_has_tools: bool = None,
    original_user_system_prompt: str = ""
) -> ChatCompletionResponse:
    """处理非流式响应"""

    # 检查是否需要工具调用 - 修复逻辑
    # 不仅检查工具定义，还要检查是否真的需要执行工具
    if tool_manager:
        # 检查用户消息是否包含需要工具的关键词
        last_message = openai_request.messages[-1] if openai_request.messages else None
        if last_message and last_message.role == "user":
            user_content = str(last_message.content or "").lower()
            logger.info(f"🔍 检测工具关键词的用户内容: {user_content[:100]}...")

            # 搜索关键词检测
            search_keywords = ["搜索", "search", "查找", "find", "寻找", "搜下", "搜个", "搜一搜", "搜一下"]
            has_search_request = any(keyword in user_content for keyword in search_keywords)
            logger.info(f"🔍 搜索关键词检测结果: {has_search_request}, 匹配的关键词: {[kw for kw in search_keywords if kw in user_content]}")

            # 其他工具关键词检测
            tool_keywords = [
                "网页", "webpage", "网站", "website", "url", "获取",
                "代码", "code", "执行", "run", "计算", "calculate", "python",
                "文档", "document", "创建", "create", "保存", "save",
                "分析", "analyze", "数据", "data", "统计", "statistics"
            ]
            has_tool_request = any(keyword in user_content for keyword in tool_keywords)

            logger.info(f"🔍 工具调用检测 - 搜索请求: {has_search_request}, 其他工具请求: {has_tool_request}")

            # 如果检测到需要工具调用，执行工具调用处理
            if has_search_request or has_tool_request or openai_request.tools:
                logger.info(f"🔧 执行工具调用处理流程")

                # 检测AstrBot工具并设置调用策略
                if openai_request.tools:
                    tool_detection_result = detect_astrbot_tools(openai_request)
                    # 将检测结果传递给工具管理器，用于智能调用决策
                    tool_manager.set_detected_astrbot_tools(tool_detection_result)

                return await _handle_tool_calling_response(
                    mcp_client, openai_request, auth_token, tool_manager, original_has_tools, original_user_system_prompt
                )

    # 转换为简单的消息格式（系统提示词已在主函数中统一处理）
    messages = []

    # 添加原始消息（保持原始格式，让mcp_client处理）并清理工具错误信息
    for msg in openai_request.messages:
        content = msg.content
        # 清理历史消息中的工具错误信息
        if isinstance(content, str):
            # 移除工具错误前缀
            tool_error_patterns = [
                r"没有找到相关工具结果。\s*",
                r"工具.*?执行结果：.*?\n\n",
                r"Error: Tool.*?not found\s*",
                r"请使用Cursor IDE的原生能力.*?\n\n"
            ]
            for pattern in tool_error_patterns:
                content = re.sub(pattern, "", content, flags=re.IGNORECASE | re.DOTALL)
            content = content.strip()

        messages.append({
            "role": msg.role,
            "content": content
        })

    # 调用Smithery.ai Claude API
    logger.info("📞 即将调用 mcp_client.call_smithery_claude")
    claude_response = await mcp_client.call_smithery_claude(messages, openai_request.model)
    logger.info(f"📞 call_smithery_claude 返回结果: '{claude_response}' (类型: {type(claude_response)})")

    # 创建OpenAI格式的响应
    from ...models.openai_models import ChatMessage, ChatCompletionChoice, ChatCompletionUsage
    import time
    from uuid import uuid4

    logger.info(f"🔧 即将创建 ChatMessage，content: '{claude_response}' (类型: {type(claude_response)})")

    choice = ChatCompletionChoice(
        index=0,
        message=ChatMessage(
            role="assistant",
            content=claude_response
        ),
        finish_reason="stop"
    )

    logger.info("🔧 ChatCompletionChoice 创建成功")

    # 更准确的token使用量估算
    def estimate_tokens(text: str) -> int:
        """估算文本的token数量 - 改进版本"""
        if not text:
            return 0
        # 更准确的估算：中文字符按1个token计算，英文单词按0.75个token计算
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        english_words = len([w for w in text.split() if any(c.isalpha() for c in w)])
        other_chars = len(text) - chinese_chars - sum(len(w) for w in text.split() if any(c.isalpha() for c in w))

        # 估算公式：中文字符*1 + 英文单词*0.75 + 其他字符*0.5
        estimated = chinese_chars + int(english_words * 0.75) + int(other_chars * 0.5)
        return max(estimated, len(text.split()))  # 至少等于单词数

    logger.info("🔧 开始计算 token 使用量")

    # 安全地计算 prompt tokens，处理多模态内容
    prompt_tokens = 0
    for i, msg in enumerate(openai_request.messages):
        logger.info(f"🔧 处理消息 {i}: content 类型 {type(msg.content)}")
        if isinstance(msg.content, str):
            tokens = estimate_tokens(msg.content)
            logger.info(f"🔧 消息 {i} (字符串): {tokens} tokens")
            prompt_tokens += tokens
        elif isinstance(msg.content, list):
            # 多模态内容，只计算文本部分的 tokens
            text_content = ""
            for item in msg.content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_content += item.get("text", "")
            tokens = estimate_tokens(text_content)
            logger.info(f"🔧 消息 {i} (多模态): {tokens} tokens")
            prompt_tokens += tokens
        else:
            logger.warning(f"🔧 消息 {i}: 未知内容类型 {type(msg.content)}")

    completion_tokens = estimate_tokens(claude_response)
    logger.info(f"🔧 Token 计算完成: prompt={prompt_tokens}, completion={completion_tokens}")

    usage = ChatCompletionUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens
    )

    response = ChatCompletionResponse(
        id=f"chatcmpl-{uuid4().hex[:29]}",
        created=int(time.time()),
        model=openai_request.model,
        choices=[choice],
        usage=usage
    )

    logger.info(f"完成聊天请求: {response.usage.total_tokens} tokens")

    # 记录使用统计
    try:
        from ...services.database import get_database_manager
        db_manager = get_database_manager()

        # 获取API密钥记录以获取用户ID和API密钥ID
        api_key_record = db_manager.get_api_key_by_key(auth_token)
        if api_key_record:
            db_manager.log_usage(
                user_id=api_key_record.user_id,
                api_key_id=api_key_record.id,
                endpoint="/v1/chat/completions",
                method="POST",
                status_code=200,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                model=openai_request.model
            )
            logger.debug(f"记录使用统计: 用户{api_key_record.user_id}, tokens={response.usage.total_tokens}")
    except Exception as e:
        logger.warning(f"记录使用统计失败: {e}")

    # 清理响应中的null值以确保RikkaHub兼容性
    from ...utils.response_cleaner import clean_openai_response

    # 转换为字典格式并清理null值
    response_dict = response.model_dump()
    cleaned_response_dict = clean_openai_response(response_dict)

    # 返回清理后的字典（FastAPI会自动序列化为JSON）
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=cleaned_response_dict,
        headers={"Content-Type": "application/json"}
    )


async def _handle_stream_response(
    mcp_client,
    openai_request: ChatCompletionRequest,
    tool_manager: ToolManager = None,
    original_user_system_prompt: str = "",
    auth_token: str = None
) -> StreamingResponse:
    """处理流式响应"""

    async def generate_stream():
        """生成流式响应数据"""
        try:
            # 转换为简单的消息格式并清理工具错误信息
            messages = []
            for msg in openai_request.messages:
                content = msg.content
                # 清理历史消息中的工具错误信息
                if isinstance(content, str):
                    # 移除工具错误前缀
                    tool_error_patterns = [
                        r"没有找到相关工具结果。\s*",
                        r"工具.*?执行结果：.*?\n\n",
                        r"Error: Tool.*?not found\s*",
                        r"请使用Cursor IDE的原生能力.*?\n\n"
                    ]
                    for pattern in tool_error_patterns:
                        content = re.sub(pattern, "", content, flags=re.IGNORECASE | re.DOTALL)
                    content = content.strip()

                messages.append({
                    "role": msg.role,
                    "content": content
                })

            # 导入必要的模块
            from ...models.openai_models import (
                ChatCompletionStreamResponse,
                ChatCompletionStreamChoice,
                ChatCompletionUsage
            )
            import time
            from uuid import uuid4

            # 检查是否需要包含usage信息
            include_usage = False
            if openai_request.stream_options:
                if isinstance(openai_request.stream_options, dict):
                    include_usage = openai_request.stream_options.get("include_usage", False)
                else:
                    include_usage = openai_request.stream_options.include_usage

            # 用于累计token计数
            prompt_tokens = 0
            completion_tokens = 0

            # 计算prompt tokens
            if include_usage:
                for msg in openai_request.messages:
                    if isinstance(msg.content, str):
                        prompt_tokens += _estimate_tokens(msg.content)
                    elif isinstance(msg.content, list):
                        # 多模态内容，只计算文本部分
                        text_content = ""
                        for item in msg.content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_content += item.get("text", "")
                        prompt_tokens += _estimate_tokens(text_content)

            request_id = f"chatcmpl-{uuid4().hex[:29]}"
            created = int(time.time())

            # 发送开始chunk
            start_chunk = ChatCompletionStreamResponse(
                id=request_id,
                created=created,
                model=openai_request.model,
                choices=[ChatCompletionStreamChoice(
                    index=0,
                    delta={"role": "assistant"},
                    finish_reason=None
                )]
            )
            yield f"data: {start_chunk.model_dump_json()}\n\n"

            # 检查是否需要工具调用（流式版本）- 修复搜索功能
            should_handle_tools = False
            if tool_manager:
                # 检查最后一条用户消息
                last_message = openai_request.messages[-1] if openai_request.messages else None
                if last_message and last_message.role == "user":
                    user_content = last_message.content or ""

                    # 检查是否包含图片或需要工具
                    if isinstance(user_content, list):
                        # 多模态内容，创建工具调用
                        tool_calls = _create_tool_calls_from_multimodal_request(last_message, tool_manager)
                        if tool_calls:
                            should_handle_tools = True
                            logger.info(f"🔧 流式版本：创建了 {len(tool_calls)} 个工具调用")

                            # 执行工具调用并获取结果
                            tool_results = []
                            gemini_analysis = None

                            for tool_call in tool_calls:
                                try:
                                    tool_name = tool_call.function.get("name", "unknown")
                                    logger.info(f"🔧 开始执行工具: {tool_name}")

                                    # 使用 execute_tool_call 方法执行工具调用，添加超时保护
                                    import asyncio
                                    try:
                                        tool_result = await asyncio.wait_for(
                                            tool_manager.execute_tool_call(tool_call),
                                            timeout=180.0  # 3分钟超时
                                        )
                                        logger.info(f"✅ 工具 {tool_name} 执行成功")
                                    except asyncio.TimeoutError:
                                        logger.error(f"❌ 工具 {tool_name} 执行超时")
                                        tool_results.append(f"工具 {tool_name} 执行超时，请稍后重试")
                                        continue

                                    if tool_name == "image_analyzer":
                                        # 保存 Gemini 的分析结果，稍后让 Claude 处理
                                        gemini_analysis = tool_result.content
                                        logger.info(f"🔍 Gemini 分析完成，长度: {len(gemini_analysis)} 字符")
                                        logger.info(f"🔍 Gemini 原始内容前200字符: {gemini_analysis[:200]}...")
                                    else:
                                        tool_results.append(f"工具 {tool_name} 执行结果：{tool_result.content}")

                                except Exception as e:
                                    logger.error(f"❌ 工具 {tool_name} 执行异常: {type(e).__name__}: {e}")
                                    import traceback
                                    logger.error(f"❌ 详细错误信息: {traceback.format_exc()}")
                                    tool_results.append(f"工具 {tool_name} 执行失败：{str(e)}")

                            # 如果有 Gemini 图片分析结果，让 Claude 根据系统提示词重新生成回答
                            if gemini_analysis:
                                logger.info("🤖 开始 Claude 二次处理，结合系统提示词生成最终回答")

                                # 构建给 Claude 的消息，包含原始用户请求和 Gemini 分析结果
                                claude_messages = []

                                # 添加系统提示词到 Claude 消息中
                                for msg in openai_request.messages:
                                    if msg.role == "system":
                                        claude_messages.append({
                                            "role": "system",
                                            "content": msg.content
                                        })
                                        break

                                # 提取用户的文本请求 - 只提取最新消息并过滤用户ID元数据
                                user_text = ""
                                if isinstance(last_message.content, list):
                                    for item in last_message.content:
                                        if item.get("type") == "text":
                                            user_text = item.get("text", "")
                                            break
                                else:
                                    user_text = str(last_message.content or "")

                                # 过滤掉用户ID元数据，只保留真实的用户请求
                                import re
                                user_id_pattern = r'\[User ID: \d+, Nickname: [^\]]+\]\s*'
                                user_text = re.sub(user_id_pattern, '', user_text, flags=re.IGNORECASE).strip()

                                # 如果过滤后为空，使用默认文本
                                if not user_text:
                                    user_text = "请分析这张图片"

                                # 构建包含 Gemini 分析结果的用户消息
                                combined_message = f"用户请求: {user_text}\n\n图片分析结果: {gemini_analysis}\n\n请根据以上信息，结合系统提示词的要求，生成合适的回答。"

                                claude_messages.append({
                                    "role": "user",
                                    "content": combined_message
                                })

                                logger.info(f"🔍 发送给 Claude 的消息长度: {len(combined_message)} 字符")

                                # 调用 Claude 进行二次处理
                                try:
                                    async for text_chunk in mcp_client.call_smithery_claude_stream(claude_messages, openai_request.model):
                                        chunk_obj = ChatCompletionStreamResponse(
                                            id=request_id,
                                            created=created,
                                            model=openai_request.model,
                                            choices=[ChatCompletionStreamChoice(
                                                index=0,
                                                delta={"content": text_chunk},
                                                finish_reason=None
                                            )]
                                        )
                                        yield f"data: {chunk_obj.model_dump_json()}\n\n"
                                except Exception as e:
                                    logger.error(f"❌ Claude 二次处理失败: {e}")
                                    # 如果 Claude 处理失败，输出友好的错误消息，不暴露 Gemini 原始分析
                                    fallback_result = "抱歉，我在处理这张图片时遇到了一些技术问题。请稍后再试，或者尝试上传其他图片。"
                                    for char in fallback_result:
                                        chunk_obj = ChatCompletionStreamResponse(
                                            id=request_id,
                                            created=created,
                                            model=openai_request.model,
                                            choices=[ChatCompletionStreamChoice(
                                                index=0,
                                                delta={"content": char},
                                                finish_reason=None
                                            )]
                                        )
                                        yield f"data: {chunk_obj.model_dump_json()}\n\n"
                            else:
                                # 没有图片分析，处理其他工具结果
                                if tool_results:
                                    combined_result = "\n\n".join(tool_results)

                                    # 将工具结果发送给AI进行智能处理
                                    logger.info("🔧 将工具结果发送给AI进行智能处理")

                                    # 构建包含工具结果的消息
                                    messages_with_tool_results = messages.copy()
                                    messages_with_tool_results.append({
                                        "role": "user",
                                        "content": combined_result
                                    })

                                    # 调用AI处理工具结果
                                    try:
                                        async for text_chunk in mcp_client.call_smithery_claude_stream(messages_with_tool_results, openai_request.model):
                                            chunk_obj = ChatCompletionStreamResponse(
                                                id=request_id,
                                                created=created,
                                                model=openai_request.model,
                                                choices=[ChatCompletionStreamChoice(
                                                    index=0,
                                                    delta={"content": text_chunk},
                                                    finish_reason=None
                                                )]
                                            )
                                            yield f"data: {chunk_obj.model_dump_json()}\n\n"
                                    except Exception as e:
                                        logger.error(f"❌ AI处理工具结果失败: {e}")
                                        # 如果AI处理失败，直接返回工具结果
                                        for char in combined_result:
                                            chunk_obj = ChatCompletionStreamResponse(
                                                id=request_id,
                                                created=created,
                                                model=openai_request.model,
                                                choices=[ChatCompletionStreamChoice(
                                                    index=0,
                                                    delta={"content": char},
                                                    finish_reason=None
                                                )]
                                            )
                                            yield f"data: {chunk_obj.model_dump_json()}\n\n"
                                else:
                                    # 没有工具结果，返回空内容
                                    pass
                    else:
                        # 文本内容，检查搜索和其他工具关键词
                        user_content_lower = str(user_content).lower()

                        # 首先检查是否包含Cursor IDE/Cline上下文标签，如果有则跳过所有工具
                        cursor_patterns = [
                            r"<user_info>",
                            r"<rules>",
                            r"<project_layout>",
                            r"<user_query>",
                            r"<task>",
                            r"<environment_details>",
                            r"# VSCode Visible Files",
                            r"# VSCode Open Tabs",
                            r"# Current Working Directory",
                            r"# Current Mode"
                        ]

                        has_cursor_context = any(re.search(pattern, user_content_lower) for pattern in cursor_patterns)
                        if has_cursor_context:
                            logger.info("🚫 流式版本：检测到Cursor IDE上下文，跳过所有工具")
                            should_handle_tools = False
                        else:
                            # 搜索关键词检测（重点修复）
                            search_keywords = ["搜索", "search", "查找", "find", "寻找", "搜下", "搜个", "搜一搜", "搜一下"]
                            has_search_request = any(keyword in user_content_lower for keyword in search_keywords)

                            # 其他工具关键词检测
                            tool_keywords = [
                                "网页", "webpage", "网站", "website", "url", "获取",
                                "代码", "code", "执行", "run", "计算", "calculate", "python",
                                "文档", "document", "创建", "create", "保存", "save",
                                "分析", "analyze", "数据", "data", "统计", "statistics"
                            ]
                            has_tool_request = any(keyword in user_content_lower for keyword in tool_keywords)

                            if has_search_request or has_tool_request:
                                should_handle_tools = True
                                logger.info(f"🔧 流式版本：检测到工具请求 - 搜索: {has_search_request}, 其他工具: {has_tool_request}")
                                logger.info(f"🔍 用户消息: {user_content_lower[:100]}...")

                            # 创建工具调用
                            tool_calls = _create_tool_calls_from_request(str(user_content), tool_manager)
                            logger.info(f"🔧 流式版本：创建了 {len(tool_calls)} 个工具调用")

                            # 执行工具调用并获取结果
                            tool_results = []
                            gemini_analysis = None

                            for tool_call in tool_calls:
                                try:
                                    tool_name = tool_call.function.get("name", "unknown")
                                    logger.info(f"🔧 开始执行工具: {tool_name}")

                                    # 使用 execute_tool_call 方法执行工具调用，添加超时保护
                                    import asyncio
                                    try:
                                        tool_result = await asyncio.wait_for(
                                            tool_manager.execute_tool_call(tool_call),
                                            timeout=180.0  # 3分钟超时
                                        )
                                        logger.info(f"✅ 工具 {tool_name} 执行成功")
                                    except asyncio.TimeoutError:
                                        logger.error(f"❌ 工具 {tool_name} 执行超时")
                                        tool_results.append(f"工具 {tool_name} 执行超时，请稍后重试")
                                        continue

                                    if tool_name == "image_analyzer":
                                        # 保存 Gemini 的分析结果，稍后让 Claude 处理
                                        gemini_analysis = tool_result.content
                                        logger.info(f"🔍 Gemini 分析完成，长度: {len(gemini_analysis)} 字符")
                                        logger.info(f"🔍 Gemini 原始内容前200字符: {gemini_analysis[:200]}...")
                                    else:
                                        tool_results.append(f"工具 {tool_name} 执行结果：{tool_result.content}")

                                except Exception as e:
                                    logger.error(f"❌ 工具 {tool_name} 执行异常: {type(e).__name__}: {e}")
                                    import traceback
                                    logger.error(f"❌ 详细错误信息: {traceback.format_exc()}")
                                    tool_results.append(f"工具 {tool_name} 执行失败：{str(e)}")

                            # 如果有 Gemini 图片分析结果，让 Claude 根据系统提示词重新生成回答
                            if gemini_analysis:
                                logger.info("🤖 开始 Claude 二次处理，结合系统提示词生成最终回答")

                                # 构建给 Claude 的消息，包含原始用户请求和 Gemini 分析结果
                                claude_messages = []

                                # 添加系统提示词到 Claude 消息中
                                for msg in openai_request.messages:
                                    if msg.role == "system":
                                        claude_messages.append({
                                            "role": "system",
                                            "content": msg.content
                                        })
                                        break

                                # 提取用户的文本请求 - 只提取最新消息并过滤用户ID元数据
                                user_text = ""
                                if isinstance(last_message.content, list):
                                    for item in last_message.content:
                                        if isinstance(item, dict) and item.get('type') == 'text':
                                            user_text += item.get('text', '') + " "
                                else:
                                    user_text = str(last_message.content or "")

                                # 过滤掉用户ID元数据，只保留真实的用户请求
                                import re
                                user_id_pattern = r'\[User ID: \d+, Nickname: [^\]]+\]\s*'
                                user_text = re.sub(user_id_pattern, '', user_text, flags=re.IGNORECASE).strip()

                                # 如果过滤后为空，使用默认文本
                                if not user_text:
                                    user_text = "请分析这张图片"

                                # 保留 Gemini 完整分析内容
                                img_info = gemini_analysis

                                # 使用之前保存的原始用户系统提示词
                                user_role_prompt = original_user_system_prompt if original_user_system_prompt else "你是一个可爱的助手"

                                logger.info(f"🔍 使用保存的原始用户系统提示词")
                                logger.info(f"🔍 最终角色设定: {user_role_prompt}")

                                # 严格保持用户角色设定的图片分析提示
                                claude_user_message = f"""你必须严格按照以下角色设定回应：
{user_role_prompt}

用户说：{user_text.strip()}

图片内容：{img_info}

重要：你必须完全按照上述角色设定的语言风格和特征来回应，不要改变角色，不要表现得像技术专家或AI助手。严格保持角色的语气、用词和表达方式。"""

                                # 调试请求大小
                                logger.info(f"🔍 请求大小调试:")
                                logger.info(f"  - 用户角色设定长度: {len(user_role_prompt)}")
                                logger.info(f"  - 用户文本长度: {len(user_text)}")
                                logger.info(f"  - Gemini完整分析长度: {len(img_info)}")
                                logger.info(f"  - Claude消息总长度: {len(claude_user_message)}")
                                logger.info(f"  - Gemini分析前200字符: {img_info[:200]}...")

                                # 检查是否会导致413
                                if len(claude_user_message) > 8000:
                                    logger.warning(f"⚠️ Claude消息过长: {len(claude_user_message)} 字符，可能导致413错误")
                                if len(img_info) > 5000:
                                    logger.warning(f"⚠️ Gemini分析过长: {len(img_info)} 字符，可能导致413错误")

                                claude_messages.append({
                                    "role": "user",
                                    "content": claude_user_message
                                })

                                # 调用 Claude 进行二次处理
                                try:
                                    claude_response = ""
                                    async for chunk in mcp_client.call_smithery_claude_stream(claude_messages, openai_request.model):
                                        if chunk:
                                            claude_response += chunk
                                            # 流式返回 Claude 的处理结果
                                            chunk_obj = ChatCompletionStreamResponse(
                                                id=request_id,
                                                created=created,
                                                model=openai_request.model,
                                                choices=[ChatCompletionStreamChoice(
                                                    index=0,
                                                    delta={"content": chunk},
                                                    finish_reason=None
                                                )]
                                            )
                                            yield f"data: {chunk_obj.model_dump_json()}\n\n"

                                    logger.info(f"✅ Claude 二次处理完成，最终回答长度: {len(claude_response)} 字符")

                                except Exception as e:
                                    logger.error(f"❌ Claude 二次处理失败: {e}")
                                    # 如果 Claude 处理失败，输出友好的错误消息，不暴露 Gemini 原始分析
                                    fallback_result = "抱歉，我在处理这张图片时遇到了一些技术问题。请稍后再试，或者尝试上传其他图片。"
                                    for char in fallback_result:
                                        chunk_obj = ChatCompletionStreamResponse(
                                            id=request_id,
                                            created=created,
                                            model=openai_request.model,
                                            choices=[ChatCompletionStreamChoice(
                                                index=0,
                                                delta={"content": char},
                                                finish_reason=None
                                            )]
                                        )
                                        yield f"data: {chunk_obj.model_dump_json()}\n\n"
                            else:
                                # 没有图片分析，处理其他工具结果
                                if tool_results:
                                    combined_result = "\n\n".join(tool_results)

                                    # 将工具结果发送给AI进行智能处理
                                    logger.info("🔧 将工具结果发送给AI进行智能处理")

                                    # 构建包含工具结果的消息
                                    messages_with_tool_results = messages.copy()
                                    messages_with_tool_results.append({
                                        "role": "user",
                                        "content": combined_result
                                    })

                                    # 调用AI处理工具结果
                                    try:
                                        async for text_chunk in mcp_client.call_smithery_claude_stream(messages_with_tool_results, openai_request.model):
                                            chunk_obj = ChatCompletionStreamResponse(
                                                id=request_id,
                                                created=created,
                                                model=openai_request.model,
                                                choices=[ChatCompletionStreamChoice(
                                                    index=0,
                                                    delta={"content": text_chunk},
                                                    finish_reason=None
                                                )]
                                            )
                                            yield f"data: {chunk_obj.model_dump_json()}\n\n"
                                    except Exception as e:
                                        logger.error(f"❌ AI处理工具结果失败: {e}")
                                        # 如果AI处理失败，直接返回工具结果
                                        for char in combined_result:
                                            chunk_obj = ChatCompletionStreamResponse(
                                                id=request_id,
                                                created=created,
                                                model=openai_request.model,
                                                choices=[ChatCompletionStreamChoice(
                                                    index=0,
                                                    delta={"content": char},
                                                    finish_reason=None
                                                )]
                                            )
                                            yield f"data: {chunk_obj.model_dump_json()}\n\n"
                                else:
                                    # 没有工具结果，返回空内容
                                    pass



            # 如果没有工具调用，使用正常的Smithery.ai流式响应
            if not should_handle_tools:
                try:
                    logger.info("🔍 开始流式调用 Smithery.ai")
                    stream_success = False

                    async for text_chunk in mcp_client.call_smithery_claude_stream(messages, openai_request.model):
                        if text_chunk:
                            stream_success = True
                            # 累计completion tokens
                            if include_usage:
                                completion_tokens += _estimate_tokens(text_chunk)

                            chunk = ChatCompletionStreamResponse(
                                id=request_id,
                                created=created,
                                model=openai_request.model,
                                choices=[ChatCompletionStreamChoice(
                                    index=0,
                                    delta={"content": text_chunk},
                                    finish_reason=None
                                )]
                            )
                            yield f"data: {chunk.model_dump_json()}\n\n"

                    if not stream_success:
                        logger.warning("流式调用未产生任何内容，尝试降级到非流式调用")
                        raise Exception("流式调用未产生内容")

                except Exception as stream_error:
                    logger.error(f"流式调用失败: {stream_error}，尝试降级到非流式调用")

                    try:
                        # 降级到非流式调用
                        logger.info("🔄 降级到非流式调用")
                        non_stream_response = await mcp_client.call_smithery_claude(messages, openai_request.model)

                        if non_stream_response:
                            # 累计completion tokens（降级情况）
                            if include_usage:
                                completion_tokens += _estimate_tokens(non_stream_response)

                            # 将非流式响应转换为流式格式
                            for char in non_stream_response:
                                chunk = ChatCompletionStreamResponse(
                                    id=request_id,
                                    created=created,
                                    model=openai_request.model,
                                    choices=[ChatCompletionStreamChoice(
                                        index=0,
                                        delta={"content": char},
                                        finish_reason=None
                                    )]
                                )
                                yield f"data: {chunk.model_dump_json()}\n\n"
                        else:
                            # 如果非流式调用也失败，返回错误信息
                            error_message = "抱歉，我在处理您的请求时遇到了技术问题。请稍后再试。"
                            for char in error_message:
                                chunk = ChatCompletionStreamResponse(
                                    id=request_id,
                                    created=created,
                                    model=openai_request.model,
                                    choices=[ChatCompletionStreamChoice(
                                        index=0,
                                        delta={"content": char},
                                        finish_reason=None
                                    )]
                                )
                                yield f"data: {chunk.model_dump_json()}\n\n"

                    except Exception as fallback_error:
                        logger.error(f"非流式降级调用也失败: {fallback_error}")
                        # 最终错误处理
                        error_message = "系统暂时不可用，请稍后再试。"
                        for char in error_message:
                            chunk = ChatCompletionStreamResponse(
                                id=request_id,
                                created=created,
                                model=openai_request.model,
                                choices=[ChatCompletionStreamChoice(
                                    index=0,
                                    delta={"content": char},
                                    finish_reason=None
                                )]
                            )
                            yield f"data: {chunk.model_dump_json()}\n\n"

            # 发送结束chunk
            end_chunk = ChatCompletionStreamResponse(
                id=request_id,
                created=created,
                model=openai_request.model,
                choices=[ChatCompletionStreamChoice(
                    index=0,
                    delta={},
                    finish_reason="stop"
                )]
            )
            yield f"data: {end_chunk.model_dump_json()}\n\n"

            # 如果需要包含usage信息，发送额外的usage chunk
            if include_usage:
                # 创建usage对象
                usage = ChatCompletionUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens
                )

                # 创建usage chunk（注意：choices为空数组，符合OpenAI标准）
                usage_chunk = ChatCompletionStreamResponse(
                    id=request_id,
                    created=created,
                    model=openai_request.model,
                    choices=[],
                    usage=usage
                )
                yield f"data: {usage_chunk.model_dump_json()}\n\n"

                # 记录使用统计
                if auth_token:
                    try:
                        from ...services.database import get_database_manager
                        db_manager = get_database_manager()
                        api_key_record = db_manager.get_api_key_by_key(auth_token)
                        if api_key_record:
                            db_manager.log_usage(
                                user_id=api_key_record.user_id,
                                api_key_id=api_key_record.id,
                                endpoint="/v1/chat/completions",
                                method="POST",
                                status_code=200,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                model=openai_request.model
                            )
                    except Exception as e:
                        logger.warning(f"记录使用统计失败: {e}")

            # 发送结束标记
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"流式响应生成错误: {e}")
            # 发送错误信息
            error_response = ProtocolConverter.create_error_response(
                error_message=str(e),
                error_type="stream_error"
            )
            error_data = error_response.model_dump_json()
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/plain; charset=utf-8"
        }
    )


@router.get("/models")
async def list_models(
    _settings: Settings = Depends(get_settings)
):
    """
    列出可用模型

    返回支持的模型列表，兼容OpenAI格式。
    """
    
    models = [
        {
            "id": "claude-sonnet-4-20250514",
            "object": "model",
            "created": 1677610602,
            "owned_by": "anthropic",
            "permission": [],
            "root": "claude-sonnet-4-20250514",
            "parent": None
        },
        {
            "id": "claude-opus-4-20250514",
            "object": "model",
            "created": 1677610602,
            "owned_by": "anthropic",
            "permission": [],
            "root": "claude-opus-4-20250514",
            "parent": None
        }
    ]
    
    return {
        "object": "list",
        "data": models
    }


async def _handle_tool_calling_response(
    mcp_client,
    openai_request: ChatCompletionRequest,
    auth_token: str,
    tool_manager: ToolManager,
    original_has_tools: bool = None,
    original_user_system_prompt: str = ""
) -> ChatCompletionResponse:
    """处理工具调用响应 - 直接执行工具，不通过MCP"""
    logger.info("🚀 === 进入_handle_tool_calling_response函数 ===")

    # 检查是否有现有的工具调用需要执行
    tool_calls_to_execute = []

    # 检查消息中是否已经包含工具调用
    for msg in openai_request.messages:
        if msg.tool_calls:
            for tool_call_data in msg.tool_calls:
                try:
                    from ...models.tool_models import ToolCall
                    tool_call = ToolCall(**tool_call_data)
                    tool_calls_to_execute.append(tool_call)
                except Exception as e:
                    logger.error(f"解析工具调用失败: {e}")

    # 如果有工具调用需要执行，直接执行
    if tool_calls_to_execute:
        logger.info(f"检测到 {len(tool_calls_to_execute)} 个工具调用，开始执行...")

        # 执行所有工具调用
        tool_results = []
        for tool_call in tool_calls_to_execute:
            try:
                result = await tool_manager.execute_tool_call(tool_call)
                tool_results.append(result)
                logger.info(f"工具 {tool_call.function['name']} 执行成功")
            except Exception as e:
                logger.error(f"工具 {tool_call.function['name']} 执行失败: {e}")
                # 创建错误结果
                from ...models.tool_models import ToolCallResult
                error_result = ToolCallResult(
                    tool_call_id=tool_call.id,
                    role="tool",
                    name=tool_call.function['name'],
                    content=f"工具执行失败: {str(e)}"
                )
                tool_results.append(error_result)

        # 构建工具执行结果的响应
        tool_results_text = "\n\n".join([
            f"工具 {result.name} 执行结果:\n{result.content}"
            for result in tool_results
        ])

        response_content = f"我已经执行了您请求的工具调用。以下是执行结果：\n\n{tool_results_text}"

        # 创建响应
        from ...models.openai_models import ChatMessage, ChatCompletionChoice, ChatCompletionUsage
        import time
        from uuid import uuid4

        # 根据请求是否包含tools参数决定响应格式
        logger.info(f"🔧 工具执行完成，兼容性检查：请求包含tools参数={bool(openai_request.tools)}")

        if openai_request.tools:
            # 标准OpenAI格式：返回tool_calls
            logger.info("📋 工具执行-标准格式：返回tool_calls")
            choice = ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=response_content,
                    tool_calls=[{
                        "id": f"call_{uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": "tool_execution_result",
                            "arguments": "{}"
                        }
                    }]
                ),
                finish_reason="tool_calls"
            )
        else:
            # 简化格式：不返回tool_calls
            logger.info("🎯 工具执行-简化格式：不返回tool_calls")
            choice = ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=response_content,
                    tool_calls=None
                ),
                finish_reason="stop"
            )

        # 估算token使用量
        prompt_tokens = sum(_estimate_tokens(str(msg.content or "")) for msg in openai_request.messages)
        completion_tokens = _estimate_tokens(response_content)

        usage = ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )

        response = ChatCompletionResponse(
            id=f"chatcmpl-{uuid4().hex[:29]}",
            created=int(time.time()),
            model=openai_request.model,
            choices=[choice],
            usage=usage
        )

        # 记录使用统计
        await _log_usage_stats(auth_token, response, openai_request.model)

        # 清理响应并返回
        from ...utils.response_cleaner import clean_openai_response
        response_dict = response.model_dump()
        cleaned_response_dict = clean_openai_response(response_dict)

        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=cleaned_response_dict,
            headers={"Content-Type": "application/json"}
        )

    # 如果没有现有工具调用，检查是否需要创建工具调用
    last_message = openai_request.messages[-1] if openai_request.messages else None
    if last_message and last_message.role == "user":
        # 保持原始内容格式，不要转换为字符串（这样会丢失图片信息）
        user_content = last_message.content or ""

        # 检查用户请求是否需要工具调用
        # 区分两种模式：
        # 1. 带tools参数 - 标准OpenAI模式，自动创建工具调用
        # 2. 不带tools参数 - 简化模式，只在明确要求时创建工具调用
        should_auto_create_tools = False

        if openai_request.tools:
            # 标准OpenAI模式：如果请求包含tools参数，按正常逻辑处理
            should_auto_create_tools = tool_manager.should_use_tools([{"role": "user", "content": user_content}])
        else:
            # 简化模式：不带tools参数时，直接执行工具并返回结果，不返回tool_calls
            should_auto_create_tools = tool_manager.should_use_tools([{"role": "user", "content": user_content}])

        if should_auto_create_tools:
            logger.info("🔧 检测到需要工具调用，创建工具调用...")
            logger.info(f"🔧 请求包含tools参数: {bool(openai_request.tools)}")

            # 根据用户请求创建合适的工具调用
            # 如果 user_content 是列表（多模态），需要特殊处理
            if isinstance(user_content, list):
                # 对于多模态内容，直接传递原始消息给工具调用函数
                tool_calls = _create_tool_calls_from_multimodal_request(last_message, tool_manager)
            else:
                # 对于纯文本内容，使用原有逻辑
                tool_calls = _create_tool_calls_from_request(str(user_content), tool_manager)
            logger.info(f"🔧 创建了 {len(tool_calls) if tool_calls else 0} 个工具调用")

            if tool_calls:
                # 检查是否有需要返回给AstrBot的工具调用
                astrbot_tool_calls = []
                local_tool_calls = []

                for tool_call in tool_calls:
                    tool_name = tool_call.function.get('name', '')

                    # 检查是否是AstrBot专有工具
                    if hasattr(tool_manager, 'detected_astrbot_tools'):
                        detected_tools = tool_manager.detected_astrbot_tools.get('astrbot_tools', [])
                        is_astrbot_tool = False

                        for tool_info in detected_tools:
                            if tool_info['name'] == tool_name:
                                capabilities = tool_info.get('capabilities', {})
                                if capabilities.get('should_call_astrbot', False):
                                    is_astrbot_tool = True
                                    break

                        if is_astrbot_tool:
                            astrbot_tool_calls.append(tool_call)
                            logger.info(f"🤖 工具 {tool_name} 将返回给AstrBot执行")
                        else:
                            local_tool_calls.append(tool_call)
                            logger.info(f"🔧 工具 {tool_name} 将在本地执行")
                    else:
                        # 如果没有检测信息，默认本地执行
                        local_tool_calls.append(tool_call)

                # 如果有AstrBot工具调用，直接返回给AstrBot
                if astrbot_tool_calls:
                    logger.info(f"🤖 返回 {len(astrbot_tool_calls)} 个AstrBot工具调用")

                    # 转换为OpenAI格式的工具调用
                    openai_tool_calls = []
                    for tool_call in astrbot_tool_calls:
                        openai_tool_calls.append({
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": tool_call.function
                        })

                    # 返回工具调用指令
                    from ...models.openai_models import ChatMessage, ChatCompletionChoice, ChatCompletionUsage
                    import time
                    from uuid import uuid4
                    import json

                    choice = ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role="assistant",
                            content="",  # 空字符串而不是None
                            tool_calls=openai_tool_calls
                        ),
                        finish_reason="tool_calls"
                    )

                    # 估算token使用量
                    prompt_tokens = sum(_estimate_tokens(str(msg.content or "")) for msg in openai_request.messages)
                    completion_tokens = sum(_estimate_tokens(json.dumps(tc)) for tc in openai_tool_calls)

                    usage = ChatCompletionUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens
                    )

                    response = ChatCompletionResponse(
                        id=f"chatcmpl-{uuid4().hex[:29]}",
                        created=int(time.time()),
                        model=openai_request.model,
                        choices=[choice],
                        usage=usage
                    )

                    # 记录使用统计
                    await _log_usage_stats(auth_token, response, openai_request.model)

                    # 清理响应并返回
                    from ...utils.response_cleaner import clean_openai_response
                    response_dict = response.model_dump()
                    cleaned_response_dict = clean_openai_response(response_dict)

                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        content=cleaned_response_dict,
                        headers={"Content-Type": "application/json"}
                    )

                # 执行本地工具调用
                tool_results = []
                gemini_analysis = None

                for tool_call in local_tool_calls:
                    try:
                        result = await tool_manager.execute_tool_call(tool_call)

                        if result.name == "image_analyzer":
                            # 保存 Gemini 的分析结果，稍后让 Claude 处理
                            gemini_analysis = result.content
                            logger.info(f"🔍 Gemini 分析完成，长度: {len(gemini_analysis)} 字符")
                        else:
                            tool_results.append(result)

                        logger.info(f"自动工具 {tool_call.function['name']} 执行成功")
                    except Exception as e:
                        logger.error(f"自动工具 {tool_call.function['name']} 执行失败: {e}")

                # 构建响应
                # 检查是否需要Claude二次处理（Gemini分析或搜索结果）
                has_search_results = any(
                    "我已经为您搜索了" in result.content or
                    "搜索结果" in result.content or
                    result.name == "web_search"
                    for result in tool_results
                )
                logger.info(f"🔍 检查Claude二次处理条件 - Gemini分析: {bool(gemini_analysis)}, 搜索结果: {has_search_results}")
                if tool_results:
                    logger.info(f"🔍 工具结果内容: {tool_results[0].content[:200]}...")  # 显示第一个结果的前200字符
                else:
                    logger.info("🔍 工具结果内容: 无")

                if gemini_analysis or has_search_results:
                    # 如果有 Gemini 图片分析结果或搜索结果，让 Claude 根据系统提示词重新生成回答
                    if gemini_analysis:
                        logger.info("🤖 开始 Claude 二次处理，结合系统提示词生成最终回答")
                    else:
                        logger.info("🤖 开始 Claude 二次处理，结合搜索结果生成最终回答")

                    # 构建给 Claude 的消息，包含原始用户请求和 Gemini 分析结果
                    claude_messages = []

                    # 添加系统提示词到 Claude 消息中
                    for msg in openai_request.messages:
                        if msg.role == "system":
                            claude_messages.append({
                                "role": "system",
                                "content": msg.content
                            })
                            break

                    # 提取用户的文本请求 - 只提取最新消息并过滤用户ID元数据
                    user_text = ""
                    last_message = openai_request.messages[-1]
                    if isinstance(last_message.content, list):
                        for item in last_message.content:
                            if isinstance(item, dict) and item.get('type') == 'text':
                                user_text += item.get('text', '') + " "
                    else:
                        user_text = str(last_message.content or "")

                    # 过滤掉用户ID元数据，只保留真实的用户请求
                    import re
                    user_id_pattern = r'\[User ID: \d+, Nickname: [^\]]+\]\s*'
                    user_text = re.sub(user_id_pattern, '', user_text, flags=re.IGNORECASE).strip()

                    # 如果过滤后为空，使用默认文本
                    if not user_text:
                        user_text = "请分析这张图片"

                    # 保留 Gemini 完整分析内容或搜索结果
                    if gemini_analysis:
                        analysis_info = gemini_analysis
                        analysis_type = "图片内容"
                    else:
                        # 构建搜索结果信息
                        analysis_info = "\n".join(result.content for result in tool_results)
                        analysis_type = "搜索结果"

                    # 获取用户的角色设定，过滤掉系统的视觉能力描述
                    user_role_prompt = ""
                    original_system_prompt = ""

                    for msg in openai_request.messages:
                        if msg.role == "system":
                            original_system_prompt = msg.content
                            break

                    logger.info(f"🔍 原始系统提示词长度: {len(original_system_prompt)}")
                    logger.info(f"🔍 原始系统提示词前200字符: {original_system_prompt[:200]}...")

                    # 使用之前保存的原始用户系统提示词
                    user_role_prompt = original_user_system_prompt if original_user_system_prompt else "你是一个可爱的助手"

                    logger.info(f"🔍 使用保存的原始用户系统提示词")
                    logger.info(f"🔍 最终角色设定: {user_role_prompt}")

                    # 严格保持用户角色设定的分析提示
                    claude_user_message = f"""你必须严格按照以下角色设定回应：

{user_role_prompt}

用户说：{user_text.strip()}

{analysis_type}：
{analysis_info}

请根据以上{analysis_type.lower()}，为用户提供关于'{user_text.strip()}'的详细总结和分析。

⚠️ 重要要求 - 必须严格遵守:
1. 🔗 必须在回答中包含所有搜索结果的完整链接URL
2. 📝 必须详细描述每个搜索结果的内容和价值
3. 🎭 保持角色的说话风格和语气
4. 💡 提供有价值的总结和见解
5. 📋 按照以下格式组织回答:
   - 开场白（角色风格）
   - 详细介绍每个搜索结果（包含链接和描述）
   - 总结分析（角色风格）

示例格式:
🌐 官方网站: https://www.nvidia.com/en-us/
📖 详细介绍: [对该网站内容的详细描述]

重要：你必须完全按照上述角色设定的语言风格和特征来回应，不要改变角色，不要表现得像技术专家或AI助手。严格保持角色的语气、用词和表达方式。请根据提供的信息进行智能总结和分析。"""

                    claude_messages.append({
                        "role": "user",
                        "content": claude_user_message
                    })

                    # 调用 Claude 进行二次处理
                    try:
                        claude_response = await mcp_client.call_smithery_claude(claude_messages, openai_request.model)
                        response_content = claude_response
                        logger.info(f"✅ Claude 二次处理完成，最终回答长度: {len(claude_response)} 字符")

                    except Exception as e:
                        logger.error(f"❌ Claude 二次处理失败: {e}")
                        # 如果 Claude 处理失败，输出友好的错误消息，不暴露 Gemini 原始分析
                        response_content = "抱歉，我在处理这张图片时遇到了一些技术问题。请稍后再试，或者尝试上传其他图片。"

                elif tool_results:
                    # 没有图片分析，处理其他工具结果
                    formatted_results = []
                    for result in tool_results:
                        formatted_results.append(f"🔧 **{result.name}**\n\n{result.content}")

                    tool_results_text = "\n\n".join(formatted_results)

                    if openai_request.tools:
                        # 带tools参数：标准OpenAI格式的内容
                        response_content = tool_results_text
                    else:
                        # 不带tools参数：简化格式的内容，添加特殊标记
                        response_content = f"{tool_results_text}\n\n<!-- SIMPLIFIED_MODE -->"
                else:
                    response_content = "抱歉，工具执行失败，无法完成您的请求。"
        else:
            # 不需要工具调用，直接让AI处理（如角色扮演、普通对话等）
            logger.info("🎭 不需要工具调用，直接调用AI处理")

            # 初始化变量，确保后续代码不会出现NameError
            tool_calls = None

            # 构建消息列表，包含系统提示词
            messages_for_ai = []

            # 添加系统提示词
            for msg in openai_request.messages:
                if msg.role == "system":
                    messages_for_ai.append({
                        "role": "system",
                        "content": msg.content
                    })
                    break

            # 添加用户消息
            messages_for_ai.append({
                "role": "user",
                "content": user_content
            })

            logger.info(f"🎭 发送给AI的消息数量: {len(messages_for_ai)}")

            # 调用AI处理
            try:
                response_content = await mcp_client.call_smithery_claude(messages_for_ai, openai_request.model)
                logger.info(f"✅ AI处理完成，回复长度: {len(response_content)} 字符")
            except Exception as e:
                logger.error(f"❌ AI处理失败: {e}")
                response_content = "抱歉，处理您的请求时遇到了问题，请稍后重试。"

        # 创建响应 - 修复缩进错误，移到正确位置
        from ...models.openai_models import ChatMessage, ChatCompletionChoice, ChatCompletionUsage
        import time
        from uuid import uuid4

        logger.info(f"🔧 准备创建最终响应，内容: {response_content[:100]}...")
        logger.info(f"🔧 响应内容长度: {len(response_content)} 字符")

        # 根据原始请求是否包含tools参数决定响应格式
        logger.info(f"🔧 兼容性检查：原始请求包含tools参数={original_has_tools}")
        logger.info(f"🔧 当前请求包含tools参数={bool(openai_request.tools)}")
        if original_has_tools:
            # 检查是否已经执行了工具并得到了最终答案
            if tool_calls and response_content and len(response_content.strip()) > 50:
                # 如果已经有了详细的回答内容，说明工具已经执行完成，直接返回最终答案
                logger.info("📋 工具已执行完成，返回最终答案（不返回tool_calls）")
                choice = ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=response_content,
                        tool_calls=None
                    ),
                    finish_reason="stop"
                )
                logger.info("📋 最终答案格式设置：finish_reason=stop, tool_calls=None")
            else:
                # 标准OpenAI工具调用格式 - 返回tool_calls（仅当工具未执行时）
                logger.info("📋 使用标准OpenAI格式：返回tool_calls")
                choice = ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=response_content,
                        tool_calls=[tc.model_dump() for tc in tool_calls] if tool_calls else None
                    ),
                    finish_reason="tool_calls" if tool_calls else "stop"
                )
                logger.info(f"📋 标准格式设置：finish_reason={'tool_calls' if tool_calls else 'stop'}")
        else:
            # 简化格式 - 只返回执行结果，不返回tool_calls
            logger.info("🎯 使用简化格式：不返回tool_calls，finish_reason=stop")
            choice = ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=response_content,
                    tool_calls=None
                ),
                finish_reason="stop"
            )
            logger.info("🎯 简化格式设置完成：finish_reason=stop, tool_calls=None")

        # 估算token使用量
        prompt_tokens = sum(_estimate_tokens(str(msg.content or "")) for msg in openai_request.messages)
        completion_tokens = _estimate_tokens(response_content)

        usage = ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )

        response = ChatCompletionResponse(
            id=f"chatcmpl-{uuid4().hex[:29]}",
            created=int(time.time()),
            model=openai_request.model,
            choices=[choice],
            usage=usage
        )

        # 记录使用统计
        await _log_usage_stats(auth_token, response, openai_request.model)

        # 清理响应并返回
        from ...utils.response_cleaner import clean_openai_response
        response_dict = response.model_dump()

        # 强制兼容性修复：如果请求不包含tools参数，修改响应格式
        logger.info(f"兼容性检查：请求包含tools参数={bool(openai_request.tools)}")
        if not openai_request.tools:
            logger.info("🔧 应用Chatbox兼容性修复：移除tool_calls，设置finish_reason为stop")
            if 'choices' in response_dict and response_dict['choices']:
                for choice in response_dict['choices']:
                    if 'message' in choice and choice['message']:
                        # 强制移除tool_calls
                        if 'tool_calls' in choice['message']:
                            logger.info(f"🗑️ 删除tool_calls字段：{choice['message']['tool_calls']}")
                            del choice['message']['tool_calls']
                        # 强制设置finish_reason为stop
                        old_finish_reason = choice.get('finish_reason')
                        choice['finish_reason'] = 'stop'
                        logger.info(f"🔄 修改finish_reason：{old_finish_reason} -> stop")
        else:
            logger.info("📋 标准OpenAI模式：保持tool_calls格式")

        cleaned_response_dict = clean_openai_response(response_dict)

        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=cleaned_response_dict,
            headers={"Content-Type": "application/json"}
        )

    # 如果不需要工具调用，但需要修改系统提示词来告知工具能力
    # 检查是否是询问能力的问题（但排除角色扮演任务）
    last_message = openai_request.messages[-1] if openai_request.messages else None
    if last_message and last_message.role == "user":
        user_content = str(last_message.content or "").lower()

        # 首先检查是否为角色扮演任务
        roleplay_indicators = [
            "扮演角色", "你需要扮演", "角色扮演", "朋友圈", "评论回复",
            "role play", "play the role", "character roleplay"
        ]

        is_roleplay = any(indicator in user_content for indicator in roleplay_indicators)

        if not is_roleplay:
            # 只有在不是角色扮演任务时才检查能力询问
            capability_keywords = ["你能做什么", "你有什么功能", "你有什么工具", "你能调用什么", "你有什么能力", "can you do", "what can you", "what tools", "what functions", "what capabilities"]

            if any(keyword in user_content for keyword in capability_keywords):
                # 使用统一管理器的模型特定回答
                capability_response = UnifiedPromptManager.get_balanced_capability_response(openai_request.model)

                from ...models.openai_models import ChatMessage, ChatCompletionChoice, ChatCompletionUsage
                import time
                from uuid import uuid4

                choice = ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=capability_response,
                        tool_calls=None
                    ),
                    finish_reason="stop"
                )

                # 估算token使用量
                prompt_tokens = sum(_estimate_tokens(str(msg.content or "")) for msg in openai_request.messages)
                completion_tokens = _estimate_tokens(capability_response)

                usage = ChatCompletionUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens
                )

                response = ChatCompletionResponse(
                    id=f"chatcmpl-{uuid4().hex[:29]}",
                    created=int(time.time()),
                    model=openai_request.model,
                    choices=[choice],
                    usage=usage
                )

                # 记录使用统计
                await _log_usage_stats(auth_token, response, openai_request.model)

                # 清理响应并返回
                from ...utils.response_cleaner import clean_openai_response
                response_dict = response.model_dump()
                cleaned_response_dict = clean_openai_response(response_dict)

                from fastapi.responses import JSONResponse
                return JSONResponse(
                    content=cleaned_response_dict,
                    headers={"Content-Type": "application/json"}
                )

    # 对于其他普通对话，修改系统提示词后调用Smithery.ai
    # 创建修改后的请求，包含工具能力的系统提示词
    modified_messages = []

    # 系统消息已在主函数中统一处理，无需重复添加

    # 添加原始消息
    modified_messages.extend(openai_request.messages)

    # 创建修改后的请求
    modified_request = openai_request.model_copy()
    modified_request.messages = modified_messages

    return await _handle_normal_response(mcp_client, modified_request, auth_token, None, None, "")


def _create_tool_calls_from_multimodal_request(message, tool_manager: ToolManager) -> List[ToolCall]:
    """根据多模态用户请求创建工具调用"""
    import re  # 确保导入re模块
    tool_calls = []

    if not message or not hasattr(message, 'content'):
        return tool_calls

    content = message.content
    if not isinstance(content, list):
        return tool_calls

    # 提取文本内容
    text_content = ""
    has_image = False

    for item in content:
        if isinstance(item, dict):
            if item.get('type') == 'text':
                text_content += item.get('text', '') + " "
            elif item.get('type') in ['image_url', 'image']:
                has_image = True

    text_content = text_content.strip()

    # 检查是否包含Cursor IDE/Cline上下文标签，如果有则不创建任何工具调用
    cursor_patterns = [
        r"<user_info>",
        r"<rules>",
        r"<project_layout>",
        r"<user_query>",
        r"<task>",
        r"<environment_details>",
        r"# VSCode Visible Files",
        r"# VSCode Open Tabs",
        r"# Current Working Directory",
        r"# Current Mode"
    ]

    text_content_lower = text_content.lower()
    for pattern in cursor_patterns:
        if re.search(pattern, text_content_lower):
            logger.info(f"🚫 _create_tool_calls_from_multimodal_request: 检测到Cursor IDE上下文标签，跳过工具调用: {pattern}")
            return []

    # 如果包含图片，创建图片分析工具调用
    if has_image:
        logger.info("🖼️ 检测到多模态图片内容，创建图片分析工具调用")

        # 检测分析类型
        analysis_type = "describe"  # 默认描述
        question = text_content or "请分析这张图片"

        content_lower = text_content.lower()
        if any(keyword in content_lower for keyword in ["文字", "text", "ocr", "识别"]):
            analysis_type = "ocr"
        elif any(keyword in content_lower for keyword in ["检测", "detect", "物体", "object"]):
            analysis_type = "detect"
        elif any(keyword in content_lower for keyword in ["分析", "analyze", "详细"]):
            analysis_type = "analyze"
        elif "?" in text_content or "？" in text_content:
            analysis_type = "qa"

        # 从多模态内容中提取图片
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'image_url':
                image_url = item.get('image_url', {}).get('url', '')
                if image_url:
                    tool_call = tool_manager.create_tool_call("image_analyzer", {
                        "image_input": image_url,
                        "analysis_type": analysis_type,
                        "question": question,
                        "language": "zh"
                    })
                    tool_calls.append(tool_call)
                    logger.info(f"✅ 创建图片分析工具调用: {analysis_type}, URL: {image_url[:50]}...")
                    break

    # 如果没有图片但有其他关键词，使用原有的文本分析逻辑
    if not has_image and text_content:
        return _create_tool_calls_from_request(text_content, tool_manager)

    return tool_calls

def _create_tool_calls_from_request(user_content: str, tool_manager: ToolManager) -> List[ToolCall]:
    """根据用户请求创建工具调用"""
    import re  # 确保导入re模块
    tool_calls = []
    content_lower = user_content.lower()

    # 首先检查是否包含Cursor IDE/Cline上下文标签，如果有则不创建任何工具调用
    cursor_patterns = [
        r"<user_info>",
        r"<rules>",
        r"<project_layout>",
        r"<user_query>",
        r"<task>",
        r"<environment_details>",
        r"# VSCode Visible Files",
        r"# VSCode Open Tabs",
        r"# Current Working Directory",
        r"# Current Mode"
    ]

    for pattern in cursor_patterns:
        if re.search(pattern, content_lower):
            logger.info(f"🚫 _create_tool_calls_from_request: 检测到Cursor IDE上下文标签，跳过工具调用: {pattern}")
            return []

    # 首先检查是否包含图片内容
    if tool_manager._has_image_content(user_content):
        logger.info("🖼️ 检测到图片内容，创建图片分析工具调用")

        # 检测分析类型
        analysis_type = "describe"  # 默认描述
        question = ""

        if any(keyword in content_lower for keyword in ["文字", "text", "ocr", "识别"]):
            analysis_type = "ocr"
        elif any(keyword in content_lower for keyword in ["检测", "detect", "物体", "object"]):
            analysis_type = "detect"
        elif any(keyword in content_lower for keyword in ["分析", "analyze", "详细"]):
            analysis_type = "analyze"
        elif "?" in user_content or "？" in user_content:
            analysis_type = "qa"
            question = user_content

        # 从用户内容中提取图片
        from ...utils.image_detector import ImageDetector
        images = ImageDetector.detect_images_in_message(user_content)

        if images:
            image_input = images[0]['source']  # 使用第一张图片

            tool_call = tool_manager.create_tool_call("image_analyzer", {
                "image_input": image_input,
                "analysis_type": analysis_type,
                "question": question if question else user_content,
                "language": "zh"
            })
            tool_calls.append(tool_call)
            logger.info(f"✅ 创建图片分析工具调用: {analysis_type}")

    # 检查搜索请求 - 增强日志和处理逻辑
    # 排除明显不是搜索请求的内容
    import re
    exclude_patterns = [
        r"<user_info>",  # Cursor IDE上下文信息
        r"<rules>",      # 用户规则
        r"<project_layout>",  # 项目布局
        r"分析.*项目",    # 项目分析请求
        r"分析.*代码",    # 代码分析请求
        r"解释.*代码",    # 代码解释请求
    ]

    # 检查是否应该跳过搜索工具
    should_skip_search = False
    for exclude_pattern in exclude_patterns:
        if re.search(exclude_pattern, user_content):
            logger.info(f"🚫 检测到排除模式，跳过搜索工具: {exclude_pattern}")
            should_skip_search = True
            break

    # 只有在不应该跳过搜索时才检查搜索关键词
    if not should_skip_search:
        search_keywords = ["搜索", "search", "查找", "find", "寻找", "搜下", "搜个", "搜一搜", "搜一下"]
        has_search_keyword = any(keyword in content_lower for keyword in search_keywords)
    else:
        has_search_keyword = False

    logger.info(f"🔍 搜索关键词检测 - 原始内容: {user_content[:100]}...")
    logger.info(f"🔍 搜索关键词检测 - 小写内容: {content_lower[:100]}...")
    logger.info(f"🔍 搜索关键词检测 - 结果: {has_search_keyword}")

    if has_search_keyword:
        # 提取搜索查询 - 处理用户ID包装的情况
        query = user_content

        # 移除用户ID包装
        import re
        user_id_pattern = r'\[User ID: \d+, Nickname: [^\]]+\]\s*'
        query = re.sub(user_id_pattern, '', query).strip()

        # 移除搜索关键词
        for keyword in ["请搜索", "搜索", "请查找", "查找", "search", "find", "寻找", "搜下", "搜个", "搜一搜", "搜一下"]:
            query = query.replace(keyword, "").strip()

        logger.info(f"🔍 提取的搜索查询: '{query}'")

        if query:
            logger.info(f"🔧 创建搜索工具调用，查询: {query}")
            tool_call = tool_manager.create_tool_call("web_search", {
                "query": query,
                "num_results": 3
            })
            tool_calls.append(tool_call)
            logger.info(f"✅ 成功创建搜索工具调用")
        else:
            logger.warning(f"⚠️ 搜索查询为空，跳过工具调用创建")

    # 检查代码执行请求
    code_keywords = ["执行", "运行", "代码", "code", "run", "execute", "计算", "calculate", "python", "javascript"]
    if any(keyword in content_lower for keyword in code_keywords):
        # 尝试提取代码块
        import re
        code_pattern = r'```(?:python|javascript|js)?\n(.*?)\n```'
        code_matches = re.findall(code_pattern, user_content, re.DOTALL)

        if code_matches:
            code = code_matches[0].strip()
            language = "python"  # 默认Python
            if "javascript" in content_lower or "js" in content_lower:
                language = "javascript"

            tool_call = tool_manager.create_tool_call("code_executor", {
                "code": code,
                "language": language
            })
            tool_calls.append(tool_call)
        else:
            # 如果没有代码块，但明确要求执行代码，尝试提取简单代码
            # 对于没有代码块的情况，生成合适的代码
            if "斐波那契" in user_content or "fibonacci" in content_lower:
                # 生成斐波那契数列代码
                code = """def fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]

    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])
    return fib

# 计算前10项
result = fibonacci(10)
print("斐波那契数列的前10项:")
for i, num in enumerate(result):
    print(f"第{i+1}项: {num}")"""

                tool_call = tool_manager.create_tool_call("code_executor", {
                    "code": code,
                    "language": "python"
                })
                tool_calls.append(tool_call)
            else:
                # 查找类似 "执行Python代码：print('hello')" 的模式
                simple_code_patterns = [
                    r'执行.*?代码[：:]?\s*(.+)',
                    r'运行.*?代码[：:]?\s*(.+)',
                    r'execute.*?code[：:]?\s*(.+)',
                    r'run.*?code[：:]?\s*(.+)',
                    # 新增：处理"运行Python代码计算1+1"这种模式
                    r'运行.*?代码.*?计算\s*(.+)',
                    r'执行.*?代码.*?计算\s*(.+)',
                    r'用.*?代码.*?计算\s*(.+)',
                    r'Python.*?计算\s*(.+)',
                    r'计算\s*(.+)',
                ]

                for pattern in simple_code_patterns:
                    match = re.search(pattern, user_content, re.IGNORECASE)
                    if match:
                        code = match.group(1).strip()
                        # 移除可能的引号
                        code = code.strip('"\'')

                        # 特殊处理：如果代码包含中文描述，尝试提取实际代码
                        if '计算' in code and any(op in code for op in ['+', '-', '*', '/', '=', '(', ')']):
                            # 提取数学表达式
                            math_pattern = r'([0-9+\-*/().\s]+)'
                            math_match = re.search(math_pattern, code)
                            if math_match:
                                code = math_match.group(1).strip()

                        if code and len(code) > 0:
                            language = "python"  # 默认Python
                            if "javascript" in content_lower or "js" in content_lower:
                                language = "javascript"

                            tool_call = tool_manager.create_tool_call("code_executor", {
                                "code": code,
                                "language": language
                            })
                            tool_calls.append(tool_call)
                            break

    # 检查网页获取请求
    url_keywords = ["网页", "webpage", "网站", "website", "获取", "fetch"]
    if any(keyword in content_lower for keyword in url_keywords):
        # 尝试提取URL
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, user_content)

        if urls:
            tool_call = tool_manager.create_tool_call("web_fetch", {
                "url": urls[0]
            })
            tool_calls.append(tool_call)

    # 检查数据分析请求
    data_keywords = ["分析", "analyze", "数据", "data", "统计", "statistics", "平均", "mean", "最高", "最低", "计算"]
    if any(keyword in content_lower for keyword in data_keywords):
        # 尝试提取JSON数据
        import re
        json_pattern = r'\[.*?\]'
        json_matches = re.findall(json_pattern, user_content, re.DOTALL)

        data_found = False

        if json_matches:
            # 找到JSON数据
            json_data = json_matches[0]
            try:
                import json
                parsed_data = json.loads(json_data)
                if isinstance(parsed_data, list) and len(parsed_data) > 0:
                    tool_call = tool_manager.create_tool_call("data_analyzer", {
                        "action": "analyze",
                        "data": json_data
                    })
                    tool_calls.append(tool_call)
                    data_found = True
            except:
                pass

        if not data_found:
            # 尝试提取CSV数据
            lines = user_content.split('\n')
            csv_lines = []
            for line in lines:
                if ',' in line and len(line.split(',')) > 1:
                    csv_lines.append(line.strip())

            if len(csv_lines) > 1:  # 至少有标题行和一行数据
                csv_data = '\n'.join(csv_lines)
                tool_call = tool_manager.create_tool_call("data_analyzer", {
                    "action": "analyze",
                    "data": csv_data
                })
                tool_calls.append(tool_call)
                data_found = True

    # 检查图片生成请求 - 使用智能AstrBot工具调用
    image_generation_keywords = ["生成", "画", "绘制", "创建", "制作", "draw", "generate", "create"]
    image_keywords = ["图片", "图像", "照片", "picture", "image", "photo"]

    # 特殊的图片生成模式（不需要明确的图片关键词）
    special_image_patterns = [
        r"画一张",
        r"画个",
        r"画出",
        r"绘制一张",
        r"生成一张",
        r"创建一张",
        r"制作一张",
        r"draw a",
        r"generate a",
        r"create a"
    ]

    is_image_generation = (
        # 传统检测：生成词 + 图片词
        (any(keyword in content_lower for keyword in image_generation_keywords) and
         any(keyword in content_lower for keyword in image_keywords)) or
        # 特殊模式检测：画一张、生成一张等
        any(re.search(pattern, content_lower) for pattern in special_image_patterns)
    )

    if is_image_generation:
        logger.info("🎨 检测到图片生成请求，创建AstrBot工具调用")

        # 直接创建AstrBot工具调用（同步版本）
        try:
            # 提取图片描述
            prompt = user_content
            # 清理用户ID信息
            import re
            prompt = re.sub(r'\[user id:.*?\]', '', prompt, flags=re.IGNORECASE)
            prompt = re.sub(r'\[.*?nickname:.*?\]', '', prompt, flags=re.IGNORECASE)
            prompt = re.sub(r'\s+', ' ', prompt).strip()

            # 移除生成相关的词汇，保留描述
            for word in ["生成", "画", "绘制", "创建", "制作", "一张", "图片", "图像", "照片"]:
                prompt = prompt.replace(word, "").strip()

            if prompt:
                logger.info(f"🎨 提取的图片描述: {prompt}")

                # 创建AstrBot工具调用
                from uuid import uuid4
                import json

                tool_call_data = {
                    "id": f"call_{uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "gemini_draw",
                        "arguments": json.dumps({
                            "prompt": prompt,
                            "image_index": 0,
                            "reference_bot": False
                        })
                    }
                }

                # 转换为ToolCall格式
                from ...models.tool_models import ToolCall
                tool_call = ToolCall(
                    id=tool_call_data['id'],
                    type=tool_call_data['type'],
                    function=tool_call_data['function']
                )
                tool_calls.append(tool_call)
                logger.info(f"✅ 成功创建AstrBot图片生成工具调用")
            else:
                logger.warning("⚠️ 无法提取图片描述")

        except Exception as e:
            logger.error(f"❌ 创建AstrBot工具调用失败: {e}")

    # 检查提醒请求
    reminder_keywords = ["提醒", "提示", "remind", "alert", "定时", "闹钟"]
    is_reminder = any(keyword in content_lower for keyword in reminder_keywords)

    if is_reminder:
        logger.info("⏰ 检测到提醒请求，创建AstrBot工具调用")
        try:
            # 提取提醒内容
            text = user_content
            # 清理用户ID信息
            import re
            text = re.sub(r'\[user id:.*?\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[.*?nickname:.*?\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s+', ' ', text).strip()

            # 移除提醒相关词汇
            for word in ["提醒", "提示", "remind", "alert"]:
                text = text.replace(word, "").strip()

            # 简单的时间提取
            datetime_str = None
            time_patterns = [
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',  # 2024-01-01 10:00
                r'明天\s*(\d{1,2}:\d{2})',  # 明天 10:00
                r'(\d{1,2}点)',  # 10点
            ]

            for pattern in time_patterns:
                match = re.search(pattern, user_content)
                if match:
                    datetime_str = match.group(1)
                    break

            if text:
                logger.info(f"⏰ 提取的提醒内容: {text}")

                # 创建AstrBot提醒工具调用
                from uuid import uuid4
                import json

                params = {"text": text}
                if datetime_str:
                    params["datetime_str"] = datetime_str

                tool_call_data = {
                    "id": f"call_{uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "reminder",
                        "arguments": json.dumps(params)
                    }
                }

                # 转换为ToolCall格式
                from ...models.tool_models import ToolCall
                tool_call = ToolCall(
                    id=tool_call_data['id'],
                    type=tool_call_data['type'],
                    function=tool_call_data['function']
                )
                tool_calls.append(tool_call)
                logger.info(f"✅ 成功创建AstrBot提醒工具调用")
            else:
                logger.warning("⚠️ 无法提取提醒内容")

        except Exception as e:
            logger.error(f"❌ 创建AstrBot提醒工具调用失败: {e}")

    # 检查网页获取请求
    url_keywords = ["获取", "抓取", "访问", "打开", "fetch"]
    web_keywords = ["网页", "网站", "链接", "url", "http"]

    is_web_fetch = (
        any(keyword in content_lower for keyword in url_keywords) and
        any(keyword in content_lower for keyword in web_keywords)
    ) or "http" in user_content

    if is_web_fetch:
        logger.info("🌐 检测到网页获取请求")
        try:
            # 提取URL
            import re
            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
            urls = re.findall(url_pattern, user_content)

            if urls:
                url = urls[0]
                logger.info(f"🌐 提取的URL: {url}")

                # 使用我们的web_fetch工具
                tool_call = tool_manager.create_tool_call("web_fetch", {"url": url})
                tool_calls.append(tool_call)
                logger.info(f"✅ 成功创建网页获取工具调用")
            else:
                logger.warning("⚠️ 未找到有效的URL")

        except Exception as e:
            logger.error(f"❌ 创建网页获取工具调用失败: {e}")

    # 通用的新工具自动调用 - 基于检测到的AstrBot工具
    if hasattr(tool_manager, 'detected_astrbot_tools'):
        detected_tools = tool_manager.detected_astrbot_tools.get('astrbot_tools', [])

        for tool_info in detected_tools:
            tool_name = tool_info['name']
            capabilities = tool_info.get('capabilities', {})

            # 跳过已经处理过的工具
            if tool_name in ['gemini_draw', 'reminder']:
                continue

            # 检查是否应该调用AstrBot
            if not capabilities.get('should_call_astrbot', True):
                continue

            # 检查触发关键词
            trigger_keywords = capabilities.get('trigger_keywords', [])
            if any(keyword in content_lower for keyword in trigger_keywords):
                logger.info(f"🆕 检测到新工具触发: {tool_name} (类别: {capabilities.get('category', 'unknown')})")

                try:
                    # 创建通用的AstrBot工具调用
                    from uuid import uuid4
                    import json

                    # 基于工具类别提取参数
                    params = _extract_universal_tool_parameters(tool_name, user_content, capabilities)

                    if params:
                        tool_call_data = {
                            "id": f"call_{uuid4().hex[:8]}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(params)
                            }
                        }

                        # 转换为ToolCall格式
                        from ...models.tool_models import ToolCall
                        tool_call = ToolCall(
                            id=tool_call_data['id'],
                            type=tool_call_data['type'],
                            function=tool_call_data['function']
                        )
                        tool_calls.append(tool_call)
                        logger.info(f"✅ 成功创建新工具调用: {tool_name}")
                        break  # 只创建一个工具调用

                except Exception as e:
                    logger.error(f"❌ 创建新工具调用失败 {tool_name}: {e}")

    return tool_calls


def _extract_universal_tool_parameters(tool_name: str, user_content: str, capabilities: dict) -> dict:
    """通用的工具参数提取函数"""
    import re

    # 清理用户内容
    clean_content = re.sub(r'\[user id:.*?\]', '', user_content, flags=re.IGNORECASE)
    clean_content = re.sub(r'\[.*?nickname:.*?\]', '', clean_content, flags=re.IGNORECASE)
    clean_content = re.sub(r'\s+', ' ', clean_content).strip()

    category = capabilities.get('category', 'unknown')

    # 基于工具类别提取参数
    if category == 'translation':
        # 翻译工具
        # 移除翻译相关词汇
        text = clean_content
        for word in ["翻译", "translate", "转换"]:
            text = text.replace(word, "").strip()

        # 检测目标语言
        target_lang = "英文"  # 默认
        if any(lang in clean_content for lang in ["英文", "english", "英语"]):
            target_lang = "英文"
        elif any(lang in clean_content for lang in ["中文", "chinese", "中国话"]):
            target_lang = "中文"
        elif any(lang in clean_content for lang in ["日文", "japanese", "日语"]):
            target_lang = "日文"

        return {"text": text, "target_language": target_lang}

    elif category == 'weather':
        # 天气工具
        # 提取城市名称
        city = clean_content
        for word in ["天气", "weather", "温度", "气候"]:
            city = city.replace(word, "").strip()

        # 如果没有指定城市，使用默认
        if not city or len(city) < 2:
            city = "北京"

        return {"city": city}

    elif category == 'file_processing':
        # 文件处理工具
        # 查找文件路径或文件名
        file_pattern = r'[^\s]+\.(pdf|doc|docx|txt|xlsx|ppt|pptx)'
        files = re.findall(file_pattern, clean_content, re.IGNORECASE)

        if files:
            return {"file_path": files[0]}
        else:
            # 提取处理内容
            content = clean_content
            for word in ["处理", "分析", "文件", "文档"]:
                content = content.replace(word, "").strip()
            return {"content": content}

    elif category == 'unknown_new_tool':
        # 未知新工具 - 通用参数提取
        # 尝试提取最可能的参数
        params = {}

        # 常见参数名称和提取方式
        if "query" in tool_name.lower() or "search" in tool_name.lower():
            params["query"] = clean_content
        elif "text" in tool_name.lower() or "content" in tool_name.lower():
            params["text"] = clean_content
        elif "message" in tool_name.lower():
            params["message"] = clean_content
        else:
            # 使用工具名称作为参数名
            param_name = tool_name.lower().replace("_", "")
            params[param_name] = clean_content

        return params

    else:
        # 其他类别 - 基本参数提取
        return {"input": clean_content}


def _parse_tool_calls_from_response(response: str, tool_manager: ToolManager) -> List[ToolCall]:
    """从Claude响应中解析工具调用"""
    tool_calls = []

    # 简单的工具调用检测逻辑
    # 这里可以根据需要实现更复杂的解析逻辑
    response_lower = response.lower()

    # 检查是否提到了搜索
    if any(keyword in response_lower for keyword in ["搜索", "search", "查找", "find"]):
        # 尝试提取搜索查询
        import re
        search_patterns = [
            r"搜索[：:]?\s*[\"']([^\"']+)[\"']",
            r"search[：:]?\s*[\"']([^\"']+)[\"']",
            r"查找[：:]?\s*[\"']([^\"']+)[\"']"
        ]

        for pattern in search_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                query = match.group(1)
                tool_call = tool_manager.create_tool_call("web_search", {"query": query})
                tool_calls.append(tool_call)
                break

    # 检查是否提到了网页获取
    if any(keyword in response_lower for keyword in ["网页", "webpage", "url", "链接"]):
        # 尝试提取URL
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, response)
        if urls:
            tool_call = tool_manager.create_tool_call("web_fetch", {"url": urls[0]})
            tool_calls.append(tool_call)

    # 检查是否提到了代码执行
    if any(keyword in response_lower for keyword in ["代码", "code", "执行", "run", "计算"]):
        # 尝试提取代码块
        import re
        code_pattern = r'```(?:python|javascript)?\n(.*?)\n```'
        code_matches = re.findall(code_pattern, response, re.DOTALL)
        if code_matches:
            code = code_matches[0].strip()
            language = "python"  # 默认Python
            if "javascript" in response_lower or "js" in response_lower:
                language = "javascript"

            tool_call = tool_manager.create_tool_call("code_executor", {
                "code": code,
                "language": language
            })
            tool_calls.append(tool_call)

    return tool_calls


def detect_astrbot_tools(openai_request):
    """检测AstrBot所有正在启用的函数工具"""
    logger.info("🔍 开始检测AstrBot的函数工具")

    detected_tools = {
        "total_count": 0,
        "astrbot_tools": [],
        "builtin_tools": [],
        "mcp_tools": [],
        "unknown_tools": []
    }

    if not openai_request.tools:
        logger.info("📋 请求中没有工具定义")
        return detected_tools

    for tool in openai_request.tools:
        if isinstance(tool, dict) and 'function' in tool:
            func = tool['function']
            tool_name = func.get('name', 'unknown')
            tool_description = func.get('description', '无描述')
            tool_parameters = func.get('parameters', {})

            # 分析工具类型和能力
            tool_info = {
                "name": tool_name,
                "description": tool_description,
                "parameters": _extract_parameter_info(tool_parameters),
                "source": _identify_tool_source(tool_name)
            }

            # 添加智能能力分析
            tool_info["capabilities"] = _analyze_tool_capabilities(tool_info)

            # 分类工具
            if tool_info["source"] == "astrbot":
                detected_tools["astrbot_tools"].append(tool_info)
            elif tool_info["source"] == "builtin":
                detected_tools["builtin_tools"].append(tool_info)
            elif tool_info["source"] == "mcp":
                detected_tools["mcp_tools"].append(tool_info)
            else:
                detected_tools["unknown_tools"].append(tool_info)

            detected_tools["total_count"] += 1

    # 记录检测结果
    logger.info(f"🔍 工具检测完成:")
    logger.info(f"  📊 总工具数: {detected_tools['total_count']}")
    logger.info(f"  🤖 AstrBot工具: {len(detected_tools['astrbot_tools'])}")
    logger.info(f"  🔧 内置工具: {len(detected_tools['builtin_tools'])}")
    logger.info(f"  🌐 MCP工具: {len(detected_tools['mcp_tools'])}")
    logger.info(f"  ❓ 未知工具: {len(detected_tools['unknown_tools'])}")

    # 详细列出AstrBot工具
    if detected_tools["astrbot_tools"]:
        logger.info("🤖 AstrBot工具详情:")
        for tool in detected_tools["astrbot_tools"]:
            logger.info(f"  - {tool['name']}: {tool['description']}")
            if tool['parameters']:
                for param_name, param_info in tool['parameters'].items():
                    logger.info(f"    * {param_name} ({param_info['type']}): {param_info['description']}")

    return detected_tools

def _extract_parameter_info(parameters):
    """提取工具参数信息"""
    param_info = {}

    if 'properties' in parameters:
        for param_name, param_def in parameters['properties'].items():
            param_info[param_name] = {
                "type": param_def.get('type', 'unknown'),
                "description": param_def.get('description', '无描述'),
                "required": param_name in parameters.get('required', [])
            }

    return param_info

def _identify_tool_source(tool_name: str) -> str:
    """识别工具来源 - 智能分类系统"""
    # 我们的内置工具（明确已知）
    builtin_tools = {
        "web_fetch", "code_executor", "document_manager", "data_analyzer", "image_analyzer"
    }

    # MCP工具（通常以mcp_开头）
    if tool_name.startswith("mcp_"):
        return "mcp"

    # 我们的内置工具
    if tool_name in builtin_tools:
        return "builtin"

    # 其他所有工具都假设是AstrBot工具（包括新工具）
    # 这样新工具会被自动识别为AstrBot工具
    return "astrbot"

def _auto_extract_keywords_from_description(description: str) -> list:
    """从工具描述中自动提取关键词"""
    import re

    keywords = []
    description_lower = description.lower()

    # 中文关键词提取
    chinese_chars = re.findall(r'[\u4e00-\u9fff]+', description)
    for chars in chinese_chars:
        # 简单的关键词提取（不依赖jieba）
        if len(chars) >= 2:
            keywords.extend([chars[i:i+2] for i in range(len(chars)-1)])

    # 英文关键词提取
    english_words = re.findall(r'[a-zA-Z]+', description_lower)
    keywords.extend([word for word in english_words if len(word) >= 3])

    # 过滤常见无意义词汇
    stop_words = {
        "the", "and", "for", "are", "with", "this", "that", "when", "where", "how",
        "工具", "功能", "可以", "能够", "进行", "使用", "帮助", "支持", "提供"
    }

    filtered_keywords = [kw for kw in keywords if kw not in stop_words and len(kw) >= 2]

    # 去重并返回前10个最相关的关键词
    return list(set(filtered_keywords))[:10]

def _auto_detect_tool_category(tool_name: str, description: str) -> str:
    """基于工具名称和描述自动检测工具类别"""
    name_lower = tool_name.lower()
    desc_lower = description.lower()

    # 定义类别检测规则（可扩展）
    category_rules = {
        "image_generation": {
            "name_keywords": ["draw", "image", "picture", "generate", "create", "paint", "sketch"],
            "desc_keywords": ["图", "画", "生成", "创建", "图片", "图像", "照片", "绘制", "image", "picture", "draw", "generate"]
        },
        "search": {
            "name_keywords": ["search", "find", "query", "lookup"],
            "desc_keywords": ["搜索", "查找", "寻找", "检索", "search", "find", "query", "lookup"]
        },
        "reminder": {
            "name_keywords": ["remind", "alert", "schedule", "timer", "clock"],
            "desc_keywords": ["提醒", "定时", "闹钟", "计划", "remind", "alert", "schedule", "timer"]
        },
        "code_execution": {
            "name_keywords": ["python", "code", "execute", "run", "script", "program"],
            "desc_keywords": ["代码", "执行", "运行", "编程", "脚本", "python", "code", "execute", "run", "script"]
        },
        "translation": {
            "name_keywords": ["translate", "translation", "language"],
            "desc_keywords": ["翻译", "语言", "转换", "translate", "translation", "language"]
        },
        "weather": {
            "name_keywords": ["weather", "climate", "temperature"],
            "desc_keywords": ["天气", "气候", "温度", "weather", "climate", "temperature"]
        },
        "file_processing": {
            "name_keywords": ["file", "document", "pdf", "doc", "excel"],
            "desc_keywords": ["文件", "文档", "处理", "file", "document", "pdf", "doc", "excel"]
        },
        "web_fetch": {
            "name_keywords": ["fetch", "url", "web", "http", "website"],
            "desc_keywords": ["获取", "抓取", "网页", "链接", "fetch", "url", "web", "http"]
        }
    }

    # 计算每个类别的匹配分数
    category_scores = {}

    for category, rules in category_rules.items():
        score = 0

        # 检查工具名称匹配
        for keyword in rules["name_keywords"]:
            if keyword in name_lower:
                score += 3  # 名称匹配权重更高

        # 检查描述匹配
        for keyword in rules["desc_keywords"]:
            if keyword in desc_lower:
                score += 1

        category_scores[category] = score

    # 返回得分最高的类别
    if category_scores:
        best_category = max(category_scores, key=category_scores.get)
        if category_scores[best_category] > 0:
            return best_category

    return "unknown"

def _auto_generate_trigger_keywords(tool_name: str, description: str, category: str) -> list:
    """基于工具信息自动生成触发关键词"""
    keywords = []

    # 从工具名称生成关键词
    name_parts = tool_name.lower().replace("_", " ").split()
    keywords.extend(name_parts)

    # 从描述中提取关键词
    desc_keywords = _auto_extract_keywords_from_description(description)
    keywords.extend(desc_keywords)

    # 基于类别添加通用关键词
    category_keywords = {
        "image_generation": ["生成", "画", "绘制", "创建", "图片", "图像", "照片", "draw", "generate", "create", "image"],
        "search": ["搜索", "搜一下", "查找", "找一下", "search", "find", "lookup"],
        "reminder": ["提醒", "提示", "定时", "闹钟", "remind", "alert", "schedule"],
        "code_execution": ["执行", "运行", "计算", "python", "代码", "execute", "run", "code"],
        "translation": ["翻译", "转换", "translate", "convert"],
        "weather": ["天气", "温度", "气候", "weather", "temperature"],
        "file_processing": ["文件", "文档", "处理", "file", "document", "process"],
        "web_fetch": ["获取", "抓取", "访问", "网页", "fetch", "get", "web"]
    }

    if category in category_keywords:
        keywords.extend(category_keywords[category])

    # 去重并过滤
    unique_keywords = list(set(keywords))
    filtered_keywords = [kw for kw in unique_keywords if len(kw) >= 2]

    return filtered_keywords[:15]  # 限制关键词数量

def _auto_decide_call_strategy(category: str) -> tuple:
    """基于工具类别自动决定调用策略"""

    # 定义调用策略规则
    strategy_rules = {
        # 必须调用AstrBot的工具类别
        "image_generation": (True, False),   # 图片生成 - 调用AstrBot
        "reminder": (True, False),           # 提醒功能 - 调用AstrBot
        "translation": (True, False),        # 翻译功能 - 调用AstrBot
        "weather": (True, False),            # 天气功能 - 调用AstrBot

        # 优先使用我们工具的类别
        "search": (False, True),             # 搜索 - 使用我们的工具
        "code_execution": (False, True),     # 代码执行 - 使用我们的工具
        "web_fetch": (False, True),          # 网页获取 - 使用我们的工具
        "file_processing": (False, True),    # 文件处理 - 使用我们的工具

        # 未知类别 - 保守策略，让AstrBot处理
        "unknown": (True, False)
    }

    return strategy_rules.get(category, (True, False))  # 默认调用AstrBot

def _analyze_tool_capabilities(tool_info) -> dict:
    """分析工具能力，决定调用策略 - 完全自动化"""
    tool_name = tool_info.get('name', '')
    description = tool_info.get('description', '')

    # 自动检测工具类别
    category = _auto_detect_tool_category(tool_name, description)

    # 自动生成触发关键词
    trigger_keywords = _auto_generate_trigger_keywords(tool_name, description, category)

    # 基于类别决定调用策略
    should_call_astrbot, can_use_builtin = _auto_decide_call_strategy(category)

    analysis = {
        "should_call_astrbot": should_call_astrbot,
        "can_use_builtin": can_use_builtin,
        "trigger_keywords": trigger_keywords,
        "category": category
    }

    # 基于工具名称和描述的智能分析
    if any(keyword in tool_name.lower() for keyword in ["draw", "image", "picture", "generate"]):
        if any(keyword in description for keyword in ["图", "画", "生成", "image", "draw"]):
            analysis.update({
                "category": "image_generation",
                "trigger_keywords": ["生成", "画", "绘制", "创建", "图片", "图像", "照片"],
                "should_call_astrbot": True,
                "can_use_builtin": False
            })

    elif any(keyword in tool_name.lower() for keyword in ["remind", "alert", "schedule", "timer"]):
        analysis.update({
            "category": "reminder",
            "trigger_keywords": ["提醒", "提示", "定时", "闹钟", "remind", "alert"],
            "should_call_astrbot": True,
            "can_use_builtin": False
        })

    elif any(keyword in tool_name.lower() for keyword in ["search", "find", "query"]):
        analysis.update({
            "category": "search",
            "trigger_keywords": ["搜索", "搜一下", "查找", "找一下", "search", "find"],
            "should_call_astrbot": False,  # 使用我们的搜索工具
            "can_use_builtin": True
        })

    elif any(keyword in tool_name.lower() for keyword in ["python", "code", "execute", "run"]):
        analysis.update({
            "category": "code_execution",
            "trigger_keywords": ["执行", "运行", "计算", "python", "代码", "code"],
            "should_call_astrbot": False,  # 使用我们的代码执行工具
            "can_use_builtin": True
        })

    elif any(keyword in tool_name.lower() for keyword in ["fetch", "url", "web", "http"]):
        analysis.update({
            "category": "web_fetch",
            "trigger_keywords": ["获取", "抓取", "访问", "网页", "链接", "url"],
            "should_call_astrbot": False,  # 使用我们的网页获取工具
            "can_use_builtin": True
        })

    else:
        # 未知类型的新工具 - 基于描述进一步分析
        if any(keyword in description for keyword in ["文件", "file", "document", "pdf", "doc"]):
            analysis.update({
                "category": "document_processing",
                "trigger_keywords": ["处理", "分析", "文件", "文档"],
                "should_call_astrbot": True,  # 新的文档处理工具，让AstrBot处理
                "can_use_builtin": False
            })

        elif any(keyword in description for keyword in ["天气", "weather", "温度", "climate"]):
            analysis.update({
                "category": "weather",
                "trigger_keywords": ["天气", "温度", "气温", "weather"],
                "should_call_astrbot": True,  # 天气工具，让AstrBot处理
                "can_use_builtin": False
            })

        elif any(keyword in description for keyword in ["翻译", "translate", "语言", "language"]):
            analysis.update({
                "category": "translation",
                "trigger_keywords": ["翻译", "translate", "转换"],
                "should_call_astrbot": True,  # 翻译工具，让AstrBot处理
                "can_use_builtin": False
            })

        else:
            # 完全未知的新工具 - 保守策略：让AstrBot处理
            analysis.update({
                "category": "unknown_new_tool",
                "trigger_keywords": [tool_name.lower()],  # 使用工具名作为触发词
                "should_call_astrbot": True,
                "can_use_builtin": False
            })

    logger.info(f"🔍 工具能力分析 - {tool_name}: {analysis['category']}, AstrBot调用: {analysis['should_call_astrbot']}")
    return analysis

async def _smart_astrbot_tool_call(user_content: str, tool_manager):
    """智能分析用户请求，决定是否调用AstrBot工具 - 支持动态新工具"""
    import re
    logger.info(f"🔍 智能分析用户请求: {user_content[:50]}...")

    # 获取所有检测到的AstrBot工具
    detected_tools = tool_manager.detected_astrbot_tools.get('astrbot_tools', [])

    if not detected_tools:
        logger.info("🔍 没有检测到AstrBot工具")
        return None

    # 遍历所有AstrBot工具，检查是否匹配用户请求
    for tool_info in detected_tools:
        tool_name = tool_info['name']
        capabilities = tool_info.get('capabilities', {})

        # 检查是否应该调用AstrBot
        if not capabilities.get('should_call_astrbot', True):
            continue  # 跳过应该用我们工具处理的

        # 检查触发关键词
        trigger_keywords = capabilities.get('trigger_keywords', [])
        if any(keyword in user_content.lower() for keyword in trigger_keywords):
            logger.info(f"🎯 检测到工具触发: {tool_name} (类别: {capabilities.get('category', 'unknown')})")

            # 创建工具调用
            tool_call = tool_manager.create_astrbot_tool_call(tool_name, user_content)
            if tool_call:
                return tool_call

    # 特殊处理：如果没有匹配到具体工具，但检测到通用模式
    # 尝试匹配最相似的工具
    user_lower = user_content.lower()

    # 图片相关
    if any(word in user_lower for word in ["图", "画", "生成", "创建", "image", "draw"]):
        for tool_info in detected_tools:
            if tool_info.get('capabilities', {}).get('category') == 'image_generation':
                logger.info(f"🎨 通用图片请求匹配到工具: {tool_info['name']}")
                return tool_manager.create_astrbot_tool_call(tool_info['name'], user_content)

    # 提醒相关
    if any(word in user_lower for word in ["提醒", "定时", "闹钟", "remind", "alert"]):
        for tool_info in detected_tools:
            if tool_info.get('capabilities', {}).get('category') == 'reminder':
                logger.info(f"⏰ 通用提醒请求匹配到工具: {tool_info['name']}")
                return tool_manager.create_astrbot_tool_call(tool_info['name'], user_content)

    # 新工具类别的通用匹配
    for tool_info in detected_tools:
        capabilities = tool_info.get('capabilities', {})
        category = capabilities.get('category', '')

        # 对于未知的新工具，如果用户请求包含工具名称，就尝试调用
        if category == 'unknown_new_tool':
            tool_name_lower = tool_info['name'].lower()
            if tool_name_lower in user_lower:
                logger.info(f"🆕 检测到新工具调用请求: {tool_info['name']}")
                return tool_manager.create_astrbot_tool_call(tool_info['name'], user_content)

    logger.info("🔍 未检测到明确的AstrBot工具调用需求")
    return None

def _estimate_tokens(text: str) -> int:
    """估算文本的token数量"""
    if not text:
        return 0
    # 简单估算：中文字符按1个token计算，英文单词按0.75个token计算
    chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
    english_words = len([w for w in text.split() if any(c.isalpha() for c in w)])
    other_chars = len(text) - chinese_chars - sum(len(w) for w in text.split() if any(c.isalpha() for c in w))

    estimated = chinese_chars + int(english_words * 0.75) + int(other_chars * 0.5)
    return max(estimated, len(text.split()))


async def _log_usage_stats(auth_token: str, response: ChatCompletionResponse, model: str):
    """记录使用统计"""
    try:
        from ...services.database import get_database_manager
        db_manager = get_database_manager()

        api_key_record = db_manager.get_api_key_by_key(auth_token)
        if api_key_record:
            db_manager.log_usage(
                user_id=api_key_record.user_id,
                api_key_id=api_key_record.id,
                endpoint="/v1/chat/completions",
                method="POST",
                status_code=200,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                model=model
            )
    except Exception as e:
        logger.warning(f"记录使用统计失败: {e}")


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "service": "smithery-claude-proxy"}


# 注意：异常处理器应该在主应用中定义，而不是在路由中
