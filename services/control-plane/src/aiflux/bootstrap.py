from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from aiflux.config import Settings, get_settings
from aiflux.db import engine_for
from aiflux.models import Member, Organization


def configure_bootstrap(settings: Settings, engine: Engine) -> None:
    if settings.identity_errors() or not settings.bootstrap_object_id:
        raise SystemExit("Set database, audience, home tenant and bootstrap object ID before bootstrap")
    tenant = str(UUID(settings.home_tenant_id))
    object_id = str(UUID(settings.bootstrap_object_id))
    with Session(engine) as db:
        org = db.scalar(select(Organization).where(Organization.tenant_id == tenant))
        if org is None:
            org = Organization(name=settings.home_organization_name, tenant_id=tenant, enabled=True)
            db.add(org)
            db.flush()
        if not org.enabled:
            raise SystemExit("Home organization is disabled; bootstrap will not override it")
        member = db.scalar(
            select(Member).where(Member.organization_id == org.id, Member.object_id == object_id)
        )
        if member is None:
            db.add(Member(organization_id=org.id, object_id=object_id, role="ids_admin", enabled=True))
        elif member.role != "ids_admin" or not member.enabled:
            raise SystemExit("Membership exists with different permissions; bootstrap will not override it")
        db.commit()
    print("IDS bootstrap membership is configured")


def main() -> None:
    settings = get_settings()
    if settings.identity_errors() or not settings.bootstrap_object_id:
        raise SystemExit("Set database, audience, home tenant and bootstrap object ID before bootstrap")
    configure_bootstrap(settings, engine_for(settings.database_url))


if __name__ == "__main__":
    main()
