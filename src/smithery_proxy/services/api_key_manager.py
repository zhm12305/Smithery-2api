"""
API密钥管理器

管理客户端API密钥的生成、验证和存储
"""

import secrets
import string
import json
import logging
from typing import Set, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class APIKeyManager:
    """API密钥管理器"""
    
    def __init__(self, keys_file: Optional[str] = None):
        """
        初始化API密钥管理器
        
        Args:
            keys_file: 密钥存储文件路径
        """
        self.keys_file = Path(keys_file) if keys_file else Path("api_keys.json")
        self._valid_keys: Set[str] = set()
        self._load_keys()
    
    def _load_keys(self) -> None:
        """从文件加载API密钥"""
        try:
            if self.keys_file.exists():
                with open(self.keys_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._valid_keys = set(data.get('keys', []))
                logger.info(f"加载了 {len(self._valid_keys)} 个API密钥")
            else:
                # 如果文件不存在，创建默认密钥
                default_key = self.generate_api_key()
                self._valid_keys.add(default_key)
                self._save_keys()
                logger.info(f"创建默认API密钥: {default_key}")
        except Exception as e:
            logger.error(f"加载API密钥失败: {e}")
            # 创建默认密钥
            default_key = self.generate_api_key()
            self._valid_keys.add(default_key)
            logger.info(f"使用默认API密钥: {default_key}")
    
    def _save_keys(self) -> None:
        """保存API密钥到文件"""
        try:
            data = {
                'keys': list(self._valid_keys),
                'description': 'Smithery Claude Proxy API Keys'
            }
            with open(self.keys_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"保存了 {len(self._valid_keys)} 个API密钥")
        except Exception as e:
            logger.error(f"保存API密钥失败: {e}")
    
    def generate_api_key(self) -> str:
        """
        生成新的API密钥
        
        Returns:
            str: 新生成的API密钥，格式为 sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        """
        # 生成32位随机字符串
        chars = string.ascii_lowercase + string.digits
        random_part = ''.join(secrets.choice(chars) for _ in range(32))
        return f"sk-{random_part}"
    
    def add_api_key(self, api_key: Optional[str] = None) -> str:
        """
        添加新的API密钥
        
        Args:
            api_key: 指定的API密钥，如果为None则自动生成
            
        Returns:
            str: 添加的API密钥
        """
        if api_key is None:
            api_key = self.generate_api_key()
        
        if not self.is_valid_format(api_key):
            raise ValueError(f"无效的API密钥格式: {api_key}")
        
        self._valid_keys.add(api_key)
        self._save_keys()
        logger.info(f"添加API密钥: {api_key[:10]}...")
        return api_key
    
    def remove_api_key(self, api_key: str) -> bool:
        """
        移除API密钥
        
        Args:
            api_key: 要移除的API密钥
            
        Returns:
            bool: 是否成功移除
        """
        if api_key in self._valid_keys:
            self._valid_keys.remove(api_key)
            self._save_keys()
            logger.info(f"移除API密钥: {api_key[:10]}...")
            return True
        return False
    
    def validate_api_key(self, api_key: str) -> bool:
        """
        验证API密钥是否有效
        
        Args:
            api_key: 要验证的API密钥
            
        Returns:
            bool: 密钥是否有效
        """
        return api_key in self._valid_keys
    
    def is_valid_format(self, api_key: str) -> bool:
        """
        检查API密钥格式是否正确
        
        Args:
            api_key: 要检查的API密钥
            
        Returns:
            bool: 格式是否正确
        """
        return (
            isinstance(api_key, str) and
            api_key.startswith("sk-") and
            len(api_key) == 35 and  # sk- + 32字符
            all(c in string.ascii_lowercase + string.digits for c in api_key[3:])
        )
    
    def list_api_keys(self) -> list:
        """
        列出所有API密钥（脱敏显示）
        
        Returns:
            list: API密钥列表，只显示前10个字符
        """
        return [f"{key[:10]}..." for key in self._valid_keys]
    
    def get_default_key(self) -> Optional[str]:
        """
        获取默认API密钥
        
        Returns:
            str: 默认API密钥，如果没有则返回None
        """
        if self._valid_keys:
            return next(iter(self._valid_keys))
        return None
    
    def count(self) -> int:
        """
        获取API密钥数量
        
        Returns:
            int: API密钥数量
        """
        return len(self._valid_keys)


# 全局API密钥管理器实例
_api_key_manager: Optional[APIKeyManager] = None


def get_api_key_manager() -> APIKeyManager:
    """获取全局API密钥管理器实例"""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager
