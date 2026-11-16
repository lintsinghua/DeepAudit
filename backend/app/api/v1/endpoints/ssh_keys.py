"""
SSH密钥管理API端点
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
import json

from app.api import deps
from app.db.session import get_db
from app.models.user import User
from app.models.user_config import UserConfig
from app.services.git_ssh_service import SSHKeyService, GitSSHOperations, clear_known_hosts
from app.core.encryption import encrypt_sensitive_data, decrypt_sensitive_data

router = APIRouter()
logger = logging.getLogger(__name__)


# Schemas
class SSHKeyGenerateResponse(BaseModel):
    """SSH 密钥生成响应模型。"""
    public_key: str
    message: str


class SSHKeyResponse(BaseModel):
    """SSH 密钥查询响应模型。"""
    has_key: bool
    public_key: Optional[str] = None
    fingerprint: Optional[str] = None


class SSHKeyTestRequest(BaseModel):
    """SSH 密钥测试请求模型。"""
    repo_url: str


class SSHKeyTestResponse(BaseModel):
    """SSH 密钥测试响应模型。"""
    success: bool
    message: str
    output: Optional[str] = None


@router.post("/generate", response_model=SSHKeyGenerateResponse)
async def generate_ssh_key(
    *,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    生成新的 SSH 密钥对。

    处理流程：
    - 生成 RSA 4096 密钥对
    - 获取或创建用户配置
    - 加密并保存私钥，保存公钥
    - 返回公钥与指纹
    """
    try:
        # 生成 SSH 密钥对 (RSA 4096)
        private_key, public_key = SSHKeyService.generate_rsa_key(key_size=4096)

        # 获取或创建用户配置
        result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == current_user.id)
        )
        user_config = result.scalar_one_or_none()

        if not user_config:
            # 创建新的用户配置
            user_config = UserConfig(
                user_id=current_user.id,
                llm_config="{}",
                other_config="{}"
            )
            db.add(user_config)

        # 解析现有的 other_config
        other_config = json.loads(user_config.other_config) if user_config.other_config else {}

        # 加密并存储私钥
        encrypted_private_key = encrypt_sensitive_data(private_key)
        other_config['sshPrivateKey'] = encrypted_private_key
        # 公钥不需要加密
        other_config['sshPublicKey'] = public_key

        # 更新配置
        user_config.other_config = json.dumps(other_config)

        # 提交事务
        await db.commit()

        # 计算公钥指纹
        fingerprint = SSHKeyService.get_public_key_fingerprint(public_key)

        # 返回公钥与指纹
        return {
            "public_key": public_key,
            "fingerprint": fingerprint,
            "message": "SSH密钥生成成功，请将公钥添加到您的GitHub/GitLab账户"
        }

    except Exception as e:
        logger.error(f"Failed to generate SSH key for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="生成SSH密钥失败，请稍后重试")


@router.get("/", response_model=SSHKeyResponse)
async def get_ssh_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户的 SSH 公钥。

    处理流程：
    - 读取用户配置
    - 解析公钥并计算指纹
    - 返回公钥信息或空结果
    """
    try:
        # 获取用户配置
        result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == current_user.id)
        )
        user_config = result.scalar_one_or_none()

        if not user_config or not user_config.other_config:
            # 未找到配置则返回无密钥
            return {"has_key": False}

        # 解析配置
        other_config = json.loads(user_config.other_config)

        if 'sshPublicKey' in other_config:
            # 读取公钥并计算指纹
            public_key = other_config['sshPublicKey']
            fingerprint = SSHKeyService.get_public_key_fingerprint(public_key)

            # 返回公钥信息
            return {
                "has_key": True,
                "public_key": public_key,
                "fingerprint": fingerprint
            }
        else:
            # 未找到公钥
            return {"has_key": False}

    except Exception as e:
        logger.error(f"Failed to get SSH key for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="获取SSH密钥失败，请稍后重试")


@router.delete("/")
async def delete_ssh_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    删除当前用户的 SSH 密钥。

    处理流程：
    - 读取用户配置
    - 删除私钥与公钥字段
    - 保存配置并返回结果
    """
    try:
        # 获取用户配置
        result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == current_user.id)
        )
        user_config = result.scalar_one_or_none()

        if not user_config or not user_config.other_config:
            # 未找到密钥记录
            raise HTTPException(status_code=404, detail="未找到SSH密钥")

        # 解析配置
        other_config = json.loads(user_config.other_config)

        # 删除 SSH 密钥
        if 'sshPrivateKey' in other_config:
            del other_config['sshPrivateKey']
        if 'sshPublicKey' in other_config:
            del other_config['sshPublicKey']

        # 更新配置
        user_config.other_config = json.dumps(other_config)
        # 提交事务
        await db.commit()

        # 返回删除结果
        return {"message": "SSH密钥已删除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete SSH key for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="删除SSH密钥失败，请稍后重试")


@router.post("/test", response_model=SSHKeyTestResponse)
async def test_ssh_key(
    *,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    test_request: SSHKeyTestRequest,
) -> Any:
    """
    测试 SSH 密钥是否有效。

    Args:
        test_request: 包含repo_url的测试请求
    """
    try:
        # 获取用户配置
        result = await db.execute(
            select(UserConfig).where(UserConfig.user_id == current_user.id)
        )
        user_config = result.scalar_one_or_none()

        if not user_config or not user_config.other_config:
            # 未找到密钥记录
            raise HTTPException(status_code=404, detail="未找到SSH密钥，请先生成SSH密钥")

        # 解析配置
        other_config = json.loads(user_config.other_config)

        if 'sshPrivateKey' not in other_config:
            # 缺少私钥
            raise HTTPException(status_code=404, detail="未找到SSH密钥，请先生成SSH密钥")

        # 解密私钥
        private_key = decrypt_sensitive_data(other_config['sshPrivateKey'])
        # 读取公钥
        public_key = other_config.get('sshPublicKey', '')

        # 验证密钥对是否匹配
        is_valid = SSHKeyService.verify_key_pair(private_key, public_key)
        logger.debug(f"Key pair validation result: {is_valid}")

        if not is_valid:
            # 返回密钥对不匹配结果
            return {
                "success": False,
                "message": "密钥对验证失败：私钥和公钥不匹配",
                "output": "请重新生成SSH密钥"
            }

        # 测试 SSH 连接
        result = GitSSHOperations.test_ssh_key(test_request.repo_url, private_key)

        # 返回测试结果
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test SSH key for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="测试SSH密钥失败，请稍后重试")


@router.delete("/known-hosts")
async def clear_known_hosts_file(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    清理 known_hosts 文件。

    处理流程：
    - 调用系统清理函数
    - 返回清理结果
    """
    try:
        # 清理 known_hosts 文件
        success = clear_known_hosts()

        if success:
            # 返回成功结果
            return {
                "success": True,
                "message": "known_hosts文件已清理，下次连接时会重新保存主机密钥"
            }
        else:
            # 清理失败
            raise HTTPException(status_code=500, detail="清理known_hosts文件失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear known_hosts for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="清理失败，请稍后重试")
