"""
LazyLLM adapter测试
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import asyncio
from app.services.llm.types import LLMConfig, LLMProvider, LLMRequest, LLMMessage
from app.services.llm.adapters.lazyllm_adapter import LazyLLMAdapter


@pytest.mark.asyncio
async def test_lazyllm_adapter_basic():
    """测试 LazyLLM 适配器基本功能"""
    
    # 跳过测试如果没有设置 API key
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        pytest.skip("未设置 API key，跳过测试")
    
    # 创建配置
    config = LLMConfig(
        provider=LLMProvider.QWEN,  # 使用Qwen
        api_key=api_key,
        model="qwen-plus",
        temperature=0.7,
        max_tokens=100
    )
    
    # 创建适配器
    adapter = LazyLLMAdapter(config)
    
    # 验证配置
    assert await adapter.validate_config()
    
    # 创建请求
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content="你是一个有用的助手。"),
            LLMMessage(role="user", content="你好，请简单介绍一下你自己。")
        ],
        temperature=0.7,
        max_tokens=100
    )
    
    # 发送请求
    response = await adapter.complete(request)
    
    # 验证响应
    assert response is not None
    assert response.content
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    
    print(f"响应内容: {response.content}")
    
    # 关闭适配器
    await adapter.close()


@pytest.mark.asyncio
async def test_lazyllm_adapter_with_qwen():
    """测试使用通义千问"""
    
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        pytest.skip("未设置 QWEN_API_KEY，跳过测试")
    
    config = LLMConfig(
        provider=LLMProvider.QWEN,
        api_key=api_key,
        model="qwen-plus",
        temperature=0.2
    )
    
    adapter = LazyLLMAdapter(config)
    
    request = LLMRequest(
        messages=[
            LLMMessage(role="user", content="Python 中 list 和 tuple 的区别是什么？简短回答。")
        ]
    )
    
    response = await adapter.complete(request)
    
    assert response.content
    print(f"Qwen 响应: {response.content}")
    
    await adapter.close()


@pytest.mark.asyncio
async def test_lazyllm_adapter_supports_provider():
    """测试提供商支持检查"""
    
    # 支持的提供商
    assert LazyLLMAdapter.supports_provider(LLMProvider.OPENAI)
    assert LazyLLMAdapter.supports_provider(LLMProvider.QWEN)
    assert LazyLLMAdapter.supports_provider(LLMProvider.ZHIPU)
    assert LazyLLMAdapter.supports_provider(LLMProvider.MOONSHOT)
    assert LazyLLMAdapter.supports_provider(LLMProvider.DEEPSEEK)
    assert LazyLLMAdapter.supports_provider(LLMProvider.MINIMAX)
    assert LazyLLMAdapter.supports_provider(LLMProvider.DOUBAO)
    
    # 不支持的提供商（这些由原生适配器处理）
    assert not LazyLLMAdapter.supports_provider(LLMProvider.BAIDU)


@pytest.mark.asyncio
async def test_lazyllm_adapter_with_history():
    """测试带历史对话的请求"""
    
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        pytest.skip("未设置 QWEN_API_KEY，跳过测试")
    
    config = LLMConfig(
        provider=LLMProvider.QWEN,
        api_key=api_key,
        model="qwen-plus",
    )
    
    adapter = LazyLLMAdapter(config)
    
    # 包含历史对话的请求
    request = LLMRequest(
        messages=[
            LLMMessage(role="user", content="我的名字是张三"),
            LLMMessage(role="assistant", content="你好张三，很高兴认识你！"),
            LLMMessage(role="user", content="我叫什么名字？")
        ]
    )
    
    response = await adapter.complete(request)
    
    # 应该能够记住用户的名字
    assert "张三" in response.content
    print(f"历史对话测试响应: {response.content}")
    
    await adapter.close()


if __name__ == "__main__":
    # 运行测试
    print("=" * 60)
    print("LazyLLM 适配器测试")
    print("=" * 60)
    
    # 设置测试环境变量（如果需要）
    # os.environ["{SOURCE}_API_KEY"] = "your_api_key_here"
    
    # 运行异步测试
    asyncio.run(test_lazyllm_adapter_basic())
    print("\n✅ 基本功能测试通过\n")
    
    asyncio.run(test_lazyllm_adapter_supports_provider())
    print("\n✅ 提供商支持检查通过\n")
    
    # 如果有 API key，运行其他测试
    if os.getenv("QWEN_API_KEY"):
        asyncio.run(test_lazyllm_adapter_with_history())
        print("\n✅ 历史对话测试通过\n")
    
    print("=" * 60)
    print("所有测试完成！")
    print("=" * 60)
