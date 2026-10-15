"""Explicit operator-only initialization from an already approved private SQL route."""

import argparse
import ipaddress
import os
import socket
import sys
from pathlib import Path
from uuid import UUID

from .launcher import ROOT, DeploymentError, read_json, require


def initialize(document: dict) -> None:
    import pyodbc
    from alembic import command
    from alembic.config import Config
    from azure.identity import AzureCliCredential
    from sqlalchemy.engine import make_url

    settings = document["settings"]
    url = make_url(settings["AIFLUX_DATABASE_URL"])
    require(url.drivername == "mssql+pyodbc" and not url.password, "An identity-only SQL URL is required.")
    addresses = {item[4][0] for item in socket.getaddrinfo(url.host, 1433)}
    expected_subnet = ipaddress.ip_network(document["private_endpoint_subnet"])
    require(
        bool(addresses) and all(ipaddress.ip_address(address) in expected_subnet for address in addresses),
        "SQL must resolve exclusively inside this deployment's private endpoint subnet. No public fallback.",
    )
    require("ODBC Driver 18 for SQL Server" in pyodbc.drivers(), "Install ODBC Driver 18 on this host.")
    for name, value in settings.items():
        os.environ[name] = value
    # This process uses only the interactive operator, never the runtime managed identity.
    import aiflux.db as database
    from aiflux.bootstrap import configure_bootstrap
    from aiflux.config import get_settings

    credential = AzureCliCredential(
        tenant_id=settings["AIFLUX_HOME_TENANT_ID"], subscription=document["subscription_id"]
    )
    get_settings.cache_clear()
    engine = database.engine_for(settings["AIFLUX_DATABASE_URL"], credential)
    try:
        with engine.connect() as connection:
            permissions = connection.exec_driver_sql(
                "SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL')"
            ).scalar()
            require(
                permissions == 1,
                "Operator needs approved SQL database administration; no elevation attempted.",
            )
        migration = Config(str(ROOT / "services" / "control-plane" / "alembic.ini"))
        with engine.begin() as connection:
            migration.attributes["connection"] = connection
            command.upgrade(migration, "head")
        sql = (ROOT / "infra" / "sql" / "bootstrap-identities.sql").read_text(encoding="utf-8")
        for name in ("API_CLIENT_ID", "INGESTION_CLIENT_ID"):
            sql = sql.replace("$(" + name + ")", str(UUID(document[name])))
        with engine.begin() as connection:
            roles = connection.exec_driver_sql(
                "SELECT r.name FROM sys.database_role_members m "
                "JOIN sys.database_principals r ON r.principal_id=m.role_principal_id "
                "JOIN sys.database_principals p ON p.principal_id=m.member_principal_id "
                "WHERE p.name IN ('aiflux-api','aiflux-ingestion')"
            ).all()
            require(
                not roles,
                "Runtime users have existing database roles; review privileges before initialization.",
            )
            connection.exec_driver_sql(sql)
            for user in ("aiflux-api", "aiflux-ingestion"):
                connection.exec_driver_sql(
                    f"DENY CREATE TABLE, CREATE VIEW, CREATE PROCEDURE, CREATE FUNCTION TO [{user}]; "
                    f"DENY ALTER ON SCHEMA::dbo TO [{user}]"
                )
        configure_bootstrap(get_settings(), engine)
    finally:
        engine.dispose()
        credential.close()
    print(
        "Migration head, scoped contained users and bootstrap configured. Verify runtime /ready separately."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    args = parser.parse_args()
    try:
        initialize(read_json(args.inputs))
    except DeploymentError as error:
        print(f"SQL initialization stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
