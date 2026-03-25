"""
代码执行工具

安全执行Python和JavaScript代码。
"""

import asyncio
import io
import sys
import tempfile
import time
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict

from .base import BaseTool, ToolError
from ..models.tool_models import CodeExecutionResult


class CodeExecutorTool(BaseTool):
    """代码执行工具"""
    
    @property
    def name(self) -> str:
        return "code_executor"
    
    @property
    def description(self) -> str:
        return "Execute Python or JavaScript code safely and return the output. Supports data analysis, calculations, and visualization."
    
    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to execute"
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript"],
                    "description": "Programming language of the code",
                    "default": "python"
                }
            },
            "required": ["code"]
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行代码
        
        Args:
            code: 要执行的代码
            language: 编程语言 (python/javascript)
            
        Returns:
            代码执行结果
        """
        code = kwargs.get("code")
        language = kwargs.get("language", "python")
        
        if not code:
            raise ToolError("Code is required")
        
        if not self.config.get("code_execution_enabled", True):
            raise ToolError("Code execution is disabled")
        
        timeout = self.config.get("code_execution_timeout", 30)
        
        if language == "python":
            return await self._execute_python(code, timeout)
        elif language == "javascript":
            return await self._execute_javascript(code, timeout)
        else:
            raise ToolError(f"Unsupported language: {language}")
    
    async def _execute_python(self, code: str, timeout: int) -> Dict[str, Any]:
        """执行Python代码"""
        start_time = time.time()
        
        # 创建安全的执行环境
        import builtins
        safe_builtins = {}

        # 允许的内置函数
        allowed_builtins = [
            'print', 'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
            'range', 'enumerate', 'zip', 'map', 'filter', 'sum', 'min', 'max', 'abs', 'round',
            'sorted', 'reversed', 'any', 'all', 'type', 'isinstance', 'hasattr', 'getattr',
            'setattr', 'dir', 'vars', 'ord', 'chr', 'hex', 'oct', 'bin', 'format',
            '__import__'  # 允许导入模块
        ]

        for name in allowed_builtins:
            if hasattr(builtins, name):
                safe_builtins[name] = getattr(builtins, name)

        safe_globals = {
            '__builtins__': safe_builtins
        }
        
        # 添加常用的数据分析库
        try:
            import pandas as pd
            import numpy as np
            import matplotlib.pyplot as plt
            import json
            import math
            import datetime
            
            safe_globals.update({
                'pd': pd,
                'np': np,
                'plt': plt,
                'json': json,
                'math': math,
                'datetime': datetime,
            })
        except ImportError:
            pass  # 如果库不可用，继续执行
        
        # 捕获输出
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        try:
            # 使用asyncio.wait_for实现超时
            async def run_code():
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    exec(code, safe_globals)
            
            await asyncio.wait_for(run_code(), timeout=timeout)
            
            execution_time = time.time() - start_time
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()
            
            if error_output:
                return CodeExecutionResult(
                    success=False,
                    output=output,
                    error=error_output,
                    execution_time=execution_time
                ).model_dump()
            else:
                return CodeExecutionResult(
                    success=True,
                    output=output or "Code executed successfully (no output)",
                    error=None,
                    execution_time=execution_time
                ).model_dump()
                
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            return CodeExecutionResult(
                success=False,
                output=stdout_capture.getvalue(),
                error=f"Code execution timed out after {timeout} seconds",
                execution_time=execution_time
            ).model_dump()
            
        except Exception as e:
            execution_time = time.time() - start_time
            return CodeExecutionResult(
                success=False,
                output=stdout_capture.getvalue(),
                error=str(e),
                execution_time=execution_time
            ).model_dump()
    
    async def _execute_javascript(self, code: str, timeout: int) -> Dict[str, Any]:
        """执行JavaScript代码（需要Node.js）"""
        start_time = time.time()
        
        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            # 执行JavaScript代码
            process = await asyncio.create_subprocess_exec(
                'node', temp_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=timeout
                )
                
                execution_time = time.time() - start_time
                
                stdout_text = stdout.decode('utf-8') if stdout else ""
                stderr_text = stderr.decode('utf-8') if stderr else ""
                
                if process.returncode == 0:
                    return CodeExecutionResult(
                        success=True,
                        output=stdout_text or "Code executed successfully (no output)",
                        error=None,
                        execution_time=execution_time
                    ).model_dump()
                else:
                    return CodeExecutionResult(
                        success=False,
                        output=stdout_text,
                        error=stderr_text or f"Process exited with code {process.returncode}",
                        execution_time=execution_time
                    ).model_dump()
                    
            except asyncio.TimeoutError:
                process.kill()
                execution_time = time.time() - start_time
                return CodeExecutionResult(
                    success=False,
                    output="",
                    error=f"JavaScript execution timed out after {timeout} seconds",
                    execution_time=execution_time
                ).model_dump()
                
        except FileNotFoundError:
            execution_time = time.time() - start_time
            return CodeExecutionResult(
                success=False,
                output="",
                error="Node.js not found. Please install Node.js to execute JavaScript code.",
                execution_time=execution_time
            ).model_dump()
            
        except Exception as e:
            execution_time = time.time() - start_time
            return CodeExecutionResult(
                success=False,
                output="",
                error=str(e),
                execution_time=execution_time
            ).model_dump()
        
        finally:
            # 清理临时文件
            try:
                import os
                os.unlink(temp_file)
            except:
                pass
    
    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """格式化代码执行结果供AI使用"""
        if not result["success"]:
            return f"Code execution failed: {result['error']}"
        
        exec_result = result["result"]
        
        if not exec_result["success"]:
            return f"Code execution failed: {exec_result['error']}\nOutput: {exec_result['output']}"
        
        output = exec_result["output"]
        exec_time = exec_result["execution_time"]
        
        return f"Code executed successfully in {exec_time:.2f}s:\n\n{output}"
