import pytest
from aiflux.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///aiflux.db",
        "mssql+pyodbc://user:password@server/database",
        "mssql+pyodbc://server/database?Encrypt=no",
        "mssql+pyodbc://server/database?TrustServerCertificate=yes",
        "mssql+pyodbc://server/database?odbc_connect=opaque",
    ],
)
def test_production_database_fails_closed(url):
    settings = Settings(
        environment="production",
        database_url=url,
        entra_audience="api://test",
        home_tenant_id="11111111-1111-4111-8111-111111111111",
    )
    assert settings.identity_errors()


def test_production_managed_identity_database_configuration():
    settings = Settings(
        environment="production",
        database_url="mssql+pyodbc://server/database?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes",
        entra_audience="api://test",
        home_tenant_id="11111111-1111-4111-8111-111111111111",
    )
    assert settings.identity_errors() == []
