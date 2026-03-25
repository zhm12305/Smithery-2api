"""
MCP Playground 客户端

负责与 Smithery.ai playground 端点交互，实现 MCP 服务器搜索和工具调用。
"""

import json
import logging
import re
import time
from typing import Dict, List, Optional, Any
from uuid import uuid4

import httpx

from ..config import Settings
from ..models.mcp_playground_models import (
    MCPServerSearchRequest,
    MCPServerSearchResponse,
    MCPServerInfo,
    MCPToolDefinition,
    MCPToolCall,
    MCPToolCallResult,
    MCPServerActionRequest,
    MCPServerActionResponse,
    MCPPagination
)

logger = logging.getLogger(__name__)


class MCPPlaygroundClientError(Exception):
    """MCP Playground 客户端错误"""
    pass


class MCPPlaygroundClient:
    """MCP Playground 客户端类"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._http_client: Optional[httpx.AsyncClient] = None
        self._server_cache: Dict[str, MCPServerInfo] = {}
        self._tools_cache: Dict[str, List[MCPToolDefinition]] = {}
        
    async def initialize(self) -> None:
        """初始化客户端"""
        client_kwargs = {"timeout": httpx.Timeout(30.0)}
        self._http_client = httpx.AsyncClient(**client_kwargs)
        logger.info("MCP Playground 客户端初始化完成")
    
    async def close(self) -> None:
        """关闭客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def search_mcp_servers(
        self, 
        query: str, 
        filters: Optional[Dict[str, Any]] = None,
        pagination: Optional[MCPPagination] = None
    ) -> MCPServerSearchResponse:
        """搜索 MCP 服务器"""
        if not self._http_client:
            raise MCPPlaygroundClientError("客户端未初始化")
        
        if filters is None:
            filters = {"page": 1, "pageSize": 5}
        
        if pagination:
            filters.update({
                "page": pagination.page,
                "pageSize": pagination.page_size
            })
        
        # 构建 Server Action 请求
        action_data = [query, filters]
        
        try:
            # 使用正确的Next.js Server Action格式
            endpoint = f"{self.settings.smithery_url}/playground"

            # 构建Next.js Server Action请求体
            # 格式: [query_string, {page: number, pageSize: number}]
            server_action_body = [
                f"{query} is:deployed is:remote",
                {
                    "page": 1,
                    "pageSize": 10
                }
            ]

            logger.info(f"🔍 调用Smithery Server Action: {endpoint}")
            logger.info(f"🔍 请求体: {server_action_body}")

            response = await self._http_client.post(
                endpoint,
                content=json.dumps(server_action_body),
                headers=self._get_playground_headers(),
                timeout=30.0
            )

            logger.info(f"🔍 Server Action响应状态码: {response.status_code}")
            logger.info(f"🔍 响应内容类型: {response.headers.get('content-type', '')}")
            
            if response.status_code == 200:
                # 解析 RSC 响应
                parsed_data = await self._parse_rsc_response(response.text)
                
                # 转换为标准格式
                servers = []
                if "servers" in parsed_data:
                    for server_data in parsed_data["servers"]:
                        try:
                            server = MCPServerInfo(**server_data)
                            servers.append(server)
                            # 缓存服务器信息
                            self._server_cache[server.id] = server
                        except Exception as e:
                            logger.warning(f"解析服务器信息失败: {e}")
                            continue
                
                return MCPServerSearchResponse(
                    servers=servers,
                    pagination=parsed_data.get("pagination", {})
                )
            else:
                logger.error(f"MCP搜索请求失败: {response.status_code}, 响应内容: {response.text[:200]}")
                raise MCPPlaygroundClientError(f"搜索请求失败: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"MCP 服务器搜索请求失败: {e}")
            raise MCPPlaygroundClientError(f"网络请求失败: {e}")
        except Exception as e:
            logger.error(f"MCP 服务器搜索失败: {e}")
            raise MCPPlaygroundClientError(f"搜索失败: {e}")
    
    async def get_server_info(self, server_id: str) -> Optional[MCPServerInfo]:
        """获取服务器信息"""
        # 先检查缓存
        if server_id in self._server_cache:
            return self._server_cache[server_id]
        
        # 如果缓存中没有，尝试通过搜索获取
        try:
            # 使用服务器ID作为查询条件
            search_result = await self.search_mcp_servers(
                query=server_id,
                filters={"page": 1, "pageSize": 10}
            )
            
            for server in search_result.servers:
                if server.id == server_id:
                    return server
            
            return None
            
        except Exception as e:
            logger.error(f"获取服务器信息失败: {e}")
            return None
    
    async def get_server_tools(self, server_id: str) -> List[MCPToolDefinition]:
        """获取服务器的工具列表"""
        # 检查缓存
        if server_id in self._tools_cache:
            return self._tools_cache[server_id]
        
        # 获取服务器信息
        server_info = await self.get_server_info(server_id)
        if not server_info:
            logger.warning(f"未找到服务器: {server_id}")
            return []
        
        # 根据服务器类型和名称推断可用工具
        tools = self._infer_server_tools(server_info)
        
        # 缓存工具列表
        self._tools_cache[server_id] = tools
        
        return tools
    
    def _infer_server_tools(self, server_info: MCPServerInfo) -> List[MCPToolDefinition]:
        """根据服务器信息推断可用工具"""
        tools = []
        
        # 根据服务器名称和描述推断工具
        name_lower = server_info.display_name.lower()
        desc_lower = server_info.description.lower()
        
        if "google" in name_lower and "search" in name_lower:
            if "scholar" in name_lower:
                # Google Scholar 搜索工具
                tools.append(MCPToolDefinition(
                    name="search_papers",
                    description="搜索学术论文",
                    parameters=[],
                    server_id=server_info.id,
                    server_name=server_info.display_name
                ))
            else:
                # 普通 Google 搜索工具
                tools.append(MCPToolDefinition(
                    name="web_search",
                    description="网页搜索",
                    parameters=[],
                    server_id=server_info.id,
                    server_name=server_info.display_name
                ))
        
        elif "serper" in name_lower:
            # Serper 搜索工具
            tools.append(MCPToolDefinition(
                name="serper_search",
                description="Serper API 搜索",
                parameters=[],
                server_id=server_info.id,
                server_name=server_info.display_name
            ))
        
        elif "brave" in name_lower:
            # Brave 搜索工具
            tools.append(MCPToolDefinition(
                name="brave_search",
                description="Brave 搜索引擎",
                parameters=[],
                server_id=server_info.id,
                server_name=server_info.display_name
            ))
        
        # 如果没有推断出具体工具，添加通用工具
        if not tools:
            tools.append(MCPToolDefinition(
                name="execute",
                description=f"执行 {server_info.display_name} 功能",
                parameters=[],
                server_id=server_info.id,
                server_name=server_info.display_name
            ))
        
        return tools
    
    async def call_mcp_tool(
        self, 
        server_id: str, 
        tool_name: str, 
        parameters: Dict[str, Any]
    ) -> MCPToolCallResult:
        """调用 MCP 工具"""
        call_id = str(uuid4())
        start_time = time.time()
        
        try:
            # 获取服务器信息
            server_info = await self.get_server_info(server_id)
            if not server_info:
                return MCPToolCallResult(
                    call_id=call_id,
                    success=False,
                    error=f"未找到服务器: {server_id}"
                )
            
            # 模拟工具调用（实际实现需要根据具体的 MCP 协议）
            # 这里先返回模拟结果
            result = await self._simulate_tool_call(server_info, tool_name, parameters)
            
            execution_time = time.time() - start_time
            
            return MCPToolCallResult(
                call_id=call_id,
                success=True,
                result=result,
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"MCP 工具调用失败: {e}")
            
            return MCPToolCallResult(
                call_id=call_id,
                success=False,
                error=str(e),
                execution_time=execution_time
            )
    
    async def _simulate_tool_call(
        self,
        server_info: MCPServerInfo,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> str:
        """模拟工具调用（临时实现）"""
        # 这是一个临时实现，实际应该调用真正的 MCP 服务器
        query = parameters.get("query", parameters.get("q", parameters.get("search_query", "")))

        if "search" in tool_name.lower() or "google" in server_info.display_name.lower():
            # 模拟搜索结果
            if "scholar" in server_info.display_name.lower():
                return f"""学术搜索结果 (使用 {server_info.display_name}):

查询: "{query}"

找到以下学术论文:
1. 《人工智能在自然语言处理中的应用》 - 作者: 张三等
   摘要: 本文探讨了人工智能技术在自然语言处理领域的最新进展...

2. 《深度学习模型优化技术研究》 - 作者: 李四等
   摘要: 研究了深度学习模型的优化方法，提出了新的训练策略...

3. 《机器学习在数据分析中的应用》 - 作者: 王五等
   摘要: 分析了机器学习算法在大数据分析中的实际应用效果...

注: 这是模拟结果，实际使用时会调用真实的学术搜索API。"""
            else:
                return f"""网页搜索结果 (使用 {server_info.display_name}):

查询: "{query}"

搜索结果:
1. 相关网页标题1 - https://example1.com
   描述: 这是第一个相关搜索结果的描述信息...

2. 相关网页标题2 - https://example2.com
   描述: 这是第二个相关搜索结果的描述信息...

3. 相关网页标题3 - https://example3.com
   描述: 这是第三个相关搜索结果的描述信息...

注: 这是模拟结果，实际使用时会调用真实的搜索API。"""
        else:
            return f"""工具执行结果 (使用 {server_info.display_name}):

工具: {tool_name}
参数: {parameters}

执行成功，返回模拟结果数据。

注: 这是模拟结果，实际使用时会调用真实的MCP服务器。"""
    
    def _get_playground_headers(self) -> Dict[str, str]:
        """获取 playground 请求头 - Next.js Server Action格式"""
        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Accept": "text/x-component",
            "Next-Action": "602668e22080898ee405d5e1efc94d027efa749d49",  # 更新至2025-10-05最新ID
            "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(main)%22%2C%7B%22children%22%3A%5B%22playground%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%2Ctrue%5D",
            "Referer": f"{self.settings.smithery_url}/playground",
            "Origin": self.settings.smithery_url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Sec-Ch-Ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }

        # 添加认证Cookie（如果有的话）
        if self.settings.smithery_auth_token:
            headers["Cookie"] = f"sb-spjawbfpwezjfmicopsl-auth-token={self.settings.smithery_auth_token}"

        return headers
    
    async def _parse_rsc_response(self, response_text: str) -> Dict[str, Any]:
        """解析 RSC (React Server Components) 响应格式"""
        try:
            # 记录原始响应用于调试
            logger.debug(f"原始 RSC 响应长度: {len(response_text)}")

            servers = []
            
            # RSC 响应是多行格式，每行以数字+冒号开头
            lines = response_text.strip().split('\n')
            
            for line_idx, line in enumerate(lines):
                # 跳过空行
                if not line.strip():
                    continue
                
                # 提取行号后的内容
                if ':' not in line:
                    continue
                    
                try:
                    # 分离行号和JSON内容
                    # 格式: "10:["$","div",null,{...}]"
                    colon_idx = line.index(':')
                    json_content = line[colon_idx+1:]
                    
                    # 尝试解析JSON
                    data = json.loads(json_content)
                    
                    # 递归查找服务器数据
                    found_servers = self._extract_servers_from_data(data)
                    if found_servers:
                        servers.extend(found_servers)
                        logger.debug(f"从第 {line_idx} 行提取到 {len(found_servers)} 个服务器")
                        
                except (json.JSONDecodeError, ValueError) as e:
                    # 跳过无法解析的行
                    continue
            
            if servers:
                logger.info(f"✅ 成功从 RSC 响应中提取到 {len(servers)} 个服务器")
                return {
                    "servers": servers,
                    "pagination": {
                        "currentPage": 1,
                        "pageSize": len(servers),
                        "totalPages": 1,
                        "totalCount": len(servers)
                    }
                }
            else:
                logger.warning("未从 RSC 响应中找到服务器数据")
                return {
                    "servers": [],
                    "pagination": {
                        "currentPage": 1,
                        "pageSize": 0,
                        "totalPages": 0,
                        "totalCount": 0
                    }
                }

        except Exception as e:
            logger.error(f"RSC 响应解析异常: {e}")
            logger.debug(f"响应内容前1000字符: {response_text[:1000]}...")
            return {"servers": [], "pagination": {"currentPage": 1, "pageSize": 0, "totalPages": 0, "totalCount": 0}}
    
    def _extract_servers_from_data(self, data: Any) -> List[Dict[str, Any]]:
        """递归从数据结构中提取服务器信息"""
        servers = []
        
        if isinstance(data, dict):
            # 检查是否是服务器对象
            if self._is_server_object(data):
                servers.append(data)
            else:
                # 递归检查字典的所有值
                for value in data.values():
                    servers.extend(self._extract_servers_from_data(value))
                    
        elif isinstance(data, list):
            # 递归检查列表的所有元素
            for item in data:
                servers.extend(self._extract_servers_from_data(item))
        
        return servers
    
    def _is_server_object(self, obj: Dict[str, Any]) -> bool:
        """判断对象是否是MCP服务器对象"""
        # 服务器对象应该包含这些关键字段
        required_fields = {'id', 'qualifiedName', 'displayName'}
        return all(field in obj for field in required_fields)

    def _extract_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """从文本中提取所有可能的 JSON 对象"""
        json_objects = []

        # 查找所有可能的 JSON 对象
        brace_count = 0
        start_pos = -1

        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_pos = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_pos != -1:
                    # 找到一个完整的 JSON 对象
                    json_str = text[start_pos:i+1]
                    try:
                        json_obj = json.loads(json_str)
                        json_objects.append(json_obj)
                    except json.JSONDecodeError:
                        pass  # 忽略无效的 JSON
                    start_pos = -1

        return json_objects
