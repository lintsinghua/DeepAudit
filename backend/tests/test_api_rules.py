"""
Tests for app/api/v1/endpoints/rules.py

Covers:
- list_rule_sets: listing, filtering, empty
- get_rule_set: success, 404, 403
- create_rule_set: success
- update_rule_set: success, 404, 403 system, 403 wrong owner
- delete_rule_set: success, 404, 403 system, 403 wrong owner
- add_rule_to_set: success, 404, 403 system
- toggle_rule: success toggling enabled/disabled
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.v1.endpoints.rules import (
    get_rule_set,
    create_rule_set,
    update_rule_set,
    delete_rule_set,
    add_rule_to_set,
    toggle_rule,
)
from app.schemas.audit_rule import AuditRuleSetCreate, AuditRuleCreate, AuditRuleSetUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user-001"
OTHER_USER_ID = "user-002"
RULE_SET_ID = "rs-001"
RULE_ID = "rule-001"


def _make_user(user_id=USER_ID, is_superuser=False):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    return user


def _make_rule(
    rule_id=RULE_ID,
    rule_set_id=RULE_SET_ID,
    enabled=True,
):
    rule = MagicMock()
    rule.id = rule_id
    rule.rule_set_id = rule_set_id
    rule.rule_code = "SEC001"
    rule.name = "SQL Injection Detection"
    rule.description = "Detects SQL injection vulnerabilities"
    rule.category = "security"
    rule.severity = "high"
    rule.custom_prompt = None
    rule.fix_suggestion = "Use parameterized queries"
    rule.reference_url = "https://owasp.org/www-community/attacks/SQL_Injection"
    rule.enabled = enabled
    rule.sort_order = 0
    rule.created_at = datetime.now(timezone.utc)
    rule.updated_at = None
    return rule


def _make_rule_set(
    rule_set_id=RULE_SET_ID,
    created_by=USER_ID,
    is_system=False,
    is_active=True,
    is_default=False,
    rules=None,
):
    rs = MagicMock()
    rs.id = rule_set_id
    rs.name = "Security Rules"
    rs.description = "Default security rule set"
    rs.language = "python"
    rs.rule_type = "security"
    rs.severity_weights = json.dumps({"critical": 10, "high": 5, "medium": 2, "low": 1})
    rs.is_default = is_default
    rs.is_system = is_system
    rs.is_active = is_active
    rs.sort_order = 0
    rs.created_by = created_by
    rs.created_at = datetime.now(timezone.utc)
    rs.updated_at = None
    rs.rules = rules if rules is not None else []
    return rs


def _scalar_one_or_none(obj):
    """Build mock result that returns obj via scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _scalars_all(objects):
    """Build mock result: result.scalars().all() -> objects."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = objects
    result.scalars.return_value = scalars_mock
    return result


# ===================================================================
# list_rule_sets -- tested via mocked db.execute calls.
# The function uses Query() defaults for skip/limit, so we call it
# with explicit integer arguments.
# ===================================================================

class TestListRuleSets:

    @pytest.mark.asyncio
    async def test_list_rule_sets_returns_items(self):
        """Returns system + user-owned rule sets."""
        from app.api.v1.endpoints.rules import list_rule_sets

        rs = _make_rule_set()
        db = AsyncMock()

        # The function executes two queries:
        #   1. count query -> scalar() returns total
        #   2. data query -> scalars().unique().all() returns items
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        # For the data query, the result chain is:
        # result.scalars() -> scalars_result, scalars_result.unique() -> unique_result, unique_result.all() -> list
        data_result = MagicMock()
        scalars_result = MagicMock()
        unique_result = MagicMock()
        unique_result.all.return_value = [rs]
        scalars_result.unique.return_value = unique_result
        data_result.scalars.return_value = scalars_result

        db.execute.side_effect = [count_result, data_result]

        user = _make_user()
        # Pass skip and limit explicitly to avoid Query() default issue
        result = await list_rule_sets(skip=0, limit=100, db=db, current_user=user)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == RULE_SET_ID

    @pytest.mark.asyncio
    async def test_list_rule_sets_empty(self):
        """Returns empty list when no rule sets exist."""
        from app.api.v1.endpoints.rules import list_rule_sets

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        data_result = MagicMock()
        scalars_result = MagicMock()
        unique_result = MagicMock()
        unique_result.all.return_value = []
        scalars_result.unique.return_value = unique_result
        data_result.scalars.return_value = scalars_result

        db.execute.side_effect = [count_result, data_result]

        user = _make_user()
        result = await list_rule_sets(skip=0, limit=100, db=db, current_user=user)

        assert result.total == 0
        assert result.items == []


# ===================================================================
# get_rule_set
# ===================================================================

class TestGetRuleSet:

    @pytest.mark.asyncio
    async def test_get_rule_set_success(self):
        """Returns a user-owned rule set."""
        rule = _make_rule()
        rs = _make_rule_set(rules=[rule])
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        result = await get_rule_set(rule_set_id=RULE_SET_ID, db=db, current_user=user)

        assert result.id == RULE_SET_ID
        assert result.rules_count == 1
        assert result.enabled_rules_count == 1

    @pytest.mark.asyncio
    async def test_get_rule_set_system_visible(self):
        """System rule sets are visible to all users."""
        rs = _make_rule_set(created_by="admin", is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        result = await get_rule_set(rule_set_id=RULE_SET_ID, db=db, current_user=user)

        assert result.id == RULE_SET_ID
        assert result.is_system is True

    @pytest.mark.asyncio
    async def test_get_rule_set_not_found(self):
        """Raises 404 when rule set does not exist."""
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(None)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await get_rule_set(rule_set_id="nonexistent", db=db, current_user=user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_rule_set_wrong_owner_forbidden(self):
        """Raises 403 when accessing another user's non-system rule set."""
        rs = _make_rule_set(created_by=OTHER_USER_ID, is_system=False)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await get_rule_set(rule_set_id=RULE_SET_ID, db=db, current_user=user)
        assert exc_info.value.status_code == 403


# ===================================================================
# create_rule_set
# ===================================================================

class TestCreateRuleSet:

    @pytest.mark.asyncio
    async def test_create_rule_set_with_rules(self):
        """Creates a rule set with embedded rules."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        # After flush, the rule_set gets an id.
        # After commit + refresh, we need id/created_at on the rule_set.
        async def fake_flush():
            pass

        db.flush = AsyncMock(side_effect=fake_flush)

        async def fake_refresh(obj):
            if not hasattr(obj, '_refreshed'):
                obj._refreshed = True
                obj.id = getattr(obj, 'id', None) or "new-rs-001"
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = None

        db.refresh = AsyncMock(side_effect=fake_refresh)

        # When AuditRule objects are added, give them proper ids
        add_count = [0]

        def fake_add(obj):
            add_count[0] += 1
            if not getattr(obj, 'id', None):
                obj.id = f"rule-auto-{add_count[0]}"
            if not getattr(obj, 'rule_set_id', None):
                obj.rule_set_id = "new-rs-001"

        db.add.side_effect = fake_add

        user = _make_user()
        rule_in = AuditRuleCreate(
            rule_code="SEC001",
            name="SQL Injection",
            category="security",
            severity="high",
            description="SQL injection",
        )
        rs_in = AuditRuleSetCreate(
            name="My Rules",
            language="python",
            rule_type="security",
            rules=[rule_in],
        )

        result = await create_rule_set(rule_set_in=rs_in, db=db, current_user=user)

        assert result.name == "My Rules"
        assert result.is_system is False
        assert result.is_default is False
        assert len(result.rules) == 1

    @pytest.mark.asyncio
    async def test_create_rule_set_empty_rules(self):
        """Creates a rule set with no rules."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.id = "rs-new-001"
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = None

        db.refresh = AsyncMock(side_effect=fake_refresh)

        user = _make_user()
        rs_in = AuditRuleSetCreate(
            name="Empty Set",
            language="all",
        )

        result = await create_rule_set(rule_set_in=rs_in, db=db, current_user=user)

        assert result.name == "Empty Set"
        assert result.rules == []
        assert result.rules_count == 0


# ===================================================================
# update_rule_set
# ===================================================================

class TestUpdateRuleSet:

    @pytest.mark.asyncio
    async def test_update_user_rule_set(self):
        """Update name of a user-owned rule set."""
        rule = _make_rule()
        rs = _make_rule_set(rules=[rule])
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        update = AuditRuleSetUpdate(name="Updated Name")

        result = await update_rule_set(
            rule_set_id=RULE_SET_ID, rule_set_in=update, db=db, current_user=user
        )

        assert rs.name == "Updated Name"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_system_rule_set_only_active(self):
        """System rule sets can only have is_active toggled."""
        rule = _make_rule()
        rs = _make_rule_set(is_system=True, rules=[rule])
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user(is_superuser=True)
        update = AuditRuleSetUpdate(is_active=False)

        result = await update_rule_set(
            rule_set_id=RULE_SET_ID, rule_set_in=update, db=db, current_user=user
        )

        assert rs.is_active is False
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_system_rule_set_other_fields_forbidden(self):
        """System rule sets reject updates to non-active fields."""
        rs = _make_rule_set(is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        update = AuditRuleSetUpdate(name="Hacked")

        with pytest.raises(HTTPException) as exc_info:
            await update_rule_set(
                rule_set_id=RULE_SET_ID, rule_set_in=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_rule_set_not_found(self):
        """Raises 404 when rule set does not exist."""
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(None)

        user = _make_user()
        update = AuditRuleSetUpdate(name="X")

        with pytest.raises(HTTPException) as exc_info:
            await update_rule_set(
                rule_set_id="nonexistent", rule_set_in=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_rule_set_wrong_owner_forbidden(self):
        """Raises 403 when updating another user's rule set."""
        rs = _make_rule_set(created_by=OTHER_USER_ID)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        update = AuditRuleSetUpdate(name="Hacked")

        with pytest.raises(HTTPException) as exc_info:
            await update_rule_set(
                rule_set_id=RULE_SET_ID, rule_set_in=update, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403


# ===================================================================
# delete_rule_set
# ===================================================================

class TestDeleteRuleSet:

    @pytest.mark.asyncio
    async def test_delete_user_rule_set(self):
        """Deletes a user-owned rule set."""
        rs = _make_rule_set()
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        result = await delete_rule_set(
            rule_set_id=RULE_SET_ID, db=db, current_user=user
        )

        assert result["message"] == "规则集已删除"
        db.delete.assert_called_once_with(rs)

    @pytest.mark.asyncio
    async def test_delete_system_rule_set_forbidden(self):
        """System rule sets cannot be deleted."""
        rs = _make_rule_set(is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await delete_rule_set(
                rule_set_id=RULE_SET_ID, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403
        assert "系统规则集不允许删除" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_rule_set_not_found(self):
        """Raises 404 when rule set does not exist."""
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(None)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await delete_rule_set(
                rule_set_id="nonexistent", db=db, current_user=user
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_rule_set_wrong_owner_forbidden(self):
        """Raises 403 when deleting another user's rule set."""
        rs = _make_rule_set(created_by=OTHER_USER_ID)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await delete_rule_set(
                rule_set_id=RULE_SET_ID, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403


# ===================================================================
# add_rule_to_set
# ===================================================================

class TestAddRuleToSet:

    @pytest.mark.asyncio
    async def test_add_rule_success(self):
        """Adds a rule to a user-owned rule set."""
        rs = _make_rule_set()
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.id = "new-rule-001"

        db.refresh = AsyncMock(side_effect=fake_refresh)

        user = _make_user()
        rule_in = AuditRuleCreate(
            rule_code="PERF001",
            name="N+1 Query",
            category="performance",
            severity="medium",
        )

        result = await add_rule_to_set(
            rule_set_id=RULE_SET_ID, rule_in=rule_in, db=db, current_user=user
        )

        assert result.rule_code == "PERF001"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_rule_to_system_set_forbidden(self):
        """Cannot add rules to system rule sets."""
        rs = _make_rule_set(is_system=True)
        db = AsyncMock()
        db.execute.return_value = _scalar_one_or_none(rs)

        user = _make_user()
        rule_in = AuditRuleCreate(
            rule_code="SEC002",
            name="XSS",
            category="security",
            severity="high",
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_rule_to_set(
                rule_set_id=RULE_SET_ID, rule_in=rule_in, db=db, current_user=user
            )
        assert exc_info.value.status_code == 403
        assert "系统规则集不允许添加规则" in exc_info.value.detail


# ===================================================================
# toggle_rule
# ===================================================================

class TestToggleRule:

    @pytest.mark.asyncio
    async def test_toggle_rule_enabled_to_disabled(self):
        """Toggle a rule from enabled to disabled."""
        rs = _make_rule_set()
        rule = _make_rule(enabled=True)
        db = AsyncMock()

        rs_result = _scalar_one_or_none(rs)
        rule_result = _scalar_one_or_none(rule)
        db.execute.side_effect = [rs_result, rule_result]

        user = _make_user()
        result = await toggle_rule(
            rule_set_id=RULE_SET_ID, rule_id=RULE_ID, db=db, current_user=user
        )

        assert rule.enabled is False
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_toggle_rule_disabled_to_enabled(self):
        """Toggle a rule from disabled to enabled."""
        rs = _make_rule_set()
        rule = _make_rule(enabled=False)
        db = AsyncMock()

        rs_result = _scalar_one_or_none(rs)
        rule_result = _scalar_one_or_none(rule)
        db.execute.side_effect = [rs_result, rule_result]

        user = _make_user()
        result = await toggle_rule(
            rule_set_id=RULE_SET_ID, rule_id=RULE_ID, db=db, current_user=user
        )

        assert rule.enabled is True
        assert result["enabled"] is True
