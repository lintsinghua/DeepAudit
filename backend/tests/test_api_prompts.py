"""
Tests for app/api/v1/endpoints/prompts.py

Covers:
- list_prompt_templates: listing, filtering, pagination
- get_prompt_template: success, 404, 403
- create_prompt_template: success
- update_prompt_template: user-owned, system (active only), 403/404
- delete_prompt_template: success, system forbidden, wrong owner
- set_default_template: admin-only, 403 non-admin
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.v1.endpoints.prompts import (
    list_prompt_templates,
    get_prompt_template,
    create_prompt_template,
    update_prompt_template,
    delete_prompt_template,
    set_default_template,
)
from app.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user-001"
OTHER_USER_ID = "user-002"
TEMPLATE_ID = "tmpl-001"


def _make_user(user_id=USER_ID, is_superuser=False):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    return user


def _make_template(
    template_id=TEMPLATE_ID,
    created_by=USER_ID,
    is_system=False,
    is_active=True,
    is_default=False,
):
    tmpl = MagicMock()
    tmpl.id = template_id
    tmpl.name = "Security Analysis Prompt"
    tmpl.description = "Prompt for security analysis"
    tmpl.template_type = "analysis"
    tmpl.content_zh = "分析以下代码的安全问题"
    tmpl.content_en = "Analyze the following code for security issues"
    tmpl.variables = json.dumps({"language": "编程语言", "code": "代码内容"})
    tmpl.is_default = is_default
    tmpl.is_system = is_system
    tmpl.is_active = is_active
    tmpl.sort_order = 0
    tmpl.created_by = created_by
    tmpl.created_at = datetime.now(timezone.utc)
    tmpl.updated_at = None
    return tmpl


def _scalar_one_or_none(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _scalars_all(objects):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = objects
    result.scalars.return_value = scalars_mock
    return result


# ===================================================================
# list_prompt_templates
# ===================================================================

class TestListPromptTemplates:

    @pytest.mark.asyncio
    async def test_list_templates_returns_items(self):
        """Returns system + user-owned templates."""
        tmpl = _make_template()
        db = AsyncMock()

        # First execute: count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        # Second execute: data query
        data_result = _scalars_all([tmpl])

        db.execute.side_effect = [count_result, data_result]

        user = _make_user()
        result = await list_prompt_templates(skip=0, limit=100, db=db, current_user=user)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == TEMPLATE_ID

    @pytest.mark.asyncio
    async def test_list_templates_empty(self):
        """Returns empty list when no templates exist."""
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = _scalars_all([])

        db.execute.side_effect = [count_result, data_result]

        user = _make_user()
        result = await list_prompt_templates(skip=0, limit=100, db=db, current_user=user)

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_list_templates_parses_variables(self):
        """Variables JSON is properly parsed into a dict."""
        tmpl = _make_template()
        tmpl.variables = '{"key": "value"}'
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = _scalars_all([tmpl])

        db.execute.side_effect = [count_result, data_result]

        user = _make_user()
        result = await list_prompt_templates(skip=0, limit=100, db=db, current_user=user)

        assert result.items[0].variables == {"key": "value"}

    @pytest.mark.asyncio
    async def test_list_templates_invalid_variables_fallback(self):
        """Invalid JSON in variables falls back to empty dict."""
        tmpl = _make_template()
        tmpl.variables = "not valid json"
        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = _scalars_all([tmpl])

        db.execute.side_effect = [count_result, data_result]

        user = _make_user()
        result = await list_prompt_templates(skip=0, limit=100, db=db, current_user=user)

        assert result.items[0].variables == {}


# ===================================================================
# get_prompt_template
# ===================================================================

class TestGetPromptTemplate:

    @pytest.mark.asyncio
    async def test_get_template_success(self):
        """Returns a user-owned template."""
        tmpl = _make_template()
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        result = await get_prompt_template(
            template_id=TEMPLATE_ID, db=db, current_user=user
        )

        assert result.id == TEMPLATE_ID
        assert result.name == "Security Analysis Prompt"

    @pytest.mark.asyncio
    async def test_get_system_template_visible(self):
        """System templates are visible to all users."""
        tmpl = _make_template(created_by="admin", is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        result = await get_prompt_template(
            template_id=TEMPLATE_ID, db=db, current_user=user
        )

        assert result.is_system is True

    @pytest.mark.asyncio
    async def test_get_template_not_found(self):
        """Raises 404 when template does not exist."""
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(None)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await get_prompt_template(
                template_id="nonexistent", db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_template_wrong_owner_forbidden(self):
        """Raises 403 when accessing another user's non-system template."""
        tmpl = _make_template(created_by=OTHER_USER_ID, is_system=False)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await get_prompt_template(
                template_id=TEMPLATE_ID, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403


# ===================================================================
# create_prompt_template
# ===================================================================

class TestCreatePromptTemplate:

    @pytest.mark.asyncio
    async def test_create_template_success(self):
        """Creates a new user template."""
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.id = "new-tmpl-001"
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = None

        db.refresh = AsyncMock(side_effect=fake_refresh)

        user = _make_user()
        tmpl_in = PromptTemplateCreate(
            name="My Prompt",
            description="Custom prompt",
            template_type="analysis",
            content_zh="分析代码",
            content_en="Analyze code",
            variables={"lang": "language"},
        )

        result = await create_prompt_template(
            template_in=tmpl_in, db=db, current_user=user
        )

        assert result.name == "My Prompt"
        assert result.is_system is False
        assert result.is_default is False
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ===================================================================
# update_prompt_template
# ===================================================================

class TestUpdatePromptTemplate:

    @pytest.mark.asyncio
    async def test_update_user_template(self):
        """Update name of a user-owned template."""
        tmpl = _make_template()
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        update = PromptTemplateUpdate(name="Updated Prompt")

        result = await update_prompt_template(
            template_id=TEMPLATE_ID, template_in=update, db=db, current_user=user
        )

        assert tmpl.name == "Updated Prompt"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_system_template_active_only(self):
        """System templates can only have is_active toggled."""
        tmpl = _make_template(is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user(is_superuser=True)
        update = PromptTemplateUpdate(is_active=False)

        result = await update_prompt_template(
            template_id=TEMPLATE_ID, template_in=update, db=db, current_user=user
        )

        assert tmpl.is_active is False
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_system_template_other_fields_forbidden(self):
        """System templates reject updates to core fields without is_active."""
        tmpl = _make_template(is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        update = PromptTemplateUpdate(name="Hacked")

        with pytest.raises(HTTPException) as exc_info:
            await update_prompt_template(
                template_id=TEMPLATE_ID, template_in=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_template_not_found(self):
        """Raises 404 when template does not exist."""
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(None)

        user = _make_user()
        update = PromptTemplateUpdate(name="X")

        with pytest.raises(HTTPException) as exc_info:
            await update_prompt_template(
                template_id="nonexistent", template_in=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_template_wrong_owner_forbidden(self):
        """Raises 403 when updating another user's template."""
        tmpl = _make_template(created_by=OTHER_USER_ID, is_system=False)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        update = PromptTemplateUpdate(name="Hacked")

        with pytest.raises(HTTPException) as exc_info:
            await update_prompt_template(
                template_id=TEMPLATE_ID, template_in=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403


# ===================================================================
# delete_prompt_template
# ===================================================================

class TestDeletePromptTemplate:

    @pytest.mark.asyncio
    async def test_delete_user_template(self):
        """Deletes a user-owned template."""
        tmpl = _make_template()
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        result = await delete_prompt_template(
            template_id=TEMPLATE_ID, db=db, current_user=user
        )

        assert result["message"] == "模板已删除"
        db.delete.assert_called_once_with(tmpl)

    @pytest.mark.asyncio
    async def test_delete_system_template_forbidden(self):
        """System templates cannot be deleted."""
        tmpl = _make_template(is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await delete_prompt_template(
                template_id=TEMPLATE_ID, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403
        assert "系统模板不允许删除" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_template_not_found(self):
        """Raises 404 when template does not exist."""
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(None)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await delete_prompt_template(
                template_id="nonexistent", db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_template_wrong_owner_forbidden(self):
        """Raises 403 when deleting another user's template."""
        tmpl = _make_template(created_by=OTHER_USER_ID, is_system=False)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(tmpl)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await delete_prompt_template(
                template_id=TEMPLATE_ID, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403


# ===================================================================
# set_default_template
# ===================================================================

class TestSetDefaultTemplate:

    @pytest.mark.asyncio
    async def test_admin_can_set_default(self):
        """Admin user can set a template as default."""
        tmpl = _make_template()
        db = AsyncMock()

        # First execute: fetch template
        tmpl_result = _scalar_one_or_none(tmpl)
        # Second + third execute: find existing defaults
        defaults_result = _scalars_all([])
        db.execute.side_effect = [tmpl_result, defaults_result, defaults_result]

        user = _make_user(is_superuser=True)
        result = await set_default_template(
            template_id=TEMPLATE_ID, db=db, current_user=user
        )

        assert tmpl.is_default is True
        assert result["message"] == "已设置为默认模板"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self):
        """Non-admin users cannot set default templates."""
        db = AsyncMock()

        user = _make_user(is_superuser=False)
        with pytest.raises(HTTPException) as exc_info:
            await set_default_template(
                template_id=TEMPLATE_ID, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403
        assert "仅管理员" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_set_default_template_not_found(self):
        """Raises 404 when template does not exist."""
        db = AsyncMock()

        # First execute: fetch template -> not found
        tmpl_result = _scalar_one_or_none(None)
        db.execute.return_value = tmpl_result

        user = _make_user(is_superuser=True)
        with pytest.raises(HTTPException) as exc_info:
            await set_default_template(
                template_id="nonexistent", db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_set_default_clears_existing_defaults(self):
        """Setting a new default clears the previous default of the same type."""
        tmpl = _make_template()
        old_default = _make_template(template_id="old-default", is_default=True)

        db = AsyncMock()

        # First: fetch template
        tmpl_result = _scalar_one_or_none(tmpl)
        # Second + third: fetch existing defaults (returns old_default)
        defaults_result = _scalars_all([old_default])
        db.execute.side_effect = [tmpl_result, defaults_result, defaults_result]

        user = _make_user(is_superuser=True)
        await set_default_template(
            template_id=TEMPLATE_ID, db=db, current_user=user
        )

        # The old default should have been unset
        assert old_default.is_default is False
        assert tmpl.is_default is True
