"""Organization membership, RBAC, and ORM tenant-boundary tests."""

import uuid

import pytest
from sqlalchemy import select

from termnova.config import Settings
from termnova.db.models import Document, Organization, OrganizationMembership
from termnova.security.auth import RequestPrincipal
from termnova.security.tenancy import ROLE_PERMISSIONS, resolve_tenant_context


@pytest.mark.asyncio
async def test_local_principal_resolves_server_managed_membership(test_session):
    principal = RequestPrincipal(
        subject="local-development",
        organization_id="local",
        display_name="Local User",
        email=None,
        roles=frozenset({"local-admin"}),
        auth_method="local",
        is_authenticated=False,
    )
    tenant = await resolve_tenant_context(
        test_session, principal, Settings(APP_ENV="test", LLM_PROVIDER="mock")
    )

    assert tenant.organization_external_id == "local"
    assert tenant.allows("tenant:admin")
    membership = (
        await test_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.subject == "local-development"
            )
        )
    ).scalar_one()
    assert membership.roles == ["local-admin"]


@pytest.mark.asyncio
async def test_unprovisioned_production_organization_is_denied(test_session):
    principal = RequestPrincipal(
        subject="untrusted-subject",
        organization_id="unknown-customer",
        display_name="Unknown",
        email=None,
        roles=frozenset({"administrator"}),
        auth_method="oidc",
        is_authenticated=True,
    )
    settings = Settings(
        APP_ENV="production",
        LLM_PROVIDER="mock",
        OIDC_ISSUER="https://id.example.com",
    )

    with pytest.raises(Exception, match="Organization is not provisioned"):
        await resolve_tenant_context(test_session, principal, settings)


@pytest.mark.asyncio
async def test_session_rejects_cross_tenant_record(test_session):
    other = Organization(external_id="other", name="Other")
    test_session.add(other)
    await test_session.flush()
    document = Document(
        organization_id=other.id,
        filename="other.pdf",
        file_type="pdf",
    )
    test_session.add(document)

    with pytest.raises(ValueError, match="cannot cross"):
        await test_session.flush()


def test_every_business_role_has_least_privilege_permissions():
    assert ROLE_PERMISSIONS["administrator"] == frozenset({"*"})
    assert "document:write" not in ROLE_PERMISSIONS["read-only"]
    assert "audit:read" in ROLE_PERMISSIONS["auditor"]
    assert uuid.UUID("00000000-0000-0000-0000-000000000001")
