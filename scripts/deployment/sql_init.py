"""Explicit administrative initialization through an approved private SQL route."""

import argparse
import ipaddress
import json
import os
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from azure.identity import AzureCliCredential, ManagedIdentityCredential
from sqlalchemy import Connection

from .launcher import ROOT, DeploymentError, read_json, require


def credential_for(document: dict[str, Any]) -> AzureCliCredential | ManagedIdentityCredential:
    mode = document.get("credential_mode", "operator")
    if mode == "managed-identity":
        client = str(UUID(document["runner_client_id"]))
        require(
            client not in (document["API_CLIENT_ID"], document["INGESTION_CLIENT_ID"]),
            "Migration identity must be separate from runtime identities.",
        )
        return ManagedIdentityCredential(client_id=client)
    require(mode == "operator", "Unsupported SQL initialization credential mode.")
    return AzureCliCredential(
        tenant_id=document["settings"]["AIFLUX_HOME_TENANT_ID"], subscription=document["subscription_id"]
    )


def private_route(document: dict[str, Any]) -> None:
    from sqlalchemy.engine import make_url

    url = make_url(document["settings"]["AIFLUX_DATABASE_URL"])
    encrypt = url.query.get("Encrypt")
    verify = url.query.get("TrustServerCertificate")
    require(
        url.drivername == "mssql+pyodbc"
        and not url.password
        and not url.username
        and bool(url.host)
        and bool(url.database)
        and isinstance(encrypt, str)
        and encrypt.lower() == "yes"
        and isinstance(verify, str)
        and verify.lower() == "no",
        "An encrypted identity-only SQL URL with certificate verification is required.",
    )
    addresses = {item[4][0] for item in socket.getaddrinfo(url.host, 1433)}
    expected_subnet = ipaddress.ip_network(document["private_endpoint_subnet"])
    require(
        expected_subnet.is_private
        and bool(addresses)
        and all(ipaddress.ip_address(address) in expected_subnet for address in addresses),
        "SQL must resolve exclusively inside this deployment's private endpoint subnet. No public fallback.",
    )


@contextmanager
def migration_lock(connection: Connection) -> Any:
    result = connection.exec_driver_sql(
        "SET NOCOUNT ON; DECLARE @r int; "
        "EXEC @r=sys.sp_getapplock @Resource=N'aiflux-sql-init', "
        "@LockMode='Exclusive', @LockOwner='Session', @LockTimeout=0; SELECT @r;"
    ).scalar()
    require(isinstance(result, int) and result >= 0, "Another SQL initialization holds the migration lock.")
    connection.exec_driver_sql("SET NOCOUNT OFF")
    connection.commit()
    try:
        yield
    finally:
        connection.exec_driver_sql(
            "EXEC sys.sp_releaseapplock @Resource=N'aiflux-sql-init', @LockOwner='Session'"
        )
        connection.commit()


def initialize(document: dict[str, Any]) -> None:
    import pyodbc
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    settings = document["settings"]
    private_route(document)
    require("ODBC Driver 18 for SQL Server" in pyodbc.drivers(), "Install ODBC Driver 18 on this host.")
    for name, value in settings.items():
        os.environ[name] = value
    import aiflux.db as database
    from aiflux.bootstrap import configure_bootstrap
    from aiflux.config import get_settings
    from aiflux.models import Base

    credential = credential_for(document)
    get_settings.cache_clear()
    engine = database.engine_for(settings["AIFLUX_DATABASE_URL"], credential)
    try:
        with engine.connect() as connection, migration_lock(connection):
            permissions = connection.exec_driver_sql(
                "SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL')"
            ).scalar()
            require(
                permissions == 1,
                "Initializer needs approved SQL database administration; no elevation attempted.",
            )
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
            connection.commit()
            migration = Config(str(ROOT / "services" / "control-plane" / "alembic.ini"))
            with connection.begin():
                migration.attributes["connection"] = connection
                command.upgrade(migration, "head")
            sql = (ROOT / "infra" / "sql" / "bootstrap-identities.sql").read_text(encoding="utf-8")
            for name in ("API_CLIENT_ID", "INGESTION_CLIENT_ID"):
                sql = sql.replace("$(" + name + ")", str(UUID(document[name])))
            with connection.begin():
                connection.exec_driver_sql(sql)
                for user in ("aiflux-api", "aiflux-ingestion"):
                    connection.exec_driver_sql(
                        f"DENY CREATE TABLE, CREATE VIEW, CREATE PROCEDURE, CREATE FUNCTION TO [{user}]; "
                        f"DENY ALTER ON SCHEMA::dbo TO [{user}]"
                    )
            configure_bootstrap(get_settings(), engine)
            head = ScriptDirectory.from_config(migration).get_current_head()
            require(
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == head,
                "SQL migration head verification failed.",
            )
            from sqlalchemy import inspect

            require(
                set(Base.metadata.tables) <= set(inspect(connection).get_table_names(schema="dbo")),
                "Required SQL tables are missing.",
            )
            for user in ("aiflux-api", "aiflux-ingestion"):
                connection.exec_driver_sql(f"EXECUTE AS USER = '{user}'")
                try:
                    require(
                        connection.exec_driver_sql(
                            "SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL')"
                            "+HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CREATE TABLE')"
                            "+HAS_PERMS_BY_NAME('dbo','SCHEMA','ALTER')"
                        ).scalar()
                        == 0,
                        "Runtime identity unexpectedly has administrative/DDL permissions.",
                    )
                    require(
                        connection.exec_driver_sql(
                            "SELECT HAS_PERMS_BY_NAME('dbo.usage_records','OBJECT','SELECT')"
                            "*HAS_PERMS_BY_NAME('dbo.usage_records','OBJECT','INSERT')"
                            "*HAS_PERMS_BY_NAME('dbo.usage_records','OBJECT','UPDATE')"
                        ).scalar()
                        == 1,
                        "Runtime identity is missing required usage-record DML permissions.",
                    )
                finally:
                    connection.exec_driver_sql("REVERT")
            connection.commit()
            print(
                "AIFLUX_SQL_RESULT="
                + json.dumps({"revision": head, "status": "initialized", "run_id": document.get("run_id")})
            )
    finally:
        engine.dispose()
        close = getattr(credential, "close", None)
        if close:
            close()
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
