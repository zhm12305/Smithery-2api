"""
工具管理服务

管理和执行各种AI助手工具，包括内置工具和 MCP 远程工具。
"""

import logging
import asyncio
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..tools import (
    BaseTool,
    GoogleSearchTool,
    WebFetchTool,
    CodeExecutorTool,
    DocumentManagerTool,
    DataAnalyzerTool,
    ImageAnalyzerTool
)
from ..models.tool_models import ToolDefinition, ToolCall, ToolCallResult, ToolConfig
from ..models.mcp_playground_models import (
    MCPToolDefinition,
    MCPToolCall,
    MCPToolCallResult,
    OpenAITool,
    OpenAIToolFunction
)
from .mcp_playground_client import MCPPlaygroundClient, MCPPlaygroundClientError

logger = logging.getLogger(__name__)


class ToolManager:
    """工具管理器 - 管理内置工具和 MCP 远程工具"""

    def __init__(self, config: Optional[ToolConfig] = None, mcp_client: Optional[MCPPlaygroundClient] = None):
        """
        初始化工具管理器

        Args:
            config: 工具配置
            mcp_client: MCP playground 客户端
        """
        self.config = config
        self.mcp_client = mcp_client
        self.tools: Dict[str, BaseTool] = {}
        self.mcp_tools: Dict[str, MCPToolDefinition] = {}
        self.detected_astrbot_tools = {}  # 存储检测到的AstrBot工具信息
        self._mcp_tools_cache_ttl = 3600  # MCP 工具缓存1小时
        self._last_mcp_refresh = 0
        self._initialize_tools()
    
    def _initialize_tools(self):
        """初始化所有工具"""
        tool_config = {}
        
        if self.config:
            tool_config = {
                "google_search_api_key": self.config.google_search_api_key,
                "google_search_cx": self.config.google_search_cx,
                "code_execution_enabled": self.config.code_execution_enabled,
                "code_execution_timeout": self.config.code_execution_timeout,
                "web_fetch_timeout": self.config.web_fetch_timeout,
                "max_search_results": self.config.max_search_results,
                "smithery_auth_token": getattr(self.config, "smithery_auth_token", None),
                "smithery_url": getattr(self.config, "smithery_url", "https://smithery.ai"),
                "api_timeout": getattr(self.config, "api_timeout", 60),
                "gemini_api_key": getattr(self.config, "gemini_api_key", None),
                "gemini_base_url": getattr(self.config, "gemini_base_url", None)
            }

        # 注册所有工具
        self.tools["web_search"] = GoogleSearchTool(tool_config)
        self.tools["web_fetch"] = WebFetchTool(tool_config)
        self.tools["code_executor"] = CodeExecutorTool(tool_config)
        self.tools["document_manager"] = DocumentManagerTool(tool_config)
        self.tools["data_analyzer"] = DataAnalyzerTool(tool_config)
        self.tools["image_analyzer"] = ImageAnalyzerTool(tool_config)
        
        logger.info(f"Initialized {len(self.tools)} tools: {list(self.tools.keys())}")
    
    def get_available_tools(self) -> List[ToolDefinition]:
        """获取所有可用工具的定义（仅内置工具）"""
        return [tool.get_tool_definition() for tool in self.tools.values()]

    async def get_all_available_tools(self) -> List[ToolDefinition]:
        """获取所有可用工具的定义（包括内置工具和 MCP 工具）"""
        definitions = []

        # 获取内置工具
        definitions.extend(self.get_available_tools())

        # 获取 MCP 工具
        mcp_tools = await self.discover_mcp_tools()
        for mcp_tool in mcp_tools:
            # 构建参数 schema
            parameters = {
                "type": "object",
                "properties": {},
                "required": []
            }

            # 转换 MCP 工具参数
            for param in mcp_tool.parameters:
                param_schema = {
                    "type": param.type.value,
                    "description": param.description or ""
                }
                if param.enum:
                    param_schema["enum"] = param.enum
                if param.default is not None:
                    param_schema["default"] = param.default

                parameters["properties"][param.name] = param_schema
                if param.required:
                    parameters["required"].append(param.name)

            # 转换 MCP 工具为标准工具定义
            from ..models.tool_models import ToolFunction
            tool_def = ToolDefinition(
                type="function",
                function=ToolFunction(
                    name=f"mcp_{mcp_tool.server_id}_{mcp_tool.name}",
                    description=f"[MCP] {mcp_tool.description}",
                    parameters=parameters
                )
            )
            definitions.append(tool_def)

        return definitions

    async def discover_mcp_tools(self, query: str = None) -> List[MCPToolDefinition]:
        """发现 MCP 工具"""
        if not self.mcp_client:
            return []

        import time
        current_time = time.time()

        # 检查缓存是否过期
        if (current_time - self._last_mcp_refresh) < self._mcp_tools_cache_ttl and self.mcp_tools:
            return list(self.mcp_tools.values())

        try:
            # 搜索 MCP 服务器
            search_query = query or "search tool"
            logger.debug(f"开始搜索 MCP 服务器，查询: {search_query}")

            search_result = await self.mcp_client.search_mcp_servers(
                query=search_query,
                filters={"page": 1, "pageSize": 20}
            )

            logger.debug(f"搜索到 {len(search_result.servers)} 个 MCP 服务器")

            # 获取每个服务器的工具
            all_tools = []
            for server in search_result.servers:
                try:
                    logger.debug(f"获取服务器 {server.id} 的工具")
                    server_tools = await self.mcp_client.get_server_tools(server.id)
                    all_tools.extend(server_tools)

                    # 缓存工具
                    for tool in server_tools:
                        tool_key = f"{tool.server_id}_{tool.name}"
                        self.mcp_tools[tool_key] = tool

                    logger.debug(f"服务器 {server.id} 提供 {len(server_tools)} 个工具")

                except Exception as e:
                    logger.warning(f"获取服务器 {server.id} 工具失败: {e}")
                    continue

            self._last_mcp_refresh = current_time
            logger.info(f"成功发现 {len(all_tools)} 个 MCP 工具")

            return all_tools

        except MCPPlaygroundClientError as e:
            logger.warning(f"MCP 工具发现失败: {e}")
            # 不要抛出异常，返回空列表让内置工具继续工作
            return []
        except Exception as e:
            logger.warning(f"MCP 工具发现异常: {e}")
            # 确保任何异常都不会影响内置工具
            return []

    async def refresh_mcp_tools(self) -> None:
        """刷新 MCP 工具缓存"""
        self._last_mcp_refresh = 0
        self.mcp_tools.clear()
        await self.discover_mcp_tools()
    
    def get_tool_by_name(self, name: str) -> Optional[BaseTool]:
        """根据名称获取工具"""
        return self.tools.get(name)
    
    async def execute_tool_call(self, tool_call: ToolCall) -> ToolCallResult:
        """
        执行工具调用（支持内置工具和 MCP 工具）

        Args:
            tool_call: 工具调用对象

        Returns:
            工具调用结果
        """
        function_name = tool_call.function.get("name")
        function_args = tool_call.function.get("arguments", {})

        if isinstance(function_args, str):
            import json
            try:
                function_args = json.loads(function_args)
            except json.JSONDecodeError:
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    role="tool",
                    name=function_name,
                    content=f"Error: Invalid JSON in function arguments: {function_args}"
                )

        # 检查是否是 MCP 工具
        if function_name.startswith("mcp_"):
            return await self.call_mcp_tool(function_name, function_args)

        # 处理内置工具
        tool = self.get_tool_by_name(function_name)
        if not tool:
            return ToolCallResult(
                tool_call_id=tool_call.id,
                role="tool",
                name=function_name,
                content=f"Error: Tool '{function_name}' not found"
            )
        
        try:
            # 执行工具
            logger.info(f"🔧 执行工具 {function_name}，参数: {function_args}")
            result = await tool.safe_execute(**function_args)

            # 格式化结果
            formatted_result = tool.format_result_for_ai(result)
            logger.info(f"✅ 工具 {function_name} 执行成功")

            return ToolCallResult(
                tool_call_id=tool_call.id,
                role="tool",
                name=function_name,
                content=formatted_result
            )
            
        except Exception as e:
            logger.error(f"Error executing tool {function_name}: {e}")
            return ToolCallResult(
                tool_call_id=tool_call.id,
                role="tool",
                name=function_name,
                content=f"Error executing tool: {str(e)}"
            )
    
    async def execute_multiple_tool_calls(self, tool_calls: List[ToolCall]) -> List[ToolCallResult]:
        """
        执行多个工具调用
        
        Args:
            tool_calls: 工具调用列表
            
        Returns:
            工具调用结果列表
        """
        results = []
        
        for tool_call in tool_calls:
            result = await self.execute_tool_call(tool_call)
            results.append(result)
        
        return results
    
    def create_tool_call(self, function_name: str, arguments: Dict[str, Any]) -> ToolCall:
        """
        创建工具调用对象
        
        Args:
            function_name: 函数名称
            arguments: 函数参数
            
        Returns:
            工具调用对象
        """
        return ToolCall(
            id=f"call_{uuid4().hex[:8]}",
            type="function",
            function={
                "name": function_name,
                "arguments": arguments
            }
        )
    
    def is_tool_call_message(self, message: Dict[str, Any]) -> bool:
        """
        检查消息是否包含工具调用
        
        Args:
            message: 消息字典
            
        Returns:
            是否包含工具调用
        """
        return (
            message.get("role") == "assistant" and
            "tool_calls" in message and
            isinstance(message["tool_calls"], list) and
            len(message["tool_calls"]) > 0
        )
    
    def extract_tool_calls_from_message(self, message: Dict[str, Any]) -> List[ToolCall]:
        """
        从消息中提取工具调用
        
        Args:
            message: 消息字典
            
        Returns:
            工具调用列表
        """
        if not self.is_tool_call_message(message):
            return []
        
        tool_calls = []
        for tool_call_data in message["tool_calls"]:
            try:
                tool_call = ToolCall(**tool_call_data)
                tool_calls.append(tool_call)
            except Exception as e:
                logger.error(f"Error parsing tool call: {e}")
                continue
        
        return tool_calls

    async def call_mcp_tool(self, tool_id: str, parameters: Dict[str, Any]) -> ToolCallResult:
        """调用 MCP 工具"""
        if not self.mcp_client:
            return ToolCallResult(
                tool_call_id=str(uuid4()),
                role="tool",
                name=tool_id,
                content="Error: MCP 客户端未配置"
            )

        # 解析工具ID
        if tool_id.startswith("mcp_"):
            parts = tool_id[4:].split("_", 1)
            if len(parts) == 2:
                server_id, tool_name = parts
            else:
                return ToolCallResult(
                    tool_call_id=str(uuid4()),
                    role="tool",
                    name=tool_id,
                    content="Error: 无效的 MCP 工具ID格式"
                )
        else:
            return ToolCallResult(
                tool_call_id=str(uuid4()),
                role="tool",
                name=tool_id,
                content="Error: 不是 MCP 工具ID"
            )

        try:
            # 调用 MCP 工具
            mcp_result = await self.mcp_client.call_mcp_tool(
                server_id=server_id,
                tool_name=tool_name,
                parameters=parameters
            )

            # 转换结果格式
            content = str(mcp_result.result) if mcp_result.success else f"Error: {mcp_result.error}"

            return ToolCallResult(
                tool_call_id=mcp_result.call_id,
                role="tool",
                name=tool_id,
                content=content
            )

        except Exception as e:
            logger.error(f"MCP 工具调用失败: {e}")
            return ToolCallResult(
                tool_call_id=str(uuid4()),
                role="tool",
                name=tool_id,
                content=f"Error: {str(e)}"
            )

    def should_use_tools(self, messages: List[Dict[str, Any]]) -> bool:
        """
        判断是否应该使用工具

        Args:
            messages: 消息列表

        Returns:
            是否应该使用工具
        """
        if not messages:
            return False

        last_message = messages[-1]
        if last_message.get("role") != "user":
            return False

        content = last_message.get("content", "")

        # 首先检查是否包含图片内容
        if self._has_image_content(content):
            logger.info("检测到消息中包含图片，自动启用工具")
            return True

        # 然后检查文本关键词
        content_text = content.lower() if isinstance(content, str) else ""
        if isinstance(content, list):
            # 提取多模态消息中的文本内容
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and "text" in item:
                        text_parts.append(item["text"])
                    elif "text" in item:
                        text_parts.append(item["text"])
            content_text = " ".join(text_parts).lower()

        # 优先检查是否为文本生成任务
        if self._is_text_generation_task(content_text):
            logger.info("检测到文本生成任务，跳过工具调用")
            return False

        # 检查是否包含Cursor IDE/Cline上下文标签，如果有则跳过所有工具
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
            if re.search(pattern, content_text):
                logger.info(f"🚫 检测到Cursor IDE上下文标签，跳过所有工具: {pattern}")
                return False

        # 检查是否包含工具相关的关键词（使用上下文感知过滤）
        logger.info(f"🔍 should_use_tools 检查内容: '{content_text[:200]}...'")
        result = self._has_tool_intent(content_text)
        logger.info(f"🔍 should_use_tools 结果: {result}")
        return result

    def _has_image_content(self, content) -> bool:
        """检查内容是否包含图片"""
        try:
            from ..utils.image_detector import ImageDetector
            return ImageDetector.has_images(content)
        except Exception as e:
            logger.warning(f"图片检测失败: {e}")
            return False

    def _is_text_generation_task(self, content_text: str) -> bool:
        """
        检查是否为文本生成任务

        Args:
            content_text: 用户输入的文本内容（已转为小写）

        Returns:
            是否为文本生成任务
        """
        # 首先检查是否为需要工具的特殊任务
        tool_required_tasks = [
            "json数组格式", "json格式返回", "返回json", "输出json",
            "朋友圈动态生成", "生成朋友圈", "朋友圈助手"
        ]

        for task in tool_required_tasks:
            if task in content_text:
                logger.info(f"检测到需要工具的特殊任务: {task}")
                return False  # 不跳过工具调用

        # 文本生成任务的明确指示词（只包括明确的创作请求）
        text_generation_indicators = [
            # 明确的写作请求
            "写一篇文章", "写一个故事", "帮我写一篇", "写一首诗", "写一段",
            "write an article", "write a story", "write a poem",

            # 明确的文案创作请求
            "帮我写文案", "写个标题", "写个slogan", "写广告语",
            "write a headline", "create a slogan",

            # 明确的内容创作请求（但排除角色扮演）
            "写个小说", "写篇博客", "写日记",
            "write a novel", "write a blog post", "write a diary"
        ]

        # 检查是否包含文本生成指示词
        for indicator in text_generation_indicators:
            if indicator in content_text:
                logger.info(f"检测到文本生成指示词: {indicator}")
                return True

        # 检查是否为助手类任务描述（通常包含"你是"开头）
        if content_text.startswith(("你是", "你扮演", "请扮演", "假设你是")):
            logger.info("检测到角色扮演任务")
            return True

        # 检查是否包含JSON输出要求
        if "json" in content_text and ("返回" in content_text or "输出" in content_text or "格式" in content_text):
            logger.info("检测到JSON格式输出要求")
            return True

        return False

    def _has_tool_intent(self, content_text: str) -> bool:
        """
        检查是否有真实的工具使用意图（上下文感知）

        Args:
            content_text: 用户输入的文本内容（已转为小写）

        Returns:
            是否有工具使用意图
        """
        # 首先检查是否为系统功能描述（不是实际请求）
        system_description_indicators = [
            "这个系统", "该系统", "系统可以", "功能包括", "支持", "能够",
            "this system", "the system", "system can", "features include", "supports", "capable of"
        ]

        for indicator in system_description_indicators:
            if indicator in content_text:
                logger.info(f"检测到系统功能描述指示词: {indicator}")
                return False

        # 检查是否为角色扮演任务（应该让AI处理，不跳过）
        roleplay_indicators = [
            "扮演角色", "你需要扮演", "角色扮演", "朋友圈", "评论回复",
            "role play", "play the role", "character roleplay"
        ]

        for indicator in roleplay_indicators:
            if indicator in content_text:
                logger.info(f"检测到角色扮演任务: {indicator}")
                return False  # 不使用工具，让AI直接处理

        # 明确的工具使用指示词
        explicit_tool_keywords = [
            # 搜索相关 - 明确的搜索意图（包括简单格式）
            "搜索一下", "帮我搜索", "查找一下", "帮我查找", "搜索最新",
            "搜索", "查找", "寻找",  # 添加简单搜索格式
            "search for", "find information", "look up", "search", "find",

            # 图片生成相关 - 明确的图片生成意图
            "生成图片", "生成一张", "画一张", "绘制图片", "创建图片", "制作图片",
            "generate image", "create image", "draw picture", "make image",

            # 网页相关 - 明确的网页操作
            "打开网页", "访问网站", "获取网页", "抓取网页",
            "open webpage", "visit website", "fetch webpage",

            # 代码执行 - 明确的执行意图
            "执行代码", "运行代码", "计算结果", "帮我计算",
            "execute code", "run code", "calculate this",

            # 提醒相关 - 明确的提醒意图
            "设置提醒", "提醒我", "定时提醒", "创建提醒",
            "set reminder", "remind me", "create reminder",

            # 数据分析 - 明确的分析意图
            "分析数据", "处理数据", "统计数据", "数据可视化",
            "analyze data", "process data", "data analysis",

            # 文档操作 - 明确的文档操作
            "保存文档", "创建文件", "下载文件",
            "save document", "create file", "download file"
        ]

        # 检查明确的工具使用意图
        for keyword in explicit_tool_keywords:
            if keyword in content_text:
                logger.info(f"检测到明确工具使用意图: {keyword}")
                return True

        # 检查是否包含具体的搜索查询格式
        import re
        search_patterns = [
            r"搜索[：:]?\s*[\"']([^\"']+)[\"']",
            r"查找[：:]?\s*[\"']([^\"']+)[\"']",
            r"search[：:]?\s*[\"']([^\"']+)[\"']",
            # 添加简单的"搜索 + 内容"格式，支持多行内容
            r"搜索\s*[\u4e00-\u9fff\w\s]{1,50}",  # 搜索 + 中文/英文内容
            r"查找\s*[\u4e00-\u9fff\w\s]{1,50}",  # 查找 + 中文/英文内容
            r"search\s+[\w\s]{1,50}",  # search + 英文内容
            # 添加更多口语化的搜索表达
            r"搜下\s*[\u4e00-\u9fff\w\s]{1,50}",   # 搜下 + 内容
            r"搜个\s*[\u4e00-\u9fff\w\s]{1,50}",   # 搜个 + 内容
            r"搜一搜\s*[\u4e00-\u9fff\w\s]{1,50}", # 搜一搜 + 内容
            r"搜一下\s*[\u4e00-\u9fff\w\s]{1,50}", # 搜一下 + 内容
        ]

        # 排除明显不是搜索请求的内容
        exclude_patterns = [
            r"<user_info>",  # Cursor IDE上下文信息
            r"<rules>",      # 用户规则
            r"<project_layout>",  # 项目布局
            r"分析.*项目",    # 项目分析请求
            r"分析.*代码",    # 代码分析请求
            r"解释.*代码",    # 代码解释请求
        ]

        # 如果包含排除模式，不触发搜索
        for exclude_pattern in exclude_patterns:
            if re.search(exclude_pattern, content_text):
                logger.info(f"检测到排除模式，不触发搜索: {exclude_pattern}")
                return False

        for pattern in search_patterns:
            if re.search(pattern, content_text):
                logger.info(f"检测到搜索查询格式: {pattern}")
                return True

        # 检查图片生成请求格式
        image_generation_patterns = [
            r"生成.*图片",
            r"生成.*图像",
            r"生成.*照片",
            r"画.*图片",
            r"画.*图像",
            r"绘制.*图片",
            r"创建.*图片",
            r"制作.*图片",
            r"generate.*image",
            r"create.*image",
            r"draw.*picture"
        ]

        for pattern in image_generation_patterns:
            if re.search(pattern, content_text):
                logger.info(f"检测到图片生成请求格式: {pattern}")
                return True

        # 检查是否包含代码块
        if "```" in content_text or "执行这段代码" in content_text:
            logger.info("检测到代码块或执行请求")
            return True

        # 检查是否包含数据表格或CSV格式
        lines = content_text.split('\n')
        csv_lines = [line for line in lines if ',' in line and len(line.split(',')) > 2]
        if len(csv_lines) > 1:
            logger.info("检测到数据表格格式")
            return True

        return False


# 全局工具管理器实例
_tool_manager: Optional[ToolManager] = None


def get_tool_manager(config: Optional[ToolConfig] = None, mcp_client: Optional[MCPPlaygroundClient] = None) -> ToolManager:
    """获取工具管理器实例"""
    global _tool_manager

    if _tool_manager is None:
        _tool_manager = ToolManager(config, mcp_client)

    return _tool_manager


def initialize_tool_manager(config: ToolConfig, mcp_client: Optional[MCPPlaygroundClient] = None) -> ToolManager:
    """初始化工具管理器"""
    global _tool_manager
    _tool_manager = ToolManager(config, mcp_client)
    return _tool_manager


# 为ToolManager类添加AstrBot工具支持方法
def _add_astrbot_methods():
    """为ToolManager类添加AstrBot工具支持方法"""

    def set_detected_astrbot_tools(self, detection_result):
        """设置检测到的AstrBot工具信息"""
        self.detected_astrbot_tools = detection_result
        logger.info(f"🤖 已设置AstrBot工具信息，共{detection_result.get('total_count', 0)}个工具")

    def get_astrbot_tool_info(self, tool_name: str):
        """获取特定AstrBot工具的信息"""
        for tool in self.detected_astrbot_tools.get('astrbot_tools', []):
            if tool['name'] == tool_name:
                return tool
        return None

    def should_call_astrbot_directly(self, tool_name: str) -> bool:
        """判断是否应该直接调用AstrBot工具"""
        # 这些工具必须由AstrBot执行，不能用我们的工具替代
        astrbot_exclusive_tools = {
            "gemini_draw",    # 图片生成
            "reminder",       # 提醒功能
        }

        return tool_name in astrbot_exclusive_tools

    def create_astrbot_tool_call(self, tool_name: str, user_request: str):
        """为AstrBot工具创建工具调用指令"""
        tool_info = self.get_astrbot_tool_info(tool_name)
        if not tool_info:
            logger.error(f"❌ 未找到AstrBot工具信息: {tool_name}")
            return None

        # 根据工具类型和用户请求智能提取参数
        parameters = self._extract_astrbot_tool_parameters(tool_name, user_request, tool_info)

        if parameters:
            from uuid import uuid4
            import json

            tool_call = {
                "id": f"call_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(parameters)
                }
            }

            logger.info(f"🤖 创建AstrBot工具调用: {tool_name}, 参数: {parameters}")
            return tool_call

        return None

    def _extract_astrbot_tool_parameters(self, tool_name: str, user_request: str, tool_info):
        """从用户请求中提取AstrBot工具参数"""
        import re

        # 清理用户请求，移除用户ID信息
        clean_request = re.sub(r'\[user id:.*?\]', '', user_request, flags=re.IGNORECASE)
        clean_request = re.sub(r'\[.*?nickname:.*?\]', '', clean_request, flags=re.IGNORECASE)
        clean_request = clean_request.strip()

        if tool_name == "gemini_draw":
            # 图片生成工具
            # 移除生成相关的词汇，保留描述
            prompt = clean_request
            for word in ["生成", "画", "绘制", "创建", "制作", "一张", "图片", "图像", "照片"]:
                prompt = prompt.replace(word, "").strip()

            return {
                "prompt": prompt if prompt else "一张美丽的图片",
                "image_index": 0,  # 默认不使用历史图片
                "reference_bot": False  # 默认不参考之前生成的图片
            }

        elif tool_name == "reminder":
            # 提醒工具
            # 提取提醒内容
            text = clean_request
            for word in ["提醒", "提示", "remind", "alert"]:
                text = text.replace(word, "").strip()

            # 简单的时间提取（可以后续优化）
            datetime_str = None
            time_patterns = [
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',  # 2024-01-01 10:00
                r'明天\s*(\d{1,2}:\d{2})',  # 明天 10:00
                r'(\d{1,2}点)',  # 10点
            ]

            for pattern in time_patterns:
                match = re.search(pattern, clean_request)
                if match:
                    datetime_str = match.group(1)
                    break

            params = {"text": text if text else "提醒事项"}
            if datetime_str:
                params["datetime_str"] = datetime_str

            return params

        elif tool_name == "python_interpreter":
            # Python代码执行工具 - 使用我们自己的代码执行器
            return None  # 返回None表示使用我们的工具

        return None

    # 将方法添加到ToolManager类
    ToolManager.set_detected_astrbot_tools = set_detected_astrbot_tools
    ToolManager.get_astrbot_tool_info = get_astrbot_tool_info
    ToolManager.should_call_astrbot_directly = should_call_astrbot_directly
    ToolManager.create_astrbot_tool_call = create_astrbot_tool_call
    ToolManager._extract_astrbot_tool_parameters = _extract_astrbot_tool_parameters

# 调用函数添加方法
_add_astrbot_methods()
