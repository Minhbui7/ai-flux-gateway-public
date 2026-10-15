import struct
from collections.abc import Iterator
from functools import lru_cache

from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from fastapi import HTTPException, Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from aiflux.config import Settings


@lru_cache
def engine_for(url: str, credential: TokenCredential | None = None) -> Engine:
    if url.startswith("sqlite"):
        options: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        return create_engine(url, **options)
    engine = create_engine(url, pool_pre_ping=True)
    if url.startswith("mssql+pyodbc://"):
        sql_credential = credential if credential is not None else DefaultAzureCredential()

        @event.listens_for(engine, "do_connect")
        def provide_token(dialect: object, conn_rec: object, cargs: list, cparams: dict) -> None:
            cargs[0] = cargs[0].replace(";Trusted_Connection=Yes", "")
            token = sql_credential.get_token("https://database.windows.net/.default").token.encode("utf-16-le")
            cparams["attrs_before"] = {1256: struct.pack(f"<I{len(token)}s", len(token), token)}

    return engine


def get_db(request: Request) -> Iterator[Session]:
    settings: Settings = request.app.state.settings
    if settings.identity_errors():
        raise HTTPException(503, "Identity/database configuration is incomplete")
    with Session(engine_for(settings.database_url), expire_on_commit=False) as session:
        yield session
