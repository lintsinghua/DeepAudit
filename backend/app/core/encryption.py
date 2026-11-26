"""
敏感信息加密服务
使用 Fernet 对称加密算法加密 API Key 等敏感信息
"""

import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from app.core.config import settings


class EncryptionService:
    """加密服务 - 用于加密和解密敏感信息"""
    
    _instance: Optional['EncryptionService'] = None
    _fernet: Optional[Fernet] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_fernet()
        return cls._instance
    
    def _init_fernet(self):
        """初始化 Fernet 加密器，使用 SECRET_KEY 派生密钥"""
        # 使用 SHA256 哈希 SECRET_KEY 生成 32 字节密钥
        key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        # Fernet 需要 base64 编码的 32 字节密钥
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        self._fernet = Fernet(fernet_key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        加密明文字符串
        
        Args:
            plaintext: 要加密的明文
            
        Returns:
            加密后的密文（base64编码）
        """
        if not plaintext:
            return ""
        
        encrypted = self._fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted.decode('utf-8')
    
    def decrypt(self, ciphertext: str) -> str:
        """
        解密密文字符串
        
        Args:
            ciphertext: 要解密的密文（base64编码）
            
        Returns:
            解密后的明文
        """
        if not ciphertext:
            return ""
        
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode('utf-8'))
            return decrypted.decode('utf-8')
        except Exception:
            # 如果解密失败，可能是未加密的旧数据，直接返回原值
            return ciphertext
    
    def is_encrypted(self, value: str) -> bool:
        """
        检查值是否已加密
        
        Args:
            value: 要检查的值
            
        Returns:
            是否已加密
        """
        if not value:
            return False
        
        try:
            # 尝试解密，如果成功说明是加密的
            self._fernet.decrypt(value.encode('utf-8'))
            return True
        except Exception:
            return False


# 全局加密服务实例
encryption_service = EncryptionService()


def encrypt_sensitive_data(data: str) -> str:
    """加密敏感数据的便捷函数"""
    return encryption_service.encrypt(data)


def decrypt_sensitive_data(data: str) -> str:
    """解密敏感数据的便捷函数"""
    return encryption_service.decrypt(data)


def protect_embedding_key(other_config: dict) -> dict:
    """Encrypt the embedding credential in a saved configuration or legacy backup."""
    embedding = other_config.get("embedding_config")
    key = embedding.get("api_key") if isinstance(embedding, dict) else None
    if not key or encryption_service.is_encrypted(key):
        return other_config
    return {**other_config, "embedding_config": {**embedding, "api_key": encrypt_sensitive_data(key)}}


def without_embedding_key(other_config: dict) -> dict:
    embedding = other_config.get("embedding_config")
    if not isinstance(embedding, dict) or "api_key" not in embedding:
        return other_config
    return {**other_config, "embedding_config": {k: v for k, v in embedding.items() if k != "api_key"}}
