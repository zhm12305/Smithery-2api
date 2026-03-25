"""
文档内容检测工具

检测消息中是否包含文档内容，支持多种格式。
基于测试验证，Smithery API 支持：TXT, Markdown, CSV, PDF
"""

import logging
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DocumentDetector:
    """文档内容检测器"""
    
    # Smithery API 确认支持的文档格式（基于测试）
    SUPPORTED_DOCUMENT_EXTENSIONS = {
        'txt', 'md', 'markdown', 'csv', 'pdf'
    }
    
    # 文档 MIME 类型映射
    DOCUMENT_MIME_TYPES = {
        'text/plain': 'txt',
        'text/markdown': 'md',
        'text/csv': 'csv',
        'application/pdf': 'pdf',
    }
    
    # 不支持的 Office 格式（Smithery API 测试失败）
    UNSUPPORTED_OFFICE_TYPES = {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',       # .xlsx
        'application/vnd.openxmlformats-officedocument.presentationml.presentation', # .pptx
    }
    
    @classmethod
    def detect_documents_in_message(cls, content: Union[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        检测消息中的文档内容
        
        Args:
            content: 消息内容，可以是字符串或多模态列表
            
        Returns:
            检测到的文档信息列表
        """
        documents = []
        
        if isinstance(content, str):
            # 字符串格式，检测 URL 和 base64
            documents.extend(cls._detect_documents_in_text(content))
        elif isinstance(content, list):
            # 多模态格式，检测文档对象
            documents.extend(cls._detect_documents_in_multimodal(content))
        
        return documents
    
    @classmethod
    def _detect_documents_in_text(cls, text: str) -> List[Dict[str, Any]]:
        """
        在文本中检测文档链接
        
        Args:
            text: 要检测的文本
            
        Returns:
            文档信息列表
        """
        documents = []
        
        # 检测文档URL
        url_pattern = r'https?://[^\s<>"]+\.(' + '|'.join(cls.SUPPORTED_DOCUMENT_EXTENSIONS) + r')'
        urls = re.findall(url_pattern, text, re.IGNORECASE)
        
        for url in urls:
            documents.append({
                'type': 'url',
                'url': url,
                'format': cls._get_format_from_url(url)
            })
        
        # 检测 data URI
        data_uri_pattern = r'data:(text/(?:plain|markdown|csv)|application/pdf);base64,([A-Za-z0-9+/=]+)'
        data_uris = re.findall(data_uri_pattern, text)
        
        for mime_type, base64_data in data_uris:
            documents.append({
                'type': 'base64',
                'mime_type': mime_type,
                'data': base64_data[:100] + '...',  # 只保存前100字符用于日志
                'format': cls.DOCUMENT_MIME_TYPES.get(mime_type, 'unknown')
            })
        
        return documents
    
    @classmethod
    def _detect_documents_in_multimodal(cls, content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        在多模态内容中检测文档
        
        Args:
            content: 多模态内容列表
            
        Returns:
            文档信息列表
        """
        documents = []
        
        for item in content:
            if not isinstance(item, dict):
                continue
            
            item_type = item.get('type', '')
            
            # 检测 document_url 类型（新增支持）
            if item_type == 'document_url':
                doc_url = item.get('document_url', {})
                url = doc_url.get('url', '') if isinstance(doc_url, dict) else doc_url
                
                if url:
                    doc_format = cls._get_format_from_url(url)
                    if doc_format in cls.SUPPORTED_DOCUMENT_EXTENSIONS:
                        documents.append({
                            'type': 'document_url',
                            'url': url,
                            'format': doc_format,
                            'mime_type': cls._get_mime_type(doc_format)
                        })
            
            # 检测 image_url 中的文档（兼容当前实现）
            elif item_type == 'image_url':
                image_url = item.get('image_url', {})
                url = image_url.get('url', '') if isinstance(image_url, dict) else image_url
                
                if url:
                    # 检查是否是文档格式
                    doc_format = cls._get_format_from_url(url)
                    if doc_format in cls.SUPPORTED_DOCUMENT_EXTENSIONS:
                        documents.append({
                            'type': 'image_url_document',  # 标记这是通过image_url传递的文档
                            'url': url,
                            'format': doc_format,
                            'mime_type': cls._get_mime_type(doc_format)
                        })
            
            # 检测 file 类型（通用文件类型）
            elif item_type == 'file':
                file_url = item.get('url', '') or item.get('data', '')
                file_type = item.get('file_type', '') or item.get('mime_type', '')
                
                if file_url and cls._is_supported_document_type(file_type):
                    documents.append({
                        'type': 'file',
                        'url': file_url,
                        'mime_type': file_type,
                        'format': cls.DOCUMENT_MIME_TYPES.get(file_type, 'unknown')
                    })
        
        return documents
    
    @classmethod
    def _get_format_from_url(cls, url: str) -> str:
        """
        从URL中提取文档格式
        
        Args:
            url: 文档URL
            
        Returns:
            文档格式（如 'pdf', 'txt'）
        """
        # 处理 data URI
        if url.startswith('data:'):
            mime_match = re.match(r'data:([^;,]+)', url)
            if mime_match:
                mime_type = mime_match.group(1)
                return cls.DOCUMENT_MIME_TYPES.get(mime_type, 'unknown')
        
        # 处理普通 URL
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        for ext in cls.SUPPORTED_DOCUMENT_EXTENSIONS:
            if path.endswith(f'.{ext}'):
                return ext
        
        return 'unknown'
    
    @classmethod
    def _get_mime_type(cls, file_format: str) -> str:
        """
        根据文件格式获取MIME类型
        
        Args:
            file_format: 文件格式（如 'pdf', 'txt'）
            
        Returns:
            MIME类型
        """
        mime_map = {
            'txt': 'text/plain',
            'md': 'text/markdown',
            'markdown': 'text/markdown',
            'csv': 'text/csv',
            'pdf': 'application/pdf'
        }
        return mime_map.get(file_format, 'application/octet-stream')
    
    @classmethod
    def _is_supported_document_type(cls, mime_type: str) -> bool:
        """
        检查是否是支持的文档类型
        
        Args:
            mime_type: MIME类型
            
        Returns:
            是否支持
        """
        return mime_type in cls.DOCUMENT_MIME_TYPES
    
    @classmethod
    def has_document_content(cls, content: Union[str, List[Dict[str, Any]]]) -> bool:
        """
        检查消息是否包含文档内容
        
        Args:
            content: 消息内容
            
        Returns:
            是否包含文档
        """
        documents = cls.detect_documents_in_message(content)
        return len(documents) > 0
    
    @classmethod
    def is_unsupported_office_format(cls, url: str) -> bool:
        """
        检查是否是不支持的Office格式
        
        Args:
            url: 文档URL或data URI
            
        Returns:
            是否是不支持的Office格式
        """
        if url.startswith('data:'):
            mime_match = re.match(r'data:([^;,]+)', url)
            if mime_match:
                mime_type = mime_match.group(1)
                return mime_type in cls.UNSUPPORTED_OFFICE_TYPES
        
        # 检查文件扩展名
        url_lower = url.lower()
        return any(url_lower.endswith(ext) for ext in ['.docx', '.xlsx', '.pptx'])

