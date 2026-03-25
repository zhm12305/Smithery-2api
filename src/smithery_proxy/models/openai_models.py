"""
OpenAI格式的数据模型 - 最终修复版本
"""

from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4
import json

from pydantic import BaseModel, Field, field_validator


def normalize_content(content: Union[str, List[Dict[str, Any]]]) -> Union[str, List[Dict[str, Any]]]:
    """
    标准化content格式，保持多模态内容的完整性

    支持格式：
    1. 字符串: "你好" -> 保持不变
    2. 多模态列表: [{"type": "text", "text": "你好"}, {"type": "image_url", "image_url": {...}}] -> 保持不变
    3. 混合格式等

    注意：现在保持多模态格式，不强制转换为字符串
    """
    if isinstance(content, str):
        return content  # 字符串格式，直接返回
    elif isinstance(content, list):
        # 检查是否包含图片内容
        has_image = False
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type", "")
                if item_type in ["image", "image_url"] or "image" in item_type.lower():
                    has_image = True
                    break

        # 如果包含图片，保持多模态格式
        if has_image:
            return content

        # 如果只有文本，提取文本内容并返回字符串
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                # Claude/Cursor格式: {"type": "text", "text": "内容"}
                if item.get("type") == "text" and "text" in item:
                    text_parts.append(item["text"])
                # 其他可能的格式: {"text": "内容"}
                elif "text" in item:
                    text_parts.append(item["text"])
                # 直接包含内容的格式: {"content": "内容"}
                elif "content" in item:
                    text_parts.append(str(item["content"]))
            elif isinstance(item, str):
                # 列表中直接包含字符串
                text_parts.append(item)

        result = "".join(text_parts)
        return result if result else ""
    else:
        # 其他格式转为字符串
        return str(content)


class StreamOptions(BaseModel):
    """流式响应选项"""
    include_usage: bool = Field(default=False, description="是否在流式响应中包含usage信息")


class ChatMessage(BaseModel):
    """聊天消息模型 - 支持多种content格式和工具调用"""

    role: Literal["system", "user", "assistant", "tool"] = Field(
        description="消息角色"
    )
    content: Optional[Union[str, List[Dict[str, Any]]]] = Field(default=None, description="消息内容，支持字符串和列表格式")
    name: Optional[str] = Field(default=None, description="消息发送者名称")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="工具调用列表")
    tool_call_id: Optional[str] = Field(default=None, description="工具调用ID（用于tool角色）")

    @field_validator('content')
    @classmethod
    def normalize_content_field(cls, v):
        """自动将content标准化为字符串格式"""
        return normalize_content(v)
    
    def model_dump(self, **kwargs):
        """自定义序列化，排除None值"""
        data = super().model_dump(**kwargs)
        # 移除None值的字段
        return {k: v for k, v in data.items() if v is not None}
    
    def model_dump_json(self, **kwargs):
        """自定义JSON序列化，排除None值"""
        data = self.model_dump()
        return json.dumps(data, ensure_ascii=False, **kwargs)
    
    def dict(self, **kwargs):
        """兼容旧版本的dict方法"""
        return self.model_dump(**kwargs)
    
    def __iter__(self):
        """重写迭代器，确保dict()也排除None值"""
        data = self.model_dump()
        return iter(data.items())


class ChatCompletionRequest(BaseModel):
    """聊天完成请求模型"""
    model: str = Field(
        default="claude-haiku-4.5",
        description="模型名称"
    )
    messages: List[ChatMessage] = Field(description="消息列表")
    temperature: Optional[float] = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="温度参数"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        gt=0,
        description="最大token数"
    )
    top_p: Optional[float] = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="核采样参数"
    )
    stream: bool = Field(default=False, description="是否流式输出")
    stop: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="停止词"
    )
    presence_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="存在惩罚"
    )
    frequency_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="频率惩罚"
    )
    user: Optional[str] = Field(default=None, description="用户标识")
    tools: Optional[List[Dict[str, Any]]] = Field(default=None, description="可用工具列表")
    tool_choice: Optional[Union[str, Dict[str, Any]]] = Field(default=None, description="工具选择策略")
    stream_options: Optional[Union[Dict[str, bool], StreamOptions]] = Field(
        default=None,
        description="流式响应选项，例如 {\"include_usage\": true}"
    )


class ChatCompletionChoice(BaseModel):
    """聊天完成选择项"""
    index: int = Field(description="选择项索引")
    message: ChatMessage = Field(description="生成的消息")
    finish_reason: Optional[Literal["stop", "length", "content_filter", "tool_calls"]] = Field(
        description="完成原因"
    )
    
    def model_dump(self, **kwargs):
        """自定义序列化，确保message也排除None值"""
        data = super().model_dump(**kwargs)
        # 确保message字段也使用自定义序列化
        if 'message' in data and hasattr(data['message'], 'model_dump'):
            data['message'] = data['message'].model_dump()
        elif 'message' in data and isinstance(data['message'], dict):
            # 如果message已经是dict，移除None值
            data['message'] = {k: v for k, v in data['message'].items() if v is not None}
        return data


class ChatCompletionUsage(BaseModel):
    """使用统计"""
    prompt_tokens: int = Field(description="输入token数")
    completion_tokens: int = Field(description="生成token数")
    total_tokens: int = Field(description="总token数")


class ChatCompletionResponse(BaseModel):
    """聊天完成响应模型"""
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex[:29]}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(description="创建时间戳")
    model: str = Field(description="使用的模型")
    choices: List[ChatCompletionChoice] = Field(description="生成选择项")
    usage: Optional[ChatCompletionUsage] = Field(
        default=None,
        description="使用统计"
    )
    
    def model_dump(self, **kwargs):
        """自定义序列化，确保所有嵌套对象都排除None值"""
        data = super().model_dump(**kwargs)
        
        # 处理choices中的message
        if 'choices' in data:
            for choice in data['choices']:
                if 'message' in choice and isinstance(choice['message'], dict):
                    # 移除message中的None值
                    choice['message'] = {k: v for k, v in choice['message'].items() if v is not None}
        
        # 移除顶层的None值
        return {k: v for k, v in data.items() if v is not None}
    
    def model_dump_json(self, **kwargs):
        """自定义JSON序列化"""
        data = self.model_dump()
        return json.dumps(data, ensure_ascii=False, **kwargs)


class ChatCompletionStreamChoice(BaseModel):
    """流式聊天完成选择项"""
    index: int = Field(description="选择项索引")
    delta: Dict[str, Any] = Field(description="增量内容")
    finish_reason: Optional[Literal["stop", "length", "content_filter"]] = Field(
        default=None,
        description="完成原因"
    )


class ChatCompletionStreamResponse(BaseModel):
    """流式聊天完成响应模型"""
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex[:29]}")
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int = Field(description="创建时间戳")
    model: str = Field(description="使用的模型")
    choices: List[ChatCompletionStreamChoice] = Field(description="生成选择项")
    usage: Optional[ChatCompletionUsage] = Field(
        default=None,
        description="使用统计（仅在最后一个chunk中包含）"
    )


class ErrorDetail(BaseModel):
    """错误详情"""
    message: str = Field(description="错误消息")
    type: str = Field(description="错误类型")
    param: Optional[str] = Field(default=None, description="错误参数")
    code: Optional[str] = Field(default=None, description="错误代码")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: ErrorDetail = Field(description="错误详情")



