"""One-off private App Service SQL initialization; never an HTTP endpoint."""

import argparse
import ipaddress
import json
import logging
import os
import re
import socket
import sys
import time
from pathlib import Path
from uuid import UUID


class InitializationCheckError(RuntimeError):
    """A fixed, nonsecret verification failure safe for operation markers."""


def checked_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid contained-user identifier")
    return value


def principal_sql(name: str, client_id: str, legacy_object_id: str | None = None) -> str:
    name = checked_identifier(name)
    sid = UUID(client_id).bytes_le.hex()
    repair = ""
    if legacy_object_id:
        legacy_sid = UUID(legacy_object_id).bytes_le.hex()
        repair = (
            f"IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name=N'{name}' "
            f"AND sid=0x{legacy_sid} AND type='E') DROP USER [{name}]; "
        )
    return (
        repair + f"IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name=N'{name}' "
        f"AND (sid<>0x{sid} OR type<>'E')) "
        "THROW 51000, 'Contained-user identity mismatch', 1; "
        f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name=N'{name}') "
        f"CREATE USER [{name}] WITH SID=0x{sid}, TYPE=E;"
    )


def write_marker(path: Path, payload: dict) -> None:
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(payload), encoding="utf-8")
    pending.replace(path)


def run(args: argparse.Namespace) -> dict:
    import aiflux.db as database
    import pyodbc
    from aiflux.bootstrap import main as bootstrap
    from aiflux.config import get_settings
    from alembic import command
    from alembic.config import Config
    from azure.identity import ManagedIdentityCredential
    from sqlalchemy import event, text
    from sqlalchemy.engine import make_url

    logging.getLogger("azure").setLevel(logging.CRITICAL)
    settings = get_settings()
    if settings.identity_errors() or settings.environment != "production":
        raise InitializationCheckError("Production identity/database settings are required")
    if str(UUID(settings.home_tenant_id)) != args.tenant:
        raise InitializationCheckError("Unexpected home tenant")
    if str(UUID(settings.bootstrap_object_id)) != args.bootstrap_object:
        raise InitializationCheckError("Unexpected bootstrap identity")
    if os.environ.get("AZURE_CLIENT_ID") != args.client_id:
        raise InitializationCheckError("Unexpected managed identity")
    url = make_url(settings.database_url)
    if url.host != args.server or url.database != args.database:
        raise InitializationCheckError("Unexpected SQL target")
    addresses = {record[4][0] for record in socket.getaddrinfo(args.server, 1433)}
    if not addresses or not all(ipaddress.ip_address(value).is_private for value in addresses):
        raise InitializationCheckError("SQL DNS must resolve exclusively to private addresses")
    if "ODBC Driver 18 for SQL Server" not in pyodbc.drivers():
        raise InitializationCheckError("Production ODBC driver is missing")
    migration = Path("/app/services/control-plane/alembic.ini")
    if not migration.is_file():
        raise InitializationCheckError("Image migrations are missing")
    credential = ManagedIdentityCredential(client_id=args.client_id)
    credential.get_token("https://database.windows.net/.default")
    database.DefaultAzureCredential = lambda: credential
    if args.mode == "probe":
        credential.close()
        return {"status": "probe_ok", "private_dns": True, "managed_identity": True}

    engine = database.engine_for(settings.database_url)

    @event.listens_for(engine, "do_connect")
    def bound_login_timeout(dialect: object, conn_rec: object, cargs: list, cparams: dict) -> None:
        cparams["timeout"] = 15

    try:
        if args.mode == "verify-runtime":
            for attempt in range(12):
                try:
                    with engine.connect() as connection:
                        connection.exec_driver_sql("SELECT 1")
                    break
                except Exception:
                    if attempt == 11:
                        raise
                    time.sleep(10)
        if args.mode == "initialize":
            connected = False
            for attempt in range(12):
                try:
                    with engine.connect() as connection:
                        if connection.scalar(
                            text("SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL')")
                        ) != 1:
                            raise InitializationCheckError("Temporary administration has not propagated")
                    connected = True
                    break
                except Exception:
                    if attempt == 11:
                        raise
                    time.sleep(10)
            if not connected:
                raise InitializationCheckError("Temporary administration unavailable")
            command.upgrade(Config(str(migration)), "0001")
            with engine.begin() as connection:
                for name, client, principal in (
                    (args.api_user, args.client_id, args.api_object),
                    (args.ingestion_user, args.ingestion_client, args.ingestion_object),
                ):
                    connection.exec_driver_sql(principal_sql(name, client, principal))
                    roles = connection.execute(
                        text(
                            "SELECT r.name FROM sys.database_role_members m "
                            "JOIN sys.database_principals r ON r.principal_id=m.role_principal_id "
                            "JOIN sys.database_principals p ON p.principal_id=m.member_principal_id "
                            "WHERE p.name=:name"
                        ),
                        {"name": name},
                    ).scalars().all()
                    for role in roles:
                        safe_role = checked_identifier(role)
                        connection.exec_driver_sql(f"ALTER ROLE [{safe_role}] DROP MEMBER [{name}]")
                connection.exec_driver_sql(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dbo TO [{args.api_user}]"
                )
                for table in ("team_subscriptions", "model_prices"):
                    connection.exec_driver_sql(
                        f"GRANT SELECT ON OBJECT::dbo.{table} TO [{args.ingestion_user}]"
                    )
                for table in ("usage_records", "ingestion_state", "safety_events"):
                    connection.exec_driver_sql(
                        f"GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.{table} "
                        f"TO [{args.ingestion_user}]"
                    )
                # Explicit DENY survives existing grants without denying temporary dbo.
                for name in (args.api_user, args.ingestion_user):
                    connection.exec_driver_sql(
                        f"DENY CREATE TABLE, CREATE VIEW, CREATE PROCEDURE, CREATE FUNCTION "
                        f"TO [{name}]; DENY ALTER ON SCHEMA::dbo TO [{name}]"
                    )
            bootstrap()
            with engine.connect() as connection:
                for name, principal in (
                    (args.api_user, args.client_id),
                    (args.ingestion_user, args.ingestion_client),
                ):
                    count = connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM sys.database_principals "
                            "WHERE name=:name AND sid=:sid AND type='E'"
                        ),
                        {"name": name, "sid": UUID(principal).bytes_le},
                    )
                    if count != 1:
                        raise InitializationCheckError("Contained-user SID verification failed")
                    # Test API effective permissions only after ARM administrator restoration.
                    if name == args.api_user:
                        continue
                    connection.exec_driver_sql(f"EXECUTE AS USER=N'{name}'")
                    try:
                        if connection.scalar(text("SELECT IS_MEMBER('db_owner')")) != 0:
                            raise InitializationCheckError("Contained user has db_owner")
                        if connection.scalar(
                            text("SELECT HAS_PERMS_BY_NAME('dbo','SCHEMA','ALTER')")
                        ) != 0:
                            raise InitializationCheckError("Contained user has schema DDL")
                        if name == args.ingestion_user:
                            for table in ("team_subscriptions", "model_prices", "usage_records",
                                          "ingestion_state", "safety_events"):
                                for permission in (
                                    ("SELECT",) if table in ("team_subscriptions", "model_prices")
                                    else ("SELECT", "INSERT", "UPDATE")
                                ):
                                    allowed = connection.scalar(
                                        text(
                                            f"SELECT HAS_PERMS_BY_NAME('dbo.{table}',"
                                            f"'OBJECT','{permission}')"
                                        )
                                    )
                                    if allowed != 1:
                                        raise InitializationCheckError("Ingestion grant verification failed")
                            if connection.scalar(
                                text("SELECT HAS_PERMS_BY_NAME('dbo.audit_events','OBJECT','SELECT')")
                            ) != 0:
                                raise InitializationCheckError("Ingestion access exceeds approved tables")
                            if connection.scalar(
                                text("SELECT HAS_PERMS_BY_NAME('dbo.usage_records','OBJECT','DELETE')")
                            ) != 0:
                                raise InitializationCheckError("Ingestion deletion is not approved")
                    finally:
                        connection.exec_driver_sql("REVERT")
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM dbo.alembic_version"))
            if revision != "0001":
                raise InitializationCheckError("Unexpected migration revision")
            bootstrap_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM dbo.members m "
                    "JOIN dbo.organizations o ON o.id=m.organization_id "
                    "WHERE o.tenant_id=:tenant AND m.object_id=:object_id "
                    "AND o.enabled=1 AND m.enabled=1 AND m.role='ids_admin'"
                ),
                {"tenant": args.tenant, "object_id": args.bootstrap_object},
            )
            if bootstrap_count != 1:
                raise InitializationCheckError("Approved bootstrap membership was not verified")
            if args.mode == "verify-runtime":
                if connection.scalar(text("SELECT IS_MEMBER('db_owner')")) != 0:
                    raise InitializationCheckError("Runtime identity retains administrative access")
                if connection.scalar(
                    text("SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL')")
                ) != 0:
                    raise InitializationCheckError("Runtime identity retains administrative access")
                if connection.scalar(text("SELECT HAS_PERMS_BY_NAME('dbo','SCHEMA','ALTER')")) != 0:
                    raise InitializationCheckError("Runtime identity retains schema alteration access")
                for permission in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    if connection.scalar(
                        text(f"SELECT HAS_PERMS_BY_NAME('dbo','SCHEMA','{permission}')")
                    ) != 1:
                        raise InitializationCheckError("Runtime CRUD permission is missing")
            result = {"status": args.mode + "_ok", "revision": revision, "bootstrap_count": bootstrap_count}
            if args.mode == "initialize":
                result["contained_users_verified"] = 2
                result["ingestion_scoped_permissions_verified"] = True
            if args.mode == "verify-runtime":
                result["api_crud_without_admin_verified"] = True
            return result
    finally:
        engine.dispose()
        credential.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("probe", "initialize", "verify-runtime"), required=True)
    for name in (
        "server", "database", "tenant", "bootstrap-object", "client-id",
        "api-user", "api-object", "ingestion-user", "ingestion-object", "ingestion-client", "marker",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    checked_identifier(args.api_user)
    checked_identifier(args.ingestion_user)
    marker = Path(args.marker)
    try:
        # Restarts must not repeatedly run this one-off operation.
        if not marker.exists():
            write_marker(marker, run(args))
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
        if isinstance(error, InitializationCheckError):
            result["check"] = str(error)
        original = getattr(error, "orig", None)
        if original and original.args and re.fullmatch(r"[A-Z0-9]{5}", str(original.args[0])):
            result["sqlstate"] = original.args[0]
        if original and any("18456" in str(arg) for arg in original.args):
            result["sql_error"] = "18456"
        write_marker(marker, result)
    finally:
        if args.serve:
            os.execvp(
                "uvicorn",
                ["uvicorn", "aiflux.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"],
            )
    if json.loads(marker.read_text())["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
