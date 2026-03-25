"""
工具基类

定义所有工具的通用接口和基础功能。
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..models.tool_models import ToolDefinition, CodeExecutionResult

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """工具执行错误"""
    pass


class BaseTool(ABC):
    """工具基类"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化工具
        
        Args:
            config: 工具配置字典
        """
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass
    
    @property
    @abstractmethod
    def parameters_schema(self) -> Dict[str, Any]:
        """工具参数schema"""
        pass
    
    def get_tool_definition(self) -> ToolDefinition:
        """获取工具定义"""
        from ..models.tool_models import ToolFunction
        
        return ToolDefinition(
            type="function",
            function=ToolFunction(
                name=self.name,
                description=self.description,
                parameters=self.parameters_schema
            )
        )
    
    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行工具
        
        Args:
            **kwargs: 工具参数
            
        Returns:
            工具执行结果
            
        Raises:
            ToolError: 工具执行失败
        """
        pass
    
    def validate_parameters(self, parameters: Dict[str, Any]) -> None:
        """
        验证参数
        
        Args:
            parameters: 参数字典
            
        Raises:
            ToolError: 参数验证失败
        """
        schema = self.parameters_schema
        required = schema.get("required", [])
        
        # 检查必需参数
        for param in required:
            if param not in parameters:
                raise ToolError(f"Missing required parameter: {param}")
    
    async def safe_execute(self, **kwargs) -> Dict[str, Any]:
        """
        安全执行工具（带错误处理）
        
        Args:
            **kwargs: 工具参数
            
        Returns:
            工具执行结果，包含成功/失败状态
        """
        start_time = time.time()
        
        try:
            # 验证参数
            self.validate_parameters(kwargs)
            
            # 执行工具
            result = await self.execute(**kwargs)
            
            execution_time = time.time() - start_time
            
            self.logger.info(f"Tool {self.name} executed successfully in {execution_time:.2f}s")
            
            return {
                "success": True,
                "result": result,
                "execution_time": execution_time,
                "error": None
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            
            self.logger.error(f"Tool {self.name} failed: {error_msg}")
            
            return {
                "success": False,
                "result": None,
                "execution_time": execution_time,
                "error": error_msg
            }
    
    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """
        格式化结果供AI使用
        
        Args:
            result: 工具执行结果
            
        Returns:
            格式化的字符串结果
        """
        if not result["success"]:
            return f"Tool execution failed: {result['error']}"
        
        return str(result["result"])
