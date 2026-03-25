"""
Google搜索工具

使用Google Custom Search API进行网络搜索。
"""

import json
import logging
from typing import Any, Dict, List

import httpx

from .base import BaseTool, ToolError
from ..models.tool_models import SearchResult

logger = logging.getLogger(__name__)


class GoogleSearchTool(BaseTool):
    """Google搜索工具"""
    
    @property
    def name(self) -> str:
        return "web_search"
    
    @property
    def description(self) -> str:
        return "Search the web for information using Google Custom Search API. Returns results with titles, links, and snippets."
    
    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to send to Google"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-10)",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行Google搜索
        
        Args:
            query: 搜索查询
            num_results: 结果数量 (默认5)
            
        Returns:
            搜索结果字典
        """
        query = kwargs.get("query")
        num_results = kwargs.get("num_results", 5)
        
        if not query:
            raise ToolError("Search query is required")
        
        # 从配置获取API密钥和CX
        api_key = self.config.get("google_search_api_key")
        cx = self.config.get("google_search_cx")
        
        if not api_key or not cx:
            raise ToolError("Google Search API key and CX are required in configuration")
        
        # 构建请求URL
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": query,
            "num": min(num_results, 10)  # Google API最多返回10个结果
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()

                # 解析搜索结果
                results = []
                for item in data.get("items", []):
                    result = SearchResult(
                        title=item.get("title", ""),
                        link=item.get("link", ""),
                        snippet=item.get("snippet", "")
                    )
                    results.append(result.model_dump())

                return {
                    "query": query,
                    "total_results": len(results),
                    "results": results
                }

        except httpx.HTTPStatusError as e:
            # Google API失败时，返回模拟结果而不是抛出错误
            status_code = getattr(e.response, 'status_code', 'unknown')
            logger.warning(f"Google Search API error: {status_code} - {str(e)}, using fallback")
            return self._create_fallback_results(query, num_results)
        except httpx.RequestError as e:
            logger.warning(f"Network error during search: {str(e)}, using fallback")
            return self._create_fallback_results(query, num_results)
        except Exception as e:
            logger.warning(f"Unexpected error during search: {str(e)}, using fallback")
            return self._create_fallback_results(query, num_results)

    def _create_fallback_results(self, query: str, num_results: int) -> Dict[str, Any]:
        """创建备用搜索结果"""
        logger.info(f"Creating fallback search results for query: {query}")

        # 创建一些通用的搜索结果
        fallback_results = [
            {
                "title": f"搜索建议：{query}",
                "link": "https://www.google.com/search?q=" + query.replace(" ", "+"),
                "snippet": f"搜索API暂时不可用。建议您直接访问搜索引擎查询'{query}'获取最新信息。"
            },
            {
                "title": f"{query} - 备用搜索",
                "link": "https://www.bing.com/search?q=" + query.replace(" ", "+"),
                "snippet": f"您可以通过其他搜索引擎查找关于'{query}'的详细资料和相关内容。"
            },
            {
                "title": f"{query} - 多引擎搜索",
                "link": "https://duckduckgo.com/?q=" + query.replace(" ", "+"),
                "snippet": f"建议使用多个搜索引擎来获取关于'{query}'的全面信息和不同视角。"
            }
        ]

        # 限制结果数量
        limited_results = fallback_results[:min(num_results, len(fallback_results))]

        return {
            "query": query,
            "total_results": len(limited_results),
            "results": limited_results
        }
    
    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """格式化搜索结果供AI使用 - 提供详细数据让AI进行智能总结"""
        if not result["success"]:
            return f"搜索失败: {result['error']}"

        search_data = result["result"]
        query = search_data["query"]
        results = search_data["results"]

        if not results:
            return f"没有找到关于'{query}'的搜索结果"

        # 返回详细的结构化搜索结果，让AI进行智能总结和分析
        formatted_results = [f"我已经为您搜索了'{query}'，找到了以下详细信息："]

        for i, item in enumerate(results, 1):
            title = item['title']
            url = item['link']
            snippet = item['snippet']

            formatted_results.append(f"\n【搜索结果 {i}】")
            formatted_results.append(f"标题: {title}")
            formatted_results.append(f"链接: {url}")
            formatted_results.append(f"详细描述: {snippet}")
            formatted_results.append("")  # 空行分隔

        # 添加详细的指导性文本，确保AI包含所有链接和详细描述
        formatted_results.append(f"请根据以上搜索结果，为用户提供关于'{query}'的详细总结和分析。")
        formatted_results.append("")
        formatted_results.append("⚠️ 重要要求 - 必须严格遵守:")
        formatted_results.append("1. 🔗 必须在回答中包含所有搜索结果的完整链接URL")
        formatted_results.append("2. 📝 必须详细描述每个搜索结果的内容和价值")
        formatted_results.append("3. 🎭 保持角色的说话风格和语气")
        formatted_results.append("4. 💡 提供有价值的总结和见解")
        formatted_results.append("5. 📋 按照以下格式组织回答:")
        formatted_results.append("   - 开场白（角色风格）")
        formatted_results.append("   - 详细介绍每个搜索结果（包含链接和描述）")
        formatted_results.append("   - 总结分析（角色风格）")
        formatted_results.append("")
        formatted_results.append("示例格式:")
        formatted_results.append("🌐 官方网站: https://www.nvidia.com/en-us/")
        formatted_results.append("📖 详细介绍: [对该网站内容的详细描述]")

        return "\n".join(formatted_results)
