"""
提示词模板 API 端点
"""

import json
import time
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func as sql_func

from app.api import deps
from app.db.session import get_db
from app.models.prompt_template import PromptTemplate
from app.models.user import User
from app.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
    PromptTemplateResponse,
    PromptTemplateListResponse,
    PromptTestRequest,
    PromptTestResponse,
)

router = APIRouter()


@router.get("", response_model=PromptTemplateListResponse)
async def list_prompt_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    template_type: Optional[str] = Query(None, description="模板类型过滤"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取提示词模板列表。

    处理流程：
    - 构建模板查询（系统模板 + 用户模板）
    - 应用筛选与排序
    - 统计总数并分页
    - 解析变量并返回列表
    """
    # 构建基础查询
    query = select(PromptTemplate)
    # 过滤条件：系统模板 + 当前用户创建的模板
    query = query.where(
        (PromptTemplate.is_system == True) | 
        (PromptTemplate.created_by == current_user.id)
    )
    # 可选过滤条件
    if template_type:
        query = query.where(PromptTemplate.template_type == template_type)
    if is_active is not None:
        query = query.where(PromptTemplate.is_active == is_active)
    # 排序：系统模板优先，然后按排序权重和创建时间
    query = query.order_by(
        PromptTemplate.is_system.desc(),
        PromptTemplate.is_default.desc(),
        PromptTemplate.sort_order.asc(),
        PromptTemplate.created_at.desc()
    )
    # 统计总数
    count_query = select(sql_func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()
    # 分页查询
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    templates = result.scalars().all()
    # 组装响应项
    items = []
    for t in templates:
        # 解析变量 JSON
        variables = {}
        if t.variables:
            try:
                variables = json.loads(t.variables)
            except:
                pass
        # 构建响应对象
        items.append(PromptTemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            template_type=t.template_type,
            content_zh=t.content_zh,
            content_en=t.content_en,
            variables=variables,
            is_default=t.is_default,
            is_system=t.is_system,
            is_active=t.is_active,
            sort_order=t.sort_order,
            created_by=t.created_by,
            created_at=t.created_at,
            updated_at=t.updated_at,
        ))
    # 返回列表响应
    return PromptTemplateListResponse(items=items, total=total)


@router.get("/{template_id}", response_model=PromptTemplateResponse)
async def get_prompt_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取单个提示词模板。

    处理流程：
    - 查询模板
    - 校验存在性与权限
    - 解析变量并返回
    """
    # 查询模板
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    # 获取模板对象
    template = result.scalar_one_or_none()
    # 若模板不存在则返回 404
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    # 校验权限：系统模板对所有人可见
    if not template.is_system and template.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此模板")
    # 解析变量 JSON
    variables = {}
    if template.variables:
        try:
            variables = json.loads(template.variables)
        except:
            pass
    # 返回模板响应
    return PromptTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        template_type=template.template_type,
        content_zh=template.content_zh,
        content_en=template.content_en,
        variables=variables,
        is_default=template.is_default,
        is_system=template.is_system,
        is_active=template.is_active,
        sort_order=template.sort_order,
        created_by=template.created_by,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.post("", response_model=PromptTemplateResponse)
async def create_prompt_template(
    template_in: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    创建提示词模板。

    处理流程：
    - 构建模板对象
    - 保存并刷新
    - 返回创建结果
    """
    # 构建模板对象
    template = PromptTemplate(
        name=template_in.name,
        description=template_in.description,
        template_type=template_in.template_type,
        content_zh=template_in.content_zh,
        content_en=template_in.content_en,
        variables=json.dumps(template_in.variables or {}),
        is_active=template_in.is_active,
        sort_order=template_in.sort_order,
        is_system=False,
        is_default=False,
        created_by=current_user.id,
    )
    # 保存模板
    db.add(template)
    await db.commit()
    # 刷新对象以获取最新数据
    await db.refresh(template)
    # 返回创建结果
    return PromptTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        template_type=template.template_type,
        content_zh=template.content_zh,
        content_en=template.content_en,
        variables=template_in.variables or {},
        is_default=template.is_default,
        is_system=template.is_system,
        is_active=template.is_active,
        sort_order=template.sort_order,
        created_by=template.created_by,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.put("/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(
    template_id: str,
    template_in: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新提示词模板。

    处理流程：
    - 查询模板
    - 校验权限与系统模板限制
    - 应用更新并保存
    - 返回更新结果
    """
    # 查询模板
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    # 获取模板对象
    template = result.scalar_one_or_none()
    # 若模板不存在则返回 404
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    # 系统模板不允许修改核心内容，只能修改启用状态
    if template.is_system:
        if template_in.is_active is not None:
            template.is_active = template_in.is_active
        else:
            raise HTTPException(status_code=403, detail="系统模板不允许修改")
    else:
        # 校验权限
        if template.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权修改此模板")
        # 更新字段
        update_data = template_in.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field == "variables" and value is not None:
                setattr(template, field, json.dumps(value))
            elif field != "is_default":  # 不允许用户设置默认
                setattr(template, field, value)
    # 提交更新
    await db.commit()
    # 刷新对象
    await db.refresh(template)
    # 解析变量 JSON
    variables = {}
    if template.variables:
        try:
            variables = json.loads(template.variables)
        except:
            pass
    # 返回更新结果
    return PromptTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        template_type=template.template_type,
        content_zh=template.content_zh,
        content_en=template.content_en,
        variables=variables,
        is_default=template.is_default,
        is_system=template.is_system,
        is_active=template.is_active,
        sort_order=template.sort_order,
        created_by=template.created_by,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.delete("/{template_id}")
async def delete_prompt_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    删除提示词模板。

    处理流程：
    - 查询模板
    - 校验存在性与权限
    - 删除并提交
    - 返回删除结果
    """
    # 查询模板
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    # 获取模板对象
    template = result.scalar_one_or_none()
    # 若模板不存在则返回 404
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    # 系统模板禁止删除
    if template.is_system:
        raise HTTPException(status_code=403, detail="系统模板不允许删除")
    # 校验权限
    if template.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此模板")
    # 删除模板
    await db.delete(template)
    await db.commit()
    # 返回删除结果
    return {"message": "模板已删除"}


@router.post("/test", response_model=PromptTestResponse)
async def test_prompt_template(
    request: PromptTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    测试提示词效果。

    处理流程：
    - 读取并解密用户配置
    - 创建 LLM 服务
    - 使用自定义提示词进行分析
    - 返回测试结果
    """
    # 延迟导入依赖
    from app.services.llm.service import LLMService
    from app.models.user_config import UserConfig
    from app.core.encryption import decrypt_sensitive_data
    # 记录开始时间
    start_time = time.time()
    try:
        # 获取用户配置
        user_config = {}
        result_config = await db.execute(
            select(UserConfig).where(UserConfig.user_id == current_user.id)
        )
        # 获取配置对象
        config = result_config.scalar_one_or_none()
        if config:
            # 需要解密的敏感字段
            SENSITIVE_LLM_FIELDS = [
                'llmApiKey', 'geminiApiKey', 'openaiApiKey', 'claudeApiKey',
                'qwenApiKey', 'deepseekApiKey', 'zhipuApiKey', 'moonshotApiKey',
                'baiduApiKey', 'minimaxApiKey', 'doubaoApiKey'
            ]
            # 解析并解密 LLM 配置
            llm_config = json.loads(config.llm_config) if config.llm_config else {}
            for field in SENSITIVE_LLM_FIELDS:
                if field in llm_config and llm_config[field]:
                    llm_config[field] = decrypt_sensitive_data(llm_config[field])
            # 组装用户配置
            user_config = {'llmConfig': llm_config}
        # 创建使用用户配置的 LLM 服务实例
        llm_service = LLMService(user_config=user_config)
        # 使用自定义提示词进行分析
        result = await llm_service.analyze_code_with_custom_prompt(
            code=request.code,
            language=request.language,
            custom_prompt=request.content,
            output_language=request.output_language,
        )
        # 计算耗时
        execution_time = time.time() - start_time
        # 返回成功结果
        return PromptTestResponse(
            success=True,
            result=result,
            execution_time=round(execution_time, 2),
        )
    except Exception as e:
        # 计算耗时
        execution_time = time.time() - start_time
        # 记录异常信息
        import traceback
        print(f"❌ 提示词测试失败: {e}")
        print(traceback.format_exc())
        # 返回失败结果
        return PromptTestResponse(
            success=False,
            error=str(e),
            execution_time=round(execution_time, 2),
        )


@router.post("/{template_id}/set-default")
async def set_default_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    设置默认模板（仅管理员）。

    处理流程：
    - 校验管理员权限
    - 查询模板
    - 取消同类型默认模板
    - 设置当前模板为默认
    """
    # 仅管理员可设置默认模板
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="仅管理员可设置默认模板")
    # 查询目标模板
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    # 获取模板对象
    template = result.scalar_one_or_none()
    # 若模板不存在则返回 404
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    
    # 取消同类型的其他默认模板
    await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.template_type == template.template_type)
        .where(PromptTemplate.is_default == True)
    )
    same_type_defaults = (await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.template_type == template.template_type)
        .where(PromptTemplate.is_default == True)
    )).scalars().all()
    
    for t in same_type_defaults:
        t.is_default = False
    
    # 设置新的默认模板
    template.is_default = True
    
    await db.commit()
    
    return {"message": "已设置为默认模板"}
