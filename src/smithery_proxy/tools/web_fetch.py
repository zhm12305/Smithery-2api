"""
网页获取工具

获取网页内容并转换为Markdown格式。
"""

import re
from typing import Any, Dict
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseTool, ToolError
from ..models.tool_models import WebFetchResult


class WebFetchTool(BaseTool):
    """网页获取工具"""
    
    @property
    def name(self) -> str:
        return "web_fetch"
    
    @property
    def description(self) -> str:
        return "Fetch content from a webpage and convert it to Markdown format. Returns the page title and content."
    
    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the webpage to fetch"
                }
            },
            "required": ["url"]
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        获取网页内容
        
        Args:
            url: 网页URL
            
        Returns:
            网页内容字典
        """
        url = kwargs.get("url")
        
        if not url:
            raise ToolError("URL is required")
        
        # 验证URL格式
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ToolError("Invalid URL format")
        
        timeout = self.config.get("web_fetch_timeout", 10)
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                
                # 检测编码
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type.lower():
                    raise ToolError(f"URL does not point to an HTML page. Content-Type: {content_type}")
                
                # 解析HTML
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # 获取页面标题
                title_tag = soup.find('title')
                title = title_tag.get_text().strip() if title_tag else "Untitled"
                
                # 转换为Markdown
                markdown_content = self._html_to_markdown(soup, url)
                
                result = WebFetchResult(
                    url=url,
                    title=title,
                    content=markdown_content,
                    status_code=response.status_code
                )
                
                return result.model_dump()
                
        except httpx.HTTPStatusError as e:
            raise ToolError(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise ToolError(f"Network error: {str(e)}")
        except Exception as e:
            raise ToolError(f"Error fetching webpage: {str(e)}")
    
    def _html_to_markdown(self, soup: BeautifulSoup, base_url: str) -> str:
        """将HTML转换为Markdown格式"""
        
        # 移除脚本和样式标签
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        
        # 获取主要内容
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|article'))
        if main_content:
            soup = main_content
        
        markdown_lines = []
        
        # 处理各种HTML元素
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'ul', 'ol', 'li', 'a', 'img', 'blockquote', 'code', 'pre']):
            
            if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(element.name[1])
                text = element.get_text().strip()
                if text:
                    markdown_lines.append(f"{'#' * level} {text}")
                    markdown_lines.append("")
            
            elif element.name == 'p':
                text = element.get_text().strip()
                if text:
                    markdown_lines.append(text)
                    markdown_lines.append("")
            
            elif element.name in ['ul', 'ol']:
                # 处理列表
                for li in element.find_all('li', recursive=False):
                    text = li.get_text().strip()
                    if text:
                        prefix = "- " if element.name == 'ul' else "1. "
                        markdown_lines.append(f"{prefix}{text}")
                markdown_lines.append("")
            
            elif element.name == 'a':
                text = element.get_text().strip()
                href = element.get('href')
                if text and href:
                    # 转换相对链接为绝对链接
                    if href.startswith('/'):
                        href = urljoin(base_url, href)
                    markdown_lines.append(f"[{text}]({href})")
            
            elif element.name == 'img':
                alt = element.get('alt', '')
                src = element.get('src')
                if src:
                    if src.startswith('/'):
                        src = urljoin(base_url, src)
                    markdown_lines.append(f"![{alt}]({src})")
            
            elif element.name == 'blockquote':
                text = element.get_text().strip()
                if text:
                    lines = text.split('\n')
                    for line in lines:
                        if line.strip():
                            markdown_lines.append(f"> {line.strip()}")
                    markdown_lines.append("")
            
            elif element.name == 'code':
                text = element.get_text()
                markdown_lines.append(f"`{text}`")
            
            elif element.name == 'pre':
                text = element.get_text()
                markdown_lines.append("```")
                markdown_lines.append(text)
                markdown_lines.append("```")
                markdown_lines.append("")
        
        # 清理多余的空行
        result = []
        prev_empty = False
        for line in markdown_lines:
            if line.strip() == "":
                if not prev_empty:
                    result.append("")
                prev_empty = True
            else:
                result.append(line)
                prev_empty = False
        
        return "\n".join(result).strip()
    
    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """格式化网页内容供AI使用"""
        if not result["success"]:
            return f"Failed to fetch webpage: {result['error']}"
        
        data = result["result"]
        content = data["content"]
        
        # 限制内容长度以避免过长
        if len(content) > 8000:
            content = content[:8000] + "\n\n[Content truncated...]"
        
        return f"**{data['title']}**\nURL: {data['url']}\n\n{content}"
