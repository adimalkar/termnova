"""Provision the first organization administrator without exposing a bootstrap API."""

import argparse
import asyncio

from sqlalchemy import select

from termnova.config import get_settings
from termnova.db.connection import AsyncSessionFactory, init_db
from termnova.db.models import Organization, OrganizationMembership
from termnova.security.tenancy import apply_organization_context


async def bootstrap(
    *, external_id: str, name: str, issuer: str, subject: str, display_name: str, email: str | None
) -> None:
    settings = get_settings()
    await init_db(settings)
    factory = AsyncSessionFactory()
    async with factory() as session:
        organization = (
            await session.execute(
                select(Organization).where(Organization.external_id == external_id)
            )
        ).scalar_one_or_none()
        if organization is None:
            organization = Organization(external_id=external_id, name=name)
            session.add(organization)
            await session.flush()
        await apply_organization_context(session, organization.id, actor_subject="bootstrap")
        membership = (
            await session.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization.id,
                    OrganizationMembership.identity_provider == issuer,
                    OrganizationMembership.subject == subject,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            membership = OrganizationMembership(
                organization_id=organization.id,
                identity_provider=issuer,
                subject=subject,
                display_name=display_name,
                email=email,
                roles=["administrator"],
            )
            session.add(membership)
        else:
            membership.status = "active"
            membership.roles = sorted(set(membership.roles) | {"administrator"})
        await session.commit()
        print(f"Provisioned organization={organization.id} administrator={membership.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--email")
    args = parser.parse_args()
    asyncio.run(bootstrap(**vars(args)))


if __name__ == "__main__":
    main()
