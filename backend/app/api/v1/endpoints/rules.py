"""
审计规则 API 端点
"""

import json
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func as sql_func
from sqlalchemy.orm import selectinload

from app.api import deps
from app.db.session import get_db
from app.models.audit_rule import AuditRuleSet, AuditRule
from app.models.user import User
from app.schemas.audit_rule import (
    AuditRuleCreate,
    AuditRuleUpdate,
    AuditRuleResponse,
    AuditRuleSetCreate,
    AuditRuleSetUpdate,
    AuditRuleSetResponse,
    AuditRuleSetListResponse,
    AuditRuleSetExport,
    AuditRuleSetImport,
)

router = APIRouter()


# ==================== 规则集 API ====================

@router.get("", response_model=AuditRuleSetListResponse)
async def list_rule_sets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    language: Optional[str] = Query(None, description="语言过滤"),
    rule_type: Optional[str] = Query(None, description="类型过滤"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """获取审计规则集列表"""
    query = select(AuditRuleSet).options(selectinload(AuditRuleSet.rules))
    
    # 过滤条件：系统规则集 + 当前用户创建的规则集
    query = query.where(
        (AuditRuleSet.is_system == True) | 
        (AuditRuleSet.created_by == current_user.id)
    )
    
    if language:
        query = query.where(AuditRuleSet.language == language)
    if rule_type:
        query = query.where(AuditRuleSet.rule_type == rule_type)
    if is_active is not None:
        query = query.where(AuditRuleSet.is_active == is_active)
    
    # 排序
    query = query.order_by(
        AuditRuleSet.is_system.desc(),
        AuditRuleSet.is_default.desc(),
        AuditRuleSet.sort_order.asc(),
        AuditRuleSet.created_at.desc()
    )
    
    # 计数
    count_query = select(sql_func.count()).select_from(
        select(AuditRuleSet).where(
            (AuditRuleSet.is_system == True) | 
            (AuditRuleSet.created_by == current_user.id)
        ).subquery()
    )
    total = (await db.execute(count_query)).scalar()
    
    # 分页
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    rule_sets = result.scalars().unique().all()
    
    items = []
    for rs in rule_sets:
        severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
        if rs.severity_weights:
            try:
                severity_weights = json.loads(rs.severity_weights)
            except Exception:
                pass
        
        rules = [
            AuditRuleResponse(
                id=r.id,
                rule_set_id=r.rule_set_id,
                rule_code=r.rule_code,
                name=r.name,
                description=r.description,
                category=r.category,
                severity=r.severity,
                custom_prompt=r.custom_prompt,
                fix_suggestion=r.fix_suggestion,
                reference_url=r.reference_url,
                enabled=r.enabled,
                sort_order=r.sort_order,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rs.rules
        ]
        
        items.append(AuditRuleSetResponse(
            id=rs.id,
            name=rs.name,
            description=rs.description,
            language=rs.language,
            rule_type=rs.rule_type,
            severity_weights=severity_weights,
            is_default=rs.is_default,
            is_system=rs.is_system,
            is_active=rs.is_active,
            sort_order=rs.sort_order,
            created_by=rs.created_by,
            created_at=rs.created_at,
            updated_at=rs.updated_at,
            rules=rules,
            rules_count=len(rules),
            enabled_rules_count=len([r for r in rules if r.enabled]),
        ))
    
    return AuditRuleSetListResponse(items=items, total=total)


@router.get("/{rule_set_id}", response_model=AuditRuleSetResponse)
async def get_rule_set(
    rule_set_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """获取单个规则集"""
    result = await db.execute(
        select(AuditRuleSet)
        .options(selectinload(AuditRuleSet.rules))
        .where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if not rule_set.is_system and rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此规则集")
    
    severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    if rule_set.severity_weights:
        try:
            severity_weights = json.loads(rule_set.severity_weights)
        except Exception:
            pass
    
    rules = [
        AuditRuleResponse(
            id=r.id,
            rule_set_id=r.rule_set_id,
            rule_code=r.rule_code,
            name=r.name,
            description=r.description,
            category=r.category,
            severity=r.severity,
            custom_prompt=r.custom_prompt,
            fix_suggestion=r.fix_suggestion,
            reference_url=r.reference_url,
            enabled=r.enabled,
            sort_order=r.sort_order,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rule_set.rules
    ]
    
    return AuditRuleSetResponse(
        id=rule_set.id,
        name=rule_set.name,
        description=rule_set.description,
        language=rule_set.language,
        rule_type=rule_set.rule_type,
        severity_weights=severity_weights,
        is_default=rule_set.is_default,
        is_system=rule_set.is_system,
        is_active=rule_set.is_active,
        sort_order=rule_set.sort_order,
        created_by=rule_set.created_by,
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
        rules=rules,
        rules_count=len(rules),
        enabled_rules_count=len([r for r in rules if r.enabled]),
    )


@router.post("", response_model=AuditRuleSetResponse)
async def create_rule_set(
    rule_set_in: AuditRuleSetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """创建审计规则集"""
    rule_set = AuditRuleSet(
        name=rule_set_in.name,
        description=rule_set_in.description,
        language=rule_set_in.language,
        rule_type=rule_set_in.rule_type,
        severity_weights=json.dumps(rule_set_in.severity_weights or {}),
        is_active=rule_set_in.is_active,
        sort_order=rule_set_in.sort_order,
        is_system=False,
        is_default=False,
        created_by=current_user.id,
    )
    
    db.add(rule_set)
    await db.flush()
    
    # 创建规则
    rules = []
    for rule_in in (rule_set_in.rules or []):
        rule = AuditRule(
            rule_set_id=rule_set.id,
            rule_code=rule_in.rule_code,
            name=rule_in.name,
            description=rule_in.description,
            category=rule_in.category,
            severity=rule_in.severity,
            custom_prompt=rule_in.custom_prompt,
            fix_suggestion=rule_in.fix_suggestion,
            reference_url=rule_in.reference_url,
            enabled=rule_in.enabled,
            sort_order=rule_in.sort_order,
        )
        db.add(rule)
        rules.append(rule)
    
    await db.commit()
    await db.refresh(rule_set)
    
    return AuditRuleSetResponse(
        id=rule_set.id,
        name=rule_set.name,
        description=rule_set.description,
        language=rule_set.language,
        rule_type=rule_set.rule_type,
        severity_weights=rule_set_in.severity_weights or {},
        is_default=rule_set.is_default,
        is_system=rule_set.is_system,
        is_active=rule_set.is_active,
        sort_order=rule_set.sort_order,
        created_by=rule_set.created_by,
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
        rules=[
            AuditRuleResponse(
                id=r.id,
                rule_set_id=r.rule_set_id,
                rule_code=r.rule_code,
                name=r.name,
                description=r.description,
                category=r.category,
                severity=r.severity,
                custom_prompt=r.custom_prompt,
                fix_suggestion=r.fix_suggestion,
                reference_url=r.reference_url,
                enabled=r.enabled,
                sort_order=r.sort_order,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rules
        ],
        rules_count=len(rules),
        enabled_rules_count=len([r for r in rules if r.enabled]),
    )


@router.put("/{rule_set_id}", response_model=AuditRuleSetResponse)
async def update_rule_set(
    rule_set_id: str,
    rule_set_in: AuditRuleSetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """更新审计规则集"""
    result = await db.execute(
        select(AuditRuleSet)
        .options(selectinload(AuditRuleSet.rules))
        .where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if rule_set.is_system:
        # 系统规则集只能修改启用状态
        if rule_set_in.is_active is not None:
            rule_set.is_active = rule_set_in.is_active
        else:
            raise HTTPException(status_code=403, detail="系统规则集不允许修改")
    else:
        if rule_set.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="无权修改此规则集")
        
        update_data = rule_set_in.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field == "severity_weights" and value is not None:
                setattr(rule_set, field, json.dumps(value))
            elif field != "is_default":
                setattr(rule_set, field, value)
    
    await db.commit()
    await db.refresh(rule_set)
    
    severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    if rule_set.severity_weights:
        try:
            severity_weights = json.loads(rule_set.severity_weights)
        except Exception:
            pass
    
    rules = [
        AuditRuleResponse(
            id=r.id,
            rule_set_id=r.rule_set_id,
            rule_code=r.rule_code,
            name=r.name,
            description=r.description,
            category=r.category,
            severity=r.severity,
            custom_prompt=r.custom_prompt,
            fix_suggestion=r.fix_suggestion,
            reference_url=r.reference_url,
            enabled=r.enabled,
            sort_order=r.sort_order,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rule_set.rules
    ]
    
    return AuditRuleSetResponse(
        id=rule_set.id,
        name=rule_set.name,
        description=rule_set.description,
        language=rule_set.language,
        rule_type=rule_set.rule_type,
        severity_weights=severity_weights,
        is_default=rule_set.is_default,
        is_system=rule_set.is_system,
        is_active=rule_set.is_active,
        sort_order=rule_set.sort_order,
        created_by=rule_set.created_by,
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
        rules=rules,
        rules_count=len(rules),
        enabled_rules_count=len([r for r in rules if r.enabled]),
    )


@router.delete("/{rule_set_id}")
async def delete_rule_set(
    rule_set_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """删除审计规则集"""
    result = await db.execute(
        select(AuditRuleSet).where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if rule_set.is_system:
        raise HTTPException(status_code=403, detail="系统规则集不允许删除")
    
    if rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此规则集")
    
    await db.delete(rule_set)
    await db.commit()
    
    return {"message": "规则集已删除"}


@router.get("/{rule_set_id}/export")
async def export_rule_set(
    rule_set_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """导出规则集为JSON"""
    result = await db.execute(
        select(AuditRuleSet)
        .options(selectinload(AuditRuleSet.rules))
        .where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if not rule_set.is_system and rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权导出此规则集")
    
    severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    if rule_set.severity_weights:
        try:
            severity_weights = json.loads(rule_set.severity_weights)
        except Exception:
            pass
    
    export_data = {
        "name": rule_set.name,
        "description": rule_set.description,
        "language": rule_set.language,
        "rule_type": rule_set.rule_type,
        "severity_weights": severity_weights,
        "rules": [
            {
                "rule_code": r.rule_code,
                "name": r.name,
                "description": r.description,
                "category": r.category,
                "severity": r.severity,
                "custom_prompt": r.custom_prompt,
                "fix_suggestion": r.fix_suggestion,
                "reference_url": r.reference_url,
                "enabled": r.enabled,
                "sort_order": r.sort_order,
            }
            for r in rule_set.rules
        ],
        "export_version": "1.0",
    }
    
    # 使用 URL 编码处理中文文件名
    from urllib.parse import quote
    encoded_filename = quote(f"{rule_set.name}.json")
    
    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.post("/import", response_model=AuditRuleSetResponse)
async def import_rule_set(
    import_data: AuditRuleSetImport,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """导入规则集"""
    rule_set = AuditRuleSet(
        name=import_data.name,
        description=import_data.description,
        language=import_data.language,
        rule_type=import_data.rule_type,
        severity_weights=json.dumps(import_data.severity_weights or {}),
        is_active=True,
        is_system=False,
        is_default=False,
        created_by=current_user.id,
    )
    
    db.add(rule_set)
    await db.flush()
    
    rules = []
    for rule_in in import_data.rules:
        rule = AuditRule(
            rule_set_id=rule_set.id,
            rule_code=rule_in.rule_code,
            name=rule_in.name,
            description=rule_in.description,
            category=rule_in.category,
            severity=rule_in.severity,
            custom_prompt=rule_in.custom_prompt,
            fix_suggestion=rule_in.fix_suggestion,
            reference_url=rule_in.reference_url,
            enabled=rule_in.enabled,
            sort_order=rule_in.sort_order,
        )
        db.add(rule)
        rules.append(rule)
    
    await db.commit()
    await db.refresh(rule_set)
    
    return AuditRuleSetResponse(
        id=rule_set.id,
        name=rule_set.name,
        description=rule_set.description,
        language=rule_set.language,
        rule_type=rule_set.rule_type,
        severity_weights=import_data.severity_weights or {},
        is_default=rule_set.is_default,
        is_system=rule_set.is_system,
        is_active=rule_set.is_active,
        sort_order=rule_set.sort_order,
        created_by=rule_set.created_by,
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
        rules=[
            AuditRuleResponse(
                id=r.id,
                rule_set_id=r.rule_set_id,
                rule_code=r.rule_code,
                name=r.name,
                description=r.description,
                category=r.category,
                severity=r.severity,
                custom_prompt=r.custom_prompt,
                fix_suggestion=r.fix_suggestion,
                reference_url=r.reference_url,
                enabled=r.enabled,
                sort_order=r.sort_order,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rules
        ],
        rules_count=len(rules),
        enabled_rules_count=len([r for r in rules if r.enabled]),
    )


# ==================== 单个规则 API ====================

@router.post("/{rule_set_id}/rules", response_model=AuditRuleResponse)
async def add_rule_to_set(
    rule_set_id: str,
    rule_in: AuditRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """向规则集添加规则"""
    result = await db.execute(
        select(AuditRuleSet).where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if rule_set.is_system:
        raise HTTPException(status_code=403, detail="系统规则集不允许添加规则")
    
    if rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权修改此规则集")
    
    rule = AuditRule(
        rule_set_id=rule_set_id,
        rule_code=rule_in.rule_code,
        name=rule_in.name,
        description=rule_in.description,
        category=rule_in.category,
        severity=rule_in.severity,
        custom_prompt=rule_in.custom_prompt,
        fix_suggestion=rule_in.fix_suggestion,
        reference_url=rule_in.reference_url,
        enabled=rule_in.enabled,
        sort_order=rule_in.sort_order,
    )
    
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    
    return AuditRuleResponse(
        id=rule.id,
        rule_set_id=rule.rule_set_id,
        rule_code=rule.rule_code,
        name=rule.name,
        description=rule.description,
        category=rule.category,
        severity=rule.severity,
        custom_prompt=rule.custom_prompt,
        fix_suggestion=rule.fix_suggestion,
        reference_url=rule.reference_url,
        enabled=rule.enabled,
        sort_order=rule.sort_order,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.put("/{rule_set_id}/rules/{rule_id}", response_model=AuditRuleResponse)
async def update_rule(
    rule_set_id: str,
    rule_id: str,
    rule_in: AuditRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """更新规则"""
    result = await db.execute(
        select(AuditRuleSet).where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if rule_set.is_system:
        raise HTTPException(status_code=403, detail="系统规则集不允许修改规则")
    
    if rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权修改此规则集")
    
    result = await db.execute(
        select(AuditRule).where(
            AuditRule.id == rule_id,
            AuditRule.rule_set_id == rule_set_id
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    
    update_data = rule_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)
    
    await db.commit()
    await db.refresh(rule)
    
    return AuditRuleResponse(
        id=rule.id,
        rule_set_id=rule.rule_set_id,
        rule_code=rule.rule_code,
        name=rule.name,
        description=rule.description,
        category=rule.category,
        severity=rule.severity,
        custom_prompt=rule.custom_prompt,
        fix_suggestion=rule.fix_suggestion,
        reference_url=rule.reference_url,
        enabled=rule.enabled,
        sort_order=rule.sort_order,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.delete("/{rule_set_id}/rules/{rule_id}")
async def delete_rule(
    rule_set_id: str,
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """删除规则"""
    result = await db.execute(
        select(AuditRuleSet).where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    if rule_set.is_system:
        raise HTTPException(status_code=403, detail="系统规则集不允许删除规则")
    
    if rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权修改此规则集")
    
    result = await db.execute(
        select(AuditRule).where(
            AuditRule.id == rule_id,
            AuditRule.rule_set_id == rule_set_id
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    
    await db.delete(rule)
    await db.commit()
    
    return {"message": "规则已删除"}


@router.put("/{rule_set_id}/rules/{rule_id}/toggle")
async def toggle_rule(
    rule_set_id: str,
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """切换规则启用状态"""
    result = await db.execute(
        select(AuditRuleSet).where(AuditRuleSet.id == rule_set_id)
    )
    rule_set = result.scalar_one_or_none()
    
    if not rule_set:
        raise HTTPException(status_code=404, detail="规则集不存在")
    
    # 系统规则集也允许切换单个规则的启用状态
    if not rule_set.is_system and rule_set.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="无权修改此规则集")
    
    result = await db.execute(
        select(AuditRule).where(
            AuditRule.id == rule_id,
            AuditRule.rule_set_id == rule_set_id
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    
    rule.enabled = not rule.enabled
    await db.commit()
    
    return {"enabled": rule.enabled, "message": f"规则已{'启用' if rule.enabled else '禁用'}"}
