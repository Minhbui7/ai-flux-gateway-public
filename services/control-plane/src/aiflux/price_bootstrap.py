"""Explicit deployment-time price import using the runtime's existing SQL grants."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from aiflux.catalog import Catalog
from aiflux.config import Settings, get_settings
from aiflux.db import engine_for
from aiflux.finops import create_price
from aiflux.models import AuditEvent, Organization
from aiflux.schemas import PriceCreate


def import_prices(db: Session, settings: Settings, path: Path, actor: UUID) -> int:
    if not settings.catalog_configured:
        raise ValueError("Price import requires an accepted catalog")
    prices: list[PriceCreate] = TypeAdapter(list[PriceCreate]).validate_python(
        json.loads(path.read_text(encoding="utf-8"))
    )
    if not prices:
        raise ValueError("Price import must contain reviewed rules")
    catalog = Catalog.load(settings.catalog_path)
    allowed = {
        (model.id, backend.provider or model.provider, backend.region)
        for model in catalog.models if model.enabled
        for backend in model.backends
    } | {
        (model.id, model.provider, model.region)
        for model in catalog.models if model.enabled and model.region
    }
    if any((price.model, price.provider, price.region) not in allowed for price in prices):
        raise ValueError("Price rule does not match an enabled catalog endpoint")
    organization = db.scalar(
        select(Organization).where(
            Organization.tenant_id == settings.home_tenant_id,
            Organization.enabled == true(),
        )
    )
    if organization is None:
        raise ValueError("Price import requires the enabled home organization")
    created = 0
    for payload in prices:
        row, inserted = create_price(db, payload, idempotent=True)
        if inserted:
            db.add(AuditEvent(
                organization_id=organization.id, object_id=str(actor),
                action="price.deployment.created", target_id=row.id,
            ))
            created += 1
    db.commit()
    logging.getLogger(__name__).warning("Reviewed price import created=%s verified=%s", created, len(prices))
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--actor-object-id", type=UUID, required=True)
    parser.add_argument("--serve", action="store_true", help="Start the API only after a successful import")
    args = parser.parse_args()
    settings = get_settings()
    with Session(engine_for(settings.database_url)) as db:
        import_prices(db, settings, args.file, args.actor_object_id)
    if args.serve:
        os.execv(sys.executable, [
            sys.executable, "-m", "uvicorn", "aiflux.app:app",
            "--host", "0.0.0.0", "--port", "8000", "--no-access-log",
        ])


if __name__ == "__main__":
    main()
