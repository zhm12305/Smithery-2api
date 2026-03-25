"""
工具调用相关的数据模型

定义工具定义、工具调用、工具结果等数据结构。
"""

from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field
import json


class ToolParameter(BaseModel):
    """工具参数定义"""
    type: str = Field(description="参数类型")
    description: str = Field(description="参数描述")
    enum: Optional[List[str]] = Field(default=None, description="枚举值")
    default: Optional[Any] = Field(default=None, description="默认值")


class ToolFunction(BaseModel):
    """工具函数定义"""
    name: str = Field(description="函数名称")
    description: str = Field(description="函数描述")
    parameters: Dict[str, Any] = Field(description="函数参数schema")


class ToolDefinition(BaseModel):
    """工具定义模型"""
    type: Literal["function"] = Field(default="function", description="工具类型")
    function: ToolFunction = Field(description="函数定义")


class ToolCall(BaseModel):
    """工具调用模型"""
    id: str = Field(description="工具调用ID")
    type: Literal["function"] = Field(default="function", description="工具类型")
    function: Dict[str, Any] = Field(description="函数调用信息")


class ToolCallResult(BaseModel):
    """工具调用结果模型"""
    tool_call_id: str = Field(description="工具调用ID")
    role: Literal["tool"] = Field(default="tool", description="角色")
    name: str = Field(description="工具名称")
    content: str = Field(description="工具执行结果")


class ToolConfig(BaseModel):
    """工具配置模型"""
    google_search_api_key: str = Field(description="Google搜索API密钥")
    google_search_cx: str = Field(description="Google搜索CX")
    code_execution_enabled: bool = Field(default=True, description="是否启用代码执行")
    code_execution_timeout: int = Field(default=30, description="代码执行超时时间(秒)")
    web_fetch_timeout: int = Field(default=10, description="网页获取超时时间(秒)")
    max_search_results: int = Field(default=5, description="最大搜索结果数")

    # 图片分析配置
    smithery_auth_token: Optional[str] = Field(default=None, description="Smithery.ai认证token")
    smithery_url: str = Field(default="https://smithery.ai", description="Smithery.ai服务地址")
    api_timeout: int = Field(default=60, description="API调用超时时间(秒)")
    image_analysis_enabled: bool = Field(default=True, description="是否启用图片分析功能")
    image_analysis_timeout: int = Field(default=60, description="图片分析超时时间(秒)")
    max_image_size: int = Field(default=10485760, description="最大图片大小(字节)")
    gemini_api_key: Optional[str] = Field(default=None, description="Gemini/OpenAI-compatible vision API key")
    gemini_base_url: Optional[str] = Field(default=None, description="Gemini/OpenAI-compatible vision API base URL")
    supported_image_formats: List[str] = Field(
        default=["jpeg", "jpg", "png", "gif", "webp", "bmp"],
        description="支持的图片格式"
    )


class SearchResult(BaseModel):
    """搜索结果模型"""
    title: str = Field(description="标题")
    link: str = Field(description="链接")
    snippet: str = Field(description="摘要")


class WebFetchResult(BaseModel):
    """网页获取结果模型"""
    url: str = Field(description="网页URL")
    title: str = Field(description="网页标题")
    content: str = Field(description="网页内容(Markdown格式)")
    status_code: int = Field(description="HTTP状态码")


class CodeExecutionResult(BaseModel):
    """代码执行结果模型"""
    success: bool = Field(description="执行是否成功")
    output: str = Field(description="执行输出")
    error: Optional[str] = Field(default=None, description="错误信息")
    execution_time: float = Field(description="执行时间(秒)")


class DocumentInfo(BaseModel):
    """文档信息模型"""
    path: str = Field(description="文档路径")
    title: str = Field(description="文档标题")
    content: str = Field(description="文档内容")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="更新时间")
