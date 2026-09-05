import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_config import UserConfig


async def get_user_config_dict(db: AsyncSession, user_id: str) -> dict:
    """获取用户配置字典（包含解密敏感字段）"""
    from app.core.encryption import decrypt_sensitive_data

    # 需要解密的敏感字段列表（与 config.py 保持一致）
    SENSITIVE_LLM_FIELDS = [
        "llmApiKey",
        "geminiApiKey",
        "openaiApiKey",
        "claudeApiKey",
        "qwenApiKey",
        "deepseekApiKey",
        "zhipuApiKey",
        "moonshotApiKey",
        "baiduApiKey",
        "minimaxApiKey",
        "doubaoApiKey",
    ]
    SENSITIVE_OTHER_FIELDS = ["githubToken", "gitlabToken", "giteaToken"]

    def decrypt_config(config: dict, sensitive_fields: list) -> dict:
        """解密配置中的敏感字段"""
        decrypted = config.copy()
        for field in sensitive_fields:
            if field in decrypted and decrypted[field]:
                decrypted[field] = decrypt_sensitive_data(decrypted[field])
        return decrypted

    result = await db.execute(select(UserConfig).where(UserConfig.user_id == user_id))
    config = result.scalar_one_or_none()
    if not config:
        return {}

    # 解析配置
    llm_config = json.loads(config.llm_config) if config.llm_config else {}
    other_config = json.loads(config.other_config) if config.other_config else {}

    # 解密敏感字段
    llm_config = decrypt_config(llm_config, SENSITIVE_LLM_FIELDS)
    other_config = decrypt_config(other_config, SENSITIVE_OTHER_FIELDS)

    return {
        "llmConfig": llm_config,
        "otherConfig": other_config,
    }
