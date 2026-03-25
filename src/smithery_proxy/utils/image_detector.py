"""
图片内容检测工具

检测消息中是否包含图片内容，支持多种格式。
"""

import logging
import base64
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ImageDetector:
    """图片内容检测器"""
    
    # 支持的图片格式
    SUPPORTED_IMAGE_EXTENSIONS = {
        'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg'
    }
    
    # 图片 MIME 类型
    IMAGE_MIME_TYPES = {
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 
        'image/webp', 'image/bmp', 'image/tiff', 'image/svg+xml'
    }
    
    @classmethod
    def detect_images_in_message(cls, content: Union[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        检测消息中的图片内容
        
        Args:
            content: 消息内容，可以是字符串或多模态列表
            
        Returns:
            检测到的图片信息列表
        """
        images = []
        
        if isinstance(content, str):
            # 字符串格式，检测 URL 和 base64
            images.extend(cls._detect_images_in_text(content))
        elif isinstance(content, list):
            # 多模态格式，检测图片对象
            images.extend(cls._detect_images_in_multimodal(content))
        
        return images
    
    @classmethod
    def _detect_images_in_text(cls, text: str) -> List[Dict[str, Any]]:
        """检测文本中的图片 URL 和 base64"""
        images = []
        
        # 检测图片 URL
        url_pattern = r'https?://[^\s<>"]+\.(?:' + '|'.join(cls.SUPPORTED_IMAGE_EXTENSIONS) + r')(?:\?[^\s<>"]*)?'
        urls = re.findall(url_pattern, text, re.IGNORECASE)
        
        for url in urls:
            images.append({
                'type': 'url',
                'source': url,
                'format': cls._get_format_from_url(url)
            })
        
        # 检测 data URI 格式的图片
        data_uri_pattern = r'data:image/([^;]+);base64,([A-Za-z0-9+/=]+)'
        data_uris = re.findall(data_uri_pattern, text)
        
        for mime_type, base64_data in data_uris:
            images.append({
                'type': 'base64',
                'source': base64_data,
                'format': mime_type,
                'mime_type': f'image/{mime_type}'
            })
        
        # 检测纯 base64 图片数据（启发式检测）
        if cls._looks_like_base64_image(text):
            images.append({
                'type': 'base64',
                'source': text.strip(),
                'format': 'unknown',
                'mime_type': 'image/unknown'
            })
        
        return images
    
    @classmethod
    def _detect_images_in_multimodal(cls, content_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检测多模态内容中的图片"""
        images = []
        
        for item in content_list:
            if not isinstance(item, dict):
                continue
            
            item_type = item.get('type', '')
            
            # OpenAI 格式：{"type": "image_url", "image_url": {"url": "..."}}
            if item_type == 'image_url':
                image_url_data = item.get('image_url', {})
                url = image_url_data.get('url', '')
                if url:
                    if url.startswith('data:image/'):
                        # data URI 格式
                        parts = url.split(',', 1)
                        if len(parts) == 2:
                            header, base64_data = parts
                            mime_match = re.search(r'data:image/([^;]+)', header)
                            mime_type = mime_match.group(1) if mime_match else 'unknown'
                            images.append({
                                'type': 'base64',
                                'source': base64_data,
                                'format': mime_type,
                                'mime_type': f'image/{mime_type}'
                            })
                    else:
                        # URL 格式
                        images.append({
                            'type': 'url',
                            'source': url,
                            'format': cls._get_format_from_url(url)
                        })
            
            # Claude 格式：{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}
            elif item_type == 'image':
                source = item.get('source', {})
                if source.get('type') == 'base64':
                    media_type = source.get('media_type', 'image/unknown')
                    data = source.get('data', '')
                    if data:
                        format_name = media_type.split('/')[-1] if '/' in media_type else 'unknown'
                        images.append({
                            'type': 'base64',
                            'source': data,
                            'format': format_name,
                            'mime_type': media_type
                        })
            
            # 其他可能的图片格式
            elif 'image' in item_type.lower():
                # 尝试提取图片信息
                if 'url' in item:
                    images.append({
                        'type': 'url',
                        'source': item['url'],
                        'format': cls._get_format_from_url(item['url'])
                    })
                elif 'data' in item:
                    images.append({
                        'type': 'base64',
                        'source': item['data'],
                        'format': item.get('format', 'unknown'),
                        'mime_type': item.get('mime_type', 'image/unknown')
                    })
        
        return images
    
    @classmethod
    def _get_format_from_url(cls, url: str) -> str:
        """从 URL 中提取图片格式"""
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            
            for ext in cls.SUPPORTED_IMAGE_EXTENSIONS:
                if path.endswith(f'.{ext}'):
                    return ext
            
            return 'unknown'
        except Exception:
            return 'unknown'
    
    @classmethod
    def _looks_like_base64_image(cls, text: str) -> bool:
        """启发式检测是否为 base64 图片数据"""
        text = text.strip()
        
        # 基本长度检查（图片 base64 通常很长）
        if len(text) < 100:
            return False
        
        # 检查是否为有效的 base64
        try:
            # 移除可能的空白字符
            clean_text = re.sub(r'\s+', '', text)
            
            # 检查字符集
            if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', clean_text):
                return False
            
            # 尝试解码
            decoded = base64.b64decode(clean_text, validate=True)
            
            # 检查是否为图片文件头
            return cls._has_image_header(decoded)
            
        except Exception:
            return False
    
    @classmethod
    def _has_image_header(cls, data: bytes) -> bool:
        """检查数据是否有图片文件头"""
        if len(data) < 8:
            return False
        
        # 常见图片文件头
        image_headers = [
            b'\xFF\xD8\xFF',  # JPEG
            b'\x89PNG\r\n\x1a\n',  # PNG
            b'GIF87a',  # GIF87a
            b'GIF89a',  # GIF89a
            b'RIFF',  # WebP (需要进一步检查)
            b'BM',  # BMP
            b'\x00\x00\x01\x00',  # ICO
        ]
        
        for header in image_headers:
            if data.startswith(header):
                return True
        
        # WebP 特殊检查
        if data.startswith(b'RIFF') and len(data) >= 12:
            if data[8:12] == b'WEBP':
                return True
        
        return False
    
    @classmethod
    def has_images(cls, content: Union[str, List[Dict[str, Any]]]) -> bool:
        """检查消息是否包含图片"""
        images = cls.detect_images_in_message(content)
        return len(images) > 0
    
    @classmethod
    def extract_image_info(cls, content: Union[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """提取图片信息摘要"""
        images = cls.detect_images_in_message(content)
        
        return {
            'has_images': len(images) > 0,
            'image_count': len(images),
            'image_types': list(set(img['type'] for img in images)),
            'image_formats': list(set(img['format'] for img in images if img['format'] != 'unknown')),
            'images': images
        }
