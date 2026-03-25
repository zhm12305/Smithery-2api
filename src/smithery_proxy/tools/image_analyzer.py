"""
图片分析工具

利用 Claude 3.5 Sonnet 的视觉能力进行图片识别和分析。
"""

import logging
import base64
import io
import json
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import httpx

from .base import BaseTool, ToolError
from ..models.tool_models import ToolDefinition, ToolFunction

logger = logging.getLogger(__name__)


class ImageAnalyzerTool(BaseTool):
    """图片分析工具 - 利用 ChatGPT 的视觉能力"""

    @property
    def name(self) -> str:
        return "image_analyzer"

    @property
    def description(self) -> str:
        return "分析图片内容，包括描述、OCR文字识别、物体检测等功能"

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_input": {
                    "type": "string",
                    "description": "图片输入，可以是URL或base64编码的图片数据"
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["describe", "ocr", "detect", "analyze", "qa"],
                    "default": "describe",
                    "description": "分析类型：describe(描述), ocr(文字识别), detect(物体检测), analyze(综合分析), qa(图片问答)"
                },
                "question": {
                    "type": "string",
                    "description": "当analysis_type为qa时，要问的问题"
                },
                "language": {
                    "type": "string",
                    "enum": ["zh", "en"],
                    "default": "zh",
                    "description": "输出语言：zh(中文), en(英文)"
                }
            },
            "required": ["image_input"]
        }

    def get_tool_definition(self) -> ToolDefinition:
        """获取工具定义"""
        return ToolDefinition(
            type="function",
            function=ToolFunction(
                name=self.name,
                description=self.description,
                parameters=self.parameters_schema
            )
        )

    def _get_gemini_client_config(self) -> tuple[str, str]:
        gemini_api_key = self.config.get("gemini_api_key") or os.getenv("GEMINI_API_KEY")
        gemini_base_url = self.config.get("gemini_base_url") or os.getenv("GEMINI_BASE_URL")

        if not gemini_api_key:
            raise ToolError("GEMINI_API_KEY 未配置，无法启用图片分析")
        if not gemini_base_url:
            raise ToolError("GEMINI_BASE_URL 未配置，无法启用图片分析")

        return gemini_api_key, gemini_base_url.rstrip("/")

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行图片分析
        
        Args:
            image_input: 图片输入（URL或base64）
            analysis_type: 分析类型
            question: 问题（用于qa模式）
            language: 输出语言
            
        Returns:
            分析结果
        """
        image_input = kwargs.get("image_input")
        analysis_type = kwargs.get("analysis_type", "describe")
        question = kwargs.get("question", "")
        language = kwargs.get("language", "zh")

        if not image_input:
            raise ToolError("缺少图片输入")

        try:
            # 处理图片输入
            try:
                image_data = await self._process_image_input(image_input)
                use_url_directly = False
            except ToolError as e:
                # 如果下载失败，尝试直接使用URL
                if self._is_url(image_input):
                    logger.warning(f"图片下载失败，尝试直接使用URL: {e}")
                    image_data = image_input  # 直接使用URL
                    use_url_directly = True
                else:
                    raise e

            # 根据分析类型生成提示词
            prompt = self._generate_analysis_prompt(analysis_type, question, language)

            # 调用 Gemini Vision 进行图片分析
            if use_url_directly:
                result = await self._analyze_with_gemini_url(image_data, prompt)
            else:
                result = await self._analyze_with_gemini(image_data, prompt)
            
            # 清理 Markdown 格式，返回纯净的自然文本
            cleaned_result = self._clean_markdown_format(result)
            return cleaned_result

        except Exception as e:
            logger.error(f"图片分析失败: {e}")
            raise ToolError(f"图片分析失败: {str(e)}")

    async def _process_image_input(self, image_input: str) -> str:
        """
        处理图片输入，统一转换为base64格式
        
        Args:
            image_input: 图片URL或base64数据
            
        Returns:
            base64编码的图片数据
        """
        # 检查是否已经是base64格式
        if image_input.startswith("data:image/"):
            # 提取base64部分
            return image_input.split(",", 1)[1] if "," in image_input else image_input
        elif self._is_base64(image_input):
            return image_input
        elif self._is_url(image_input):
            # 下载图片并转换为base64
            return await self._download_image_as_base64(image_input)
        else:
            raise ToolError("无效的图片输入格式，请提供URL或base64编码的图片")

    def _is_base64(self, data: str) -> bool:
        """检查字符串是否为base64格式"""
        try:
            if len(data) % 4 != 0:
                return False
            base64.b64decode(data, validate=True)
            return True
        except Exception:
            return False

    def _is_url(self, data: str) -> bool:
        """检查字符串是否为URL"""
        try:
            result = urlparse(data)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    async def _download_image_as_base64(self, url: str) -> str:
        """
        下载图片并转换为base64

        Args:
            url: 图片URL

        Returns:
            base64编码的图片数据
        """
        logger.info(f"🌐 开始下载图片: {url}")
        try:
            timeout = self.config.get("web_fetch_timeout", 30)  # 增加超时时间

            # 添加用户代理和其他头部
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            # 配置客户端，禁用SSL验证以避免证书问题
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                verify=False  # 禁用SSL验证
            ) as client:
                logger.info(f"🔍 发送HTTP请求到: {url}")
                response = await client.get(url)
                logger.info(f"🔍 HTTP响应状态码: {response.status_code}")

                response.raise_for_status()

                # 检查内容类型
                content_type = response.headers.get("content-type", "")
                logger.info(f"🔍 响应内容类型: {content_type}")

                if not content_type.startswith("image/"):
                    raise ToolError(f"URL不是图片文件，内容类型: {content_type}")

                # 检查内容长度
                content_length = len(response.content)
                logger.info(f"🔍 图片大小: {content_length} 字节")

                if content_length == 0:
                    raise ToolError("下载的图片文件为空")

                # 转换为base64
                image_data = base64.b64encode(response.content).decode('utf-8')
                logger.info(f"✅ 图片下载成功，base64长度: {len(image_data)}")
                return image_data

        except httpx.RequestError as e:
            error_msg = f"下载图片失败 - RequestError: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            raise ToolError(error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"下载图片失败 - HTTP错误: {e.response.status_code}"
            logger.error(error_msg)
            raise ToolError(error_msg)
        except Exception as e:
            error_msg = f"处理图片URL失败: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            raise ToolError(error_msg)

    async def _analyze_with_gemini_url(self, image_url: str, prompt: str) -> str:
        """
        使用 Gemini Vision 分析图片（直接使用URL）

        Args:
            image_url: 图片URL
            prompt: 分析提示词

        Returns:
            分析结果
        """
        try:
            # 使用 Gemini Vision API
            gemini_api_key, gemini_url = self._get_gemini_client_config()

            # 构建 Gemini API 请求格式（使用URL）
            request_data = {
                "model": "gemini-2.5-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_url
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 4000,
                "temperature": 0.1
            }

            headers = {
                "Authorization": f"Bearer {gemini_api_key}",
                "Content-Type": "application/json"
            }

            api_url = f"{gemini_url}/v1/chat/completions"

            # 使用与base64版本相同的超时配置
            timeout_config = httpx.Timeout(
                connect=30.0,  # 连接超时
                read=120.0,    # 读取超时
                write=30.0,    # 写入超时
                pool=30.0      # 连接池超时
            )

            logger.info(f"🔍 调用 Gemini Vision API (URL模式): {api_url}")
            logger.info(f"🔍 图片URL: {image_url}")
            logger.info(f"🔍 超时设置: 120秒")

            async with httpx.AsyncClient(timeout=timeout_config, verify=False) as client:
                response = await client.post(
                    api_url,
                    json=request_data,
                    headers=headers
                )

                logger.info(f"🔍 Gemini API 响应状态码: {response.status_code}")

                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and result["choices"]:
                        content = result["choices"][0]["message"]["content"]
                        logger.info(f"✅ Gemini 图片分析成功 (URL模式)，结果长度: {len(content)} 字符")
                        return content
                    else:
                        logger.error(f"❌ Gemini API 返回格式异常: {result}")
                        raise ToolError("Gemini API 返回格式异常")
                else:
                    error_text = response.text
                    logger.error(f"❌ Gemini API 调用失败: {response.status_code}, {error_text}")
                    raise ToolError(f"Gemini API 调用失败: {response.status_code}")

        except Exception as e:
            logger.error(f"❌ Gemini Vision 分析失败 (URL模式): {e}")
            raise ToolError(f"Gemini Vision 分析失败: {str(e)}")

    def _generate_analysis_prompt(self, analysis_type: str, question: str, language: str) -> str:
        """
        根据分析类型生成提示词
        
        Args:
            analysis_type: 分析类型
            question: 问题（用于qa模式）
            language: 输出语言
            
        Returns:
            分析提示词
        """
        lang_instruction = "请用中文回答" if language == "zh" else "Please answer in English"
        
        prompts = {
            "describe": f"请详细描述这张图片的内容，包括主要物体、场景、颜色、构图等。{lang_instruction}。",
            
            "ocr": f"请识别并提取图片中的所有文字内容，保持原有的格式和布局。如果没有文字，请说明。{lang_instruction}。",
            
            "detect": f"请识别图片中的所有物体和元素，列出它们的位置和特征。{lang_instruction}。",
            
            "analyze": f"请对这张图片进行详细分析，无论是真实照片、占位符图片、截图还是任何其他类型的图片。请包括：1)内容描述(颜色、尺寸、布局) 2)文字识别(如有) 3)物体检测 4)场景理解 5)用途或含义。请直接分析，不要说无法分析。{lang_instruction}。",
            
            "qa": f"请根据图片内容回答以下问题：{question}。{lang_instruction}。"
        }
        
        return prompts.get(analysis_type, prompts["describe"])

    async def _analyze_with_gemini(self, image_data: str, prompt: str) -> str:
        """
        使用 Gemini Vision 分析图片

        Args:
            image_data: base64编码的图片数据
            prompt: 分析提示词

        Returns:
            分析结果
        """
        try:
            # 使用 Gemini Vision API
            gemini_api_key, gemini_url = self._get_gemini_client_config()

            # 构建 Gemini API 请求格式
            request_data = {
                "model": "gemini-2.5-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 4000,
                "temperature": 0.1
            }

            headers = {
                "Authorization": f"Bearer {gemini_api_key}",
                "Content-Type": "application/json"
            }

            # 增加超时时间，特别是对于大图片
            timeout = self.config.get("api_timeout", 120)  # 增加到120秒
            api_url = f"{gemini_url}/v1/chat/completions"

            logger.info(f"🔍 调用 Gemini Vision API: {api_url}")
            logger.info(f"🔍 使用模型: gemini-2.5-flash")
            logger.info(f"🔍 超时设置: {timeout}秒")

            # 使用更详细的超时配置
            timeout_config = httpx.Timeout(
                connect=30.0,  # 连接超时
                read=120.0,    # 读取超时
                write=30.0,    # 写入超时
                pool=30.0      # 连接池超时
            )

            async with httpx.AsyncClient(timeout=timeout_config) as client:
                response = await client.post(
                    api_url,
                    json=request_data,
                    headers=headers
                )

                logger.info(f"🔍 Gemini API 响应状态码: {response.status_code}")

                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and result["choices"]:
                        content = result["choices"][0]["message"]["content"]
                        logger.info(f"✅ Gemini 图片分析成功，结果长度: {len(content)} 字符")
                        return content
                    else:
                        logger.error(f"❌ Gemini API 返回格式异常: {result}")
                        raise ToolError("Gemini API 返回格式异常")
                else:
                    error_text = response.text
                    logger.error(f"❌ Gemini API 调用失败: {response.status_code}, {error_text}")
                    raise ToolError(f"Gemini API 调用失败: {response.status_code}")

        except httpx.TimeoutException as e:
            logger.error(f"❌ Gemini API 请求超时: {e}")
            raise ToolError(f"图片分析超时，请稍后重试或使用较小的图片")
        except httpx.RequestError as e:
            logger.error(f"❌ 网络请求失败: {e}")
            raise ToolError(f"网络连接失败: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Gemini 图片分析失败: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"❌ 详细错误信息: {traceback.format_exc()}")
            raise ToolError(f"图片分析失败: {str(e)}")

    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """格式化结果供AI使用 - 现在直接返回自然文本"""
        # 如果result是字符串，直接返回
        if isinstance(result, str):
            return result

        # 如果是字典格式，提取result字段
        if isinstance(result, dict):
            return result.get("result", str(result))

        # 其他情况直接转换为字符串
        return str(result)

    def _clean_markdown_format(self, text: str) -> str:
        """清理 Markdown 格式，返回纯净的自然文本"""
        import re

        # 清理各种 Markdown 格式
        cleaned = text

        # 移除粗体标记 **text** 和 __text__
        cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
        cleaned = re.sub(r'__(.*?)__', r'\1', cleaned)

        # 移除斜体标记 *text* 和 _text_
        cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)
        cleaned = re.sub(r'_(.*?)_', r'\1', cleaned)

        # 移除标题标记 ### 、## 、#
        cleaned = re.sub(r'^#{1,6}\s*', '', cleaned, flags=re.MULTILINE)

        # 移除代码块标记 ```
        cleaned = re.sub(r'```.*?```', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)

        # 移除链接标记 [text](url)
        cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cleaned)

        # 移除列表标记 * 、- 、+
        cleaned = re.sub(r'^\s*[\*\-\+]\s*', '', cleaned, flags=re.MULTILINE)

        # 移除数字列表标记 1. 、2. 等
        cleaned = re.sub(r'^\s*\d+\.\s*', '', cleaned, flags=re.MULTILINE)

        # 移除分隔线 ---
        cleaned = re.sub(r'^-{3,}$', '', cleaned, flags=re.MULTILINE)

        # 清理多余的空行
        cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned)

        # 清理开头和结尾的空白
        cleaned = cleaned.strip()

        return cleaned
