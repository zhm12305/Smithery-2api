"""
MCP Playground 模型定义

定义与 Smithery.ai playground MCP 服务器交互相关的数据模型。
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, field_validator


class MCPPagination(BaseModel):
    """MCP 分页参数"""
    page: int = Field(default=1, description="页码")
    page_size: int = Field(default=5, description="每页大小", alias="pageSize")

    class Config:
        populate_by_name = True


class MCPServerSearchRequest(BaseModel):
    """MCP 服务器搜索请求"""
    query: str = Field(description="搜索查询")
    filters: Dict[str, Any] = Field(default_factory=dict, description="搜索过滤器")
    pagination: MCPPagination = Field(default_factory=MCPPagination, description="分页参数")


class MCPServerInfo(BaseModel):
    """MCP 服务器信息"""
    id: str = Field(description="服务器ID")
    qualified_name: str = Field(description="限定名称", alias="qualifiedName")
    display_name: str = Field(description="显示名称", alias="displayName")
    description: str = Field(description="描述")
    created_at: datetime = Field(description="创建时间", alias="createdAt")
    homepage: Optional[str] = Field(default=None, description="主页")
    verified: bool = Field(default=False, description="是否验证")
    use_count: int = Field(default=0, description="使用次数", alias="useCount")
    bug_report_count: Optional[int] = Field(default=0, description="错误报告数", alias="bugReportCount")
    error_count: Optional[int] = Field(default=0, description="错误数", alias="errorCount")
    adjusted_error_rate: Optional[float] = Field(default=0.0, description="调整后错误率", alias="adjustedErrorRate")
    is_deployed: bool = Field(default=False, description="是否部署", alias="isDeployed")
    is_new: bool = Field(default=False, description="是否新服务器", alias="isNew")
    remote: bool = Field(default=False, description="是否远程")
    icon_url: Optional[str] = Field(default=None, description="图标URL", alias="iconUrl")

    @field_validator('remote', 'is_deployed', 'is_new', 'verified', mode='before')
    @classmethod
    def parse_boolean_fields(cls, v):
        """处理布尔字段的 None 值"""
        if v is None:
            return False
        return bool(v)

    @field_validator('created_at', mode='before')
    @classmethod
    def parse_created_at(cls, v):
        """解析 Smithery.ai 特殊格式的日期时间"""
        if isinstance(v, str):
            # 处理 Smithery.ai 的特殊日期格式 $D2025-05-17T16:09:55.148Z
            if v.startswith('$D'):
                v = v[2:]  # 移除 $D 前缀
            # 尝试解析 ISO 格式
            try:
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                # 如果解析失败，返回当前时间
                return datetime.now()
        return v

    class Config:
        populate_by_name = True


class MCPServerSearchResponse(BaseModel):
    """MCP 服务器搜索响应"""
    servers: List[MCPServerInfo] = Field(description="服务器列表")
    pagination: Dict[str, Any] = Field(description="分页信息")


class MCPToolParameterType(str, Enum):
    """MCP 工具参数类型"""
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class MCPToolParameter(BaseModel):
    """MCP 工具参数定义"""
    name: str = Field(description="参数名称")
    type: MCPToolParameterType = Field(description="参数类型")
    description: Optional[str] = Field(default=None, description="参数描述")
    required: bool = Field(default=False, description="是否必需")
    default: Optional[Any] = Field(default=None, description="默认值")
    enum: Optional[List[Any]] = Field(default=None, description="枚举值")


class MCPToolDefinition(BaseModel):
    """MCP 工具定义"""
    name: str = Field(description="工具名称")
    description: str = Field(description="工具描述")
    parameters: List[MCPToolParameter] = Field(default_factory=list, description="参数列表")
    server_id: str = Field(description="所属服务器ID")
    server_name: str = Field(description="服务器名称")


class MCPToolCall(BaseModel):
    """MCP 工具调用请求"""
    server_id: str = Field(description="服务器ID")
    tool_name: str = Field(description="工具名称")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="调用参数")
    call_id: Optional[str] = Field(default=None, description="调用ID")


class MCPToolCallResult(BaseModel):
    """MCP 工具调用结果"""
    call_id: str = Field(description="调用ID")
    success: bool = Field(description="是否成功")
    result: Optional[Any] = Field(default=None, description="调用结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    execution_time: Optional[float] = Field(default=None, description="执行时间(秒)")


class MCPServerActionRequest(BaseModel):
    """MCP Server Action 请求格式"""
    action_data: List[Any] = Field(description="Server Action 数据")
    
    def to_payload(self) -> List[Any]:
        """转换为 Next.js Server Action 载荷格式"""
        return self.action_data


class MCPServerActionResponse(BaseModel):
    """MCP Server Action 响应格式"""
    raw_response: str = Field(description="原始响应")
    parsed_data: Optional[Dict[str, Any]] = Field(default=None, description="解析后的数据")
    
    @classmethod
    def from_rsc_response(cls, response_text: str) -> "MCPServerActionResponse":
        """从 RSC 响应创建实例"""
        return cls(
            raw_response=response_text,
            parsed_data=None  # 将在解析器中填充
        )


class OpenAIToolFunction(BaseModel):
    """OpenAI 工具函数定义"""
    name: str = Field(description="函数名称")
    description: str = Field(description="函数描述")
    parameters: Dict[str, Any] = Field(description="参数 JSON Schema")


class OpenAITool(BaseModel):
    """OpenAI 工具定义"""
    type: str = Field(default="function", description="工具类型")
    function: OpenAIToolFunction = Field(description="函数定义")


class OpenAIToolCall(BaseModel):
    """OpenAI 工具调用"""
    id: str = Field(description="调用ID")
    type: str = Field(default="function", description="调用类型")
    function: Dict[str, Any] = Field(description="函数调用信息")


class OpenAIToolCallResponse(BaseModel):
    """OpenAI 工具调用响应"""
    tool_call_id: str = Field(description="工具调用ID")
    role: str = Field(default="tool", description="角色")
    name: str = Field(description="工具名称")
    content: str = Field(description="调用结果")
