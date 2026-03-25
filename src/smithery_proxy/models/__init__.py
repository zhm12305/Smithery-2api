"""
数据模型模块

包含OpenAI和MCP格式的数据模型定义。
"""

from .openai_models import (
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamResponse,
    ChatCompletionChoice,
    ChatCompletionStreamChoice,
    ChatCompletionUsage,
    ErrorResponse,
    ErrorDetail,
)

from .mcp_models import (
    MCPMessage,
    MCPCreateMessageRequest,
    MCPCreateMessageResult,
    MCPSamplingParams,
    MCPToolCall,
    MCPToolResult,
    MCPResource,
    MCPResourceContent,
    MCPError,
    MCPConnectionParams,
    MCPRole,
    MCPContentType,
    MCPTextContent,
    MCPImageContent,
)

__all__ = [
    # OpenAI models
    "ChatMessage",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatCompletionStreamResponse",
    "ChatCompletionChoice",
    "ChatCompletionStreamChoice",
    "ChatCompletionUsage",
    "ErrorResponse",
    "ErrorDetail",
    # MCP models
    "MCPMessage",
    "MCPCreateMessageRequest",
    "MCPCreateMessageResult",
    "MCPSamplingParams",
    "MCPToolCall",
    "MCPToolResult",
    "MCPResource",
    "MCPResourceContent",
    "MCPError",
    "MCPConnectionParams",
    "MCPRole",
    "MCPContentType",
    "MCPTextContent",
    "MCPImageContent",
]
