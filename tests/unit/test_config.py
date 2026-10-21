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


@pytest.mark.parametrize(
    ("endpoint", "valid"),
    [
        ("http://127.0.0.1:8081/Validate", True),
        ("http://localhost:8081/Validate", True),
        ("http://[::1]:8081/Validate", True),
        ("https://127.0.0.1:8081/Validate", True),
        ("http://10.0.0.1:8081/Validate", False),
        ("http://remote-server.com/Validate", False),
        ("http://127.0.0.1:8081/not-validate", False),
        ("ftp://127.0.0.1:8081/Validate", False),
    ],
)
def test_mise_endpoint_loopback_validation(endpoint, valid):
    settings = Settings(
        database_url="sqlite:///test.db",
        entra_audience="api://test",
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        mise_validation_endpoint=endpoint,
    )
    errors = settings.identity_errors()
    if valid:
        assert not errors
    else:
        assert any("mise_validation_endpoint" in err for err in errors)


def test_entra_client_id_validation():
    valid = Settings(
        database_url="sqlite:///test.db",
        entra_audience="api://test",
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        entra_client_id="00000000-0000-4000-8000-000000000003",
    )
    assert not valid.identity_errors()

    invalid = Settings(
        database_url="sqlite:///test.db",
        entra_audience="api://test",
        home_tenant_id="11111111-1111-4111-8111-111111111111",
        entra_client_id="not-a-uuid",
    )
    assert any("entra_client_id" in err for err in invalid.identity_errors())
