from aiflux.app import create_app
from aiflux.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.dialects import mssql


def test_signed_in_approval_queries_compile_for_sql_server(env):
    queries = []

    def capture(connection, clause, multiparams, params, execution_options):
        queries.append(str(clause.compile(dialect=mssql.dialect(),
                                          compile_kwargs={"literal_binds": True})))

    event.listen(env.db_engine, "before_execute", capture)
    try:
        assert env.client.get("/api/me", headers=env.customer).status_code == 200
    finally:
        event.remove(env.db_engine, "before_execute", capture)
    assert any("organizations.enabled = 1" in query for query in queries)
    assert any("members.enabled = 1" in query for query in queries)
    assert all(" IS 1" not in query and " IS 0" not in query for query in queries)


def test_readiness_requires_application_tables_not_only_connectivity(env):
    Base.metadata.drop_all(env.db_engine)
    with TestClient(create_app(env.settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
