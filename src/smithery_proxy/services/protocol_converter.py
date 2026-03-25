"""
协议转换器

负责OpenAI格式和MCP格式之间的转换。
"""

import time
import logging
from typing import Dict, List, Any, Optional, AsyncGenerator
from uuid import uuid4

from ..models.openai_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamResponse,
    ChatCompletionChoice,
    ChatCompletionStreamChoice,
    ChatCompletionUsage,
    ChatMessage,
    ErrorResponse,
    ErrorDetail,
)

from ..models.mcp_models import (
    MCPCreateMessageRequest,
    MCPCreateMessageResult,
    MCPMessage,
    MCPRole,
    MCPSamplingParams,
    MCPTextContent,
    MCPContentType,
)

from ..models.mcp_playground_models import (
    MCPToolDefinition,
    OpenAITool,
    OpenAIToolFunction,
    OpenAIToolCall,
    OpenAIToolCallResponse
)

logger = logging.getLogger(__name__)


class ProtocolConverter:
    """协议转换器类"""
    
    @staticmethod
    def openai_to_mcp_request(openai_request: ChatCompletionRequest) -> MCPCreateMessageRequest:
        """将OpenAI请求转换为MCP请求"""
        
        # 转换消息列表
        mcp_messages = []
        for msg in openai_request.messages:
            # 转换角色
            if msg.role == "user":
                role = MCPRole.USER
            elif msg.role == "assistant":
                role = MCPRole.ASSISTANT
            elif msg.role == "system":
                role = MCPRole.SYSTEM
            else:
                role = MCPRole.USER  # 默认为用户角色
            
            # 转换内容
            content = MCPTextContent(
                type=MCPContentType.TEXT,
                text=msg.content
            )
            
            mcp_messages.append(MCPMessage(
                role=role,
                content=content.text  # 简化为字符串格式
            ))
        
        # 转换采样参数
        sampling = None
        if any([
            openai_request.temperature is not None,
            openai_request.top_p is not None,
            openai_request.max_tokens is not None,
            openai_request.stop is not None
        ]):
            stop_sequences = None
            if openai_request.stop:
                if isinstance(openai_request.stop, str):
                    stop_sequences = [openai_request.stop]
                else:
                    stop_sequences = openai_request.stop
            
            sampling = MCPSamplingParams(
                temperature=openai_request.temperature,
                top_p=openai_request.top_p,
                max_tokens=openai_request.max_tokens,
                stop_sequences=stop_sequences
            )
        
        # 构建MCP请求
        mcp_request = MCPCreateMessageRequest(
            messages=mcp_messages,
            model_preferences={"model": openai_request.model},
            sampling=sampling
        )
        
        logger.debug(f"转换OpenAI请求到MCP: {len(mcp_messages)} 条消息")
        return mcp_request
    
    @staticmethod
    def mcp_to_openai_response(
        mcp_result: MCPCreateMessageResult,
        openai_request: ChatCompletionRequest,
        request_id: Optional[str] = None
    ) -> ChatCompletionResponse:
        """将MCP响应转换为OpenAI响应"""
        
        if request_id is None:
            request_id = f"chatcmpl-{uuid4().hex[:29]}"
        
        # 转换角色
        if mcp_result.role == MCPRole.ASSISTANT:
            role = "assistant"
        elif mcp_result.role == MCPRole.USER:
            role = "user"
        elif mcp_result.role == MCPRole.SYSTEM:
            role = "system"
        else:
            role = "assistant"  # 默认为助手角色
        
        # 转换内容
        if isinstance(mcp_result.content, str):
            content = mcp_result.content
        else:
            # 处理复杂内容类型，提取文本
            content = ""
            if isinstance(mcp_result.content, list):
                for item in mcp_result.content:
                    if hasattr(item, 'text'):
                        content += item.text
                    elif isinstance(item, dict) and 'text' in item:
                        content += item['text']
            else:
                content = str(mcp_result.content)
        
        # 转换完成原因
        finish_reason = None
        if mcp_result.stop_reason:
            if mcp_result.stop_reason in ["stop", "end_turn"]:
                finish_reason = "stop"
            elif mcp_result.stop_reason in ["length", "max_tokens"]:
                finish_reason = "length"
            else:
                finish_reason = "stop"
        
        # 创建选择项
        choice = ChatCompletionChoice(
            index=0,
            message=ChatMessage(
                role=role,
                content=content
            ),
            finish_reason=finish_reason
        )
        
        # 估算token使用量（简化实现）
        prompt_tokens = sum(len(msg.content.split()) for msg in openai_request.messages)
        completion_tokens = len(content.split())
        
        usage = ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )
        
        response = ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=mcp_result.model or openai_request.model,
            choices=[choice],
            usage=usage
        )
        
        logger.debug(f"转换MCP响应到OpenAI: {len(content)} 字符")
        return response
    
    @staticmethod
    async def mcp_to_openai_stream(
        mcp_results: AsyncGenerator[MCPCreateMessageResult, None],
        openai_request: ChatCompletionRequest,
        request_id: Optional[str] = None
    ) -> AsyncGenerator[ChatCompletionStreamResponse, None]:
        """将MCP流式响应转换为OpenAI流式响应"""
        
        if request_id is None:
            request_id = f"chatcmpl-{uuid4().hex[:29]}"
        
        created = int(time.time())
        
        # 发送开始chunk
        yield ChatCompletionStreamResponse(
            id=request_id,
            created=created,
            model=openai_request.model,
            choices=[ChatCompletionStreamChoice(
                index=0,
                delta={"role": "assistant"},
                finish_reason=None
            )]
        )
        
        # 处理流式内容
        async for mcp_result in mcp_results:
            # 转换内容
            if isinstance(mcp_result.content, str):
                content = mcp_result.content
            else:
                content = str(mcp_result.content)
            
            # 发送内容chunk
            yield ChatCompletionStreamResponse(
                id=request_id,
                created=created,
                model=mcp_result.model or openai_request.model,
                choices=[ChatCompletionStreamChoice(
                    index=0,
                    delta={"content": content},
                    finish_reason=None
                )]
            )
        
        # 发送结束chunk
        yield ChatCompletionStreamResponse(
            id=request_id,
            created=created,
            model=openai_request.model,
            choices=[ChatCompletionStreamChoice(
                index=0,
                delta={},
                finish_reason="stop"
            )]
        )
        
        logger.debug(f"完成MCP流式响应转换")
    
    @staticmethod
    def create_error_response(
        error_message: str,
        error_type: str = "invalid_request_error",
        error_code: Optional[str] = None,
        param: Optional[str] = None
    ) -> ErrorResponse:
        """创建错误响应"""
        
        error_detail = ErrorDetail(
            message=error_message,
            type=error_type,
            code=error_code,
            param=param
        )
        
        return ErrorResponse(error=error_detail)
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """估算文本的token数量（简化实现）"""
        # 这是一个简化的token估算，实际应该使用tokenizer
        # 大致按照1个token约等于0.75个英文单词或1个中文字符计算
        words = text.split()
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_words = len(words) - chinese_chars
        
        return int(english_words * 1.33 + chinese_chars)
    
    @staticmethod
    def validate_openai_request(request: ChatCompletionRequest) -> Optional[str]:
        """验证OpenAI请求格式"""
        
        if not request.messages:
            return "messages字段不能为空"
        
        if not request.model:
            return "model字段不能为空"
        
        for i, msg in enumerate(request.messages):
            # 放宽content验证 - 允许空消息，但会自动填充默认内容
            # 支持多模态格式的内容检查
            is_empty = False

            if not msg.content:
                is_empty = True
            elif isinstance(msg.content, str):
                # 字符串格式
                if msg.content.strip() == "":
                    is_empty = True
            elif isinstance(msg.content, list):
                # 多模态格式 - 检查是否有实际内容
                has_content = False
                for item in msg.content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and item.get("text", "").strip():
                            has_content = True
                            break
                        elif item.get("type") in ["image", "image_url"]:
                            has_content = True
                            break
                is_empty = not has_content

            if is_empty:
                # 不返回错误，而是在后续处理中自动填充默认内容
                logger.warning(f"第{i+1}条消息的content为空，将使用默认内容")

            if msg.role not in ["system", "user", "assistant"]:
                return f"第{i+1}条消息的role必须是system、user或assistant之一"
        
        if request.temperature is not None and not (0.0 <= request.temperature <= 2.0):
            return "temperature必须在0.0到2.0之间"
        
        if request.top_p is not None and not (0.0 <= request.top_p <= 1.0):
            return "top_p必须在0.0到1.0之间"
        
        if request.max_tokens is not None and request.max_tokens <= 0:
            return "max_tokens必须大于0"

        return None

    @staticmethod
    def mcp_tools_to_openai_tools(mcp_tools: List[MCPToolDefinition]) -> List[OpenAITool]:
        """将 MCP 工具定义转换为 OpenAI tools 格式"""
        openai_tools = []

        for mcp_tool in mcp_tools:
            # 构建参数 JSON Schema
            parameters = {
                "type": "object",
                "properties": {},
                "required": []
            }

            # 转换 MCP 工具参数为 JSON Schema
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

            # 创建 OpenAI 工具
            openai_tool = OpenAITool(
                type="function",
                function=OpenAIToolFunction(
                    name=f"mcp_{mcp_tool.server_id}_{mcp_tool.name}",
                    description=f"[{mcp_tool.server_name}] {mcp_tool.description}",
                    parameters=parameters
                )
            )

            openai_tools.append(openai_tool)

        return openai_tools

    @staticmethod
    def create_tool_call_response(
        tool_calls: List[Dict[str, Any]],
        content: Optional[str] = None
    ) -> ChatCompletionResponse:
        """创建包含工具调用的响应"""

        # 转换工具调用格式
        formatted_tool_calls = []
        for tool_call in tool_calls:
            formatted_tool_calls.append({
                "id": tool_call.get("id", str(uuid4())),
                "type": "function",
                "function": {
                    "name": tool_call.get("name", ""),
                    "arguments": tool_call.get("arguments", "{}")
                }
            })

        choice = ChatCompletionChoice(
            index=0,
            message=ChatMessage(
                role="assistant",
                content=content,
                tool_calls=formatted_tool_calls
            ),
            finish_reason="tool_calls"
        )

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid4()}",
            object="chat.completion",
            created=int(time.time()),
            model="claude-haiku-4.5",
            choices=[choice],
            usage=ChatCompletionUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0
            )
        )

    @staticmethod
    def create_tool_result_message(
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> Dict[str, Any]:
        """创建工具调用结果消息"""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        }
