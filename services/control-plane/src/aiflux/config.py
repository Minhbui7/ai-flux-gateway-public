from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIFLUX_", env_file=".env", extra="ignore")

    environment: Literal["development", "testing", "production"] = "development"
    database_url: str = ""
    entra_audience: str = ""
    entra_client_id: str = ""
    home_tenant_id: str = ""
    bootstrap_object_id: str = ""
    required_scope: str = "access_as_user"
    gateway_url: str = ""
    gateway_max_completion_tokens: int | None = Field(default=None, ge=1, le=100000)
    apim_resource_id: str = ""
    apim_product_id: str = "aiflux"
    gateway_settings_scopes: list[Literal["dev-openai", "dev-unified"]] = []
    log_workspace_id: str = ""
    catalog_path: Path = Path("gateway/catalog/models.json")
    catalog_configured: bool = False
    acme_challenge_enabled: bool = False
    acme_challenge_directory: Path = Path("/home/aiflux-acme-challenges")
    cors_origins: list[str] = []
    ingestion_overlap_minutes: int = 60
    ingestion_initial_days: int = 1
    ingestion_batch_minutes: int = 60
    ingestion_delay_minutes: int = 5
    ingestion_max_rows: int = 10000
    ingestion_start_at: datetime | None = None
    mise_validation_endpoint: str | None = None

    def identity_errors(self) -> list[str]:
        errors = []
        for name in ("database_url", "entra_audience", "home_tenant_id"):
            if not getattr(self, name):
                errors.append(f"{name} is required")
        if self.home_tenant_id:
            try:
                UUID(self.home_tenant_id)
            except ValueError:
                errors.append("home_tenant_id must be an Entra tenant UUID")
        if self.entra_client_id:
            try:
                UUID(self.entra_client_id)
            except ValueError:
                errors.append("entra_client_id must be an Entra application UUID")
        if self.mise_validation_endpoint:
            try:
                parsed = urlparse(self.mise_validation_endpoint)
                if parsed.scheme not in ("http", "https"):
                    errors.append("mise_validation_endpoint must use http or https")
                hostname = parsed.hostname or ""
                if hostname not in ("127.0.0.1", "localhost", "::1"):
                    errors.append("mise_validation_endpoint must be a loopback address")
                if not parsed.path.rstrip("/").endswith("/Validate"):
                    errors.append("mise_validation_endpoint must target the /Validate path")
            except Exception:
                errors.append("mise_validation_endpoint must be a valid URL")
        if self.environment == "production" and not self.database_url.startswith("mssql+pyodbc://"):
            errors.append("production requires passwordless Azure SQL")
        if self.environment == "production" and self.database_url.startswith("mssql+pyodbc://"):
            url = make_url(self.database_url)
            if url.username or url.password:
                errors.append("production SQL credentials must use managed identity")
            if "odbc_connect" in url.query:
                errors.append(
                    "production SQL must use explicit URL parameters, not an opaque connection string"
                )
            if str(url.query.get("Encrypt", "yes")).lower() not in ("yes", "true", "mandatory", "strict"):
                errors.append("production SQL must encrypt connections")
            if str(url.query.get("TrustServerCertificate", "no")).lower() not in ("no", "false"):
                errors.append("production SQL must validate the server certificate")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
