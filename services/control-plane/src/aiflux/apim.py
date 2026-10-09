import re
from typing import Literal
from uuid import UUID

import httpx
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential

from aiflux.config import Settings

API_VERSION = "2024-05-01"


class ApimError(RuntimeError):
    def __init__(self, status_code: int | None = None):
        super().__init__("APIM management operation failed")
        self.status_code = status_code


class ApimClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._credential: DefaultAzureCredential | None = None

    def _url(self, subscription_id: str, action: str = "") -> str:
        resource = self.settings.apim_resource_id.rstrip("/")
        if not re.fullmatch(
            r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[\w.-]+/"
            r"providers/Microsoft\.ApiManagement/service/[\w-]+",
            resource,
        ) or not re.fullmatch(r"[\w-]+", self.settings.apim_product_id):
            raise ApimError()
        return (
            f"https://management.azure.com{resource}/subscriptions/{UUID(subscription_id)}"
            f"{action}?api-version={API_VERSION}"
        )

    def _request(self, method: str, sid: str, action: str = "", body: dict | None = None) -> dict:
        url = self._url(sid, action)
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        try:
            token = self._credential.get_token("https://management.azure.com/.default").token
        except AzureError as exc:
            raise ApimError() from exc
        try:
            response = httpx.request(
                method,
                url,
                json=body,
                timeout=30,
                headers={"Authorization": f"Bearer {token}", "If-Match": "*"},
            )
        except httpx.HTTPError as exc:
            raise ApimError() from exc
        if response.status_code not in (200, 201, 204):
            raise ApimError(response.status_code)
        if response.status_code == 204:
            return {}
        try:
            result = response.json()
        except ValueError as exc:
            raise ApimError(response.status_code) from exc
        if not isinstance(result, dict):
            raise ApimError(response.status_code)
        return result

    def ensure(self, sid: str, display_name: str, state: str) -> None:
        self._request(
            "PUT",
            sid,
            body={
                "properties": {
                    "displayName": display_name,
                    "scope": f"{self.settings.apim_resource_id}/products/{self.settings.apim_product_id}",
                    "state": state,
                    "allowTracing": False,
                }
            },
        )

    def set_state(self, sid: str, state: str) -> None:
        self._request("PATCH", sid, body={"properties": {"state": state}})

    def reveal(self, sid: str, key: Literal["primary", "secondary"]) -> str:
        result = self._request("POST", sid, "/listSecrets")
        value = result.get(f"{key}Key")
        if not isinstance(value, str) or not value:
            raise ApimError()
        return value

    def rotate(self, sid: str, key: Literal["primary", "secondary"]) -> None:
        action = "/regeneratePrimaryKey" if key == "primary" else "/regenerateSecondaryKey"
        self._request("POST", sid, action)
