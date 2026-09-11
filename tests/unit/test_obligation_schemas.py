"""Validation and role boundaries for obligation operations."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from termnova.obligations.schemas import ObligationCreateFromFactRequest
from termnova.security.tenancy import ROLE_PERMISSIONS


def test_due_date_requires_an_explicit_timezone():
    with pytest.raises(ValidationError, match="timezone"):
        ObligationCreateFromFactRequest(due_at=datetime(2026, 10, 1, 9, 0))


def test_obligation_owner_can_act_but_cannot_reassign_work():
    permissions = ROLE_PERMISSIONS["obligation-owner"]
    assert "obligation:read" in permissions
    assert "obligation:act" in permissions
    assert "obligation:write" not in permissions


def test_read_only_roles_cannot_mutate_obligations():
    permissions = ROLE_PERMISSIONS["read-only"]
    assert "obligation:read" in permissions
    assert "obligation:act" not in permissions
    assert "obligation:write" not in permissions
