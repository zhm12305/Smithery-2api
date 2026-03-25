"""
MCP格式的数据模型

定义与Model Context Protocol兼容的消息模型。
"""

from typing import Any, Dict, List, Optional, Union
from enum import Enum

from pydantic import BaseModel, Field


class MCPRole(str, Enum):
    """MCP消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MCPContentType(str, Enum):
    """MCP内容类型"""
    TEXT = "text"
    IMAGE = "image"


class MCPTextContent(BaseModel):
    """MCP文本内容"""
    type: MCPContentType = MCPContentType.TEXT
    text: str = Field(description="文本内容")


class MCPImageContent(BaseModel):
    """MCP图片内容"""
    type: MCPContentType = MCPContentType.IMAGE
    data: str = Field(description="图片数据(base64)")
    mimeType: str = Field(description="MIME类型")


MCPContent = Union[MCPTextContent, MCPImageContent]


class MCPMessage(BaseModel):
    """MCP消息模型"""
    role: MCPRole = Field(description="消息角色")
    content: Union[str, List[MCPContent]] = Field(description="消息内容")


class MCPSamplingParams(BaseModel):
    """MCP采样参数"""
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="采样温度"
    )
    top_p: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="核采样参数"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        gt=0,
        description="最大生成token数"
    )
    stop_sequences: Optional[List[str]] = Field(
        default=None,
        description="停止序列"
    )


class MCPCreateMessageRequest(BaseModel):
    """MCP创建消息请求"""
    messages: List[MCPMessage] = Field(description="消息列表")
    model_preferences: Optional[Dict[str, Any]] = Field(
        default=None,
        description="模型偏好设置"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="系统提示"
    )
    include_context: Optional[str] = Field(
        default=None,
        description="包含的上下文"
    )
    sampling: Optional[MCPSamplingParams] = Field(
        default=None,
        description="采样参数"
    )


class MCPCreateMessageResult(BaseModel):
    """MCP创建消息结果"""
    role: MCPRole = Field(description="响应角色")
    content: Union[str, List[MCPContent]] = Field(description="响应内容")
    model: str = Field(description="使用的模型")
    stop_reason: Optional[str] = Field(
        default=None,
        description="停止原因"
    )


class MCPToolCall(BaseModel):
    """MCP工具调用"""
    name: str = Field(description="工具名称")
    arguments: Dict[str, Any] = Field(description="工具参数")


class MCPToolResult(BaseModel):
    """MCP工具结果"""
    content: List[MCPContent] = Field(description="工具执行结果")
    is_error: bool = Field(default=False, description="是否为错误")


class MCPResource(BaseModel):
    """MCP资源"""
    uri: str = Field(description="资源URI")
    name: str = Field(description="资源名称")
    description: Optional[str] = Field(default=None, description="资源描述")
    mime_type: Optional[str] = Field(default=None, description="MIME类型")


class MCPResourceContent(BaseModel):
    """MCP资源内容"""
    uri: str = Field(description="资源URI")
    mime_type: Optional[str] = Field(default=None, description="MIME类型")
    text: Optional[str] = Field(default=None, description="文本内容")
    blob: Optional[str] = Field(default=None, description="二进制内容(base64)")


class MCPError(BaseModel):
    """MCP错误"""
    code: int = Field(description="错误代码")
    message: str = Field(description="错误消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="错误数据")


class MCPConnectionParams(BaseModel):
    """MCP连接参数"""
    server_url: str = Field(description="服务器URL")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    timeout: int = Field(default=30, description="超时时间")
    retry_attempts: int = Field(default=3, description="重试次数")
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="额外请求头"
    )
