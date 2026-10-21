import re
import time
from typing import Literal
from urllib.parse import urlsplit
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
        response = self._send(method, url, body, "*")
        if response.status_code == 204:
            return {}
        return self._json(response)

    def _send(
        self, method: str, url: str, body: dict | None = None, etag: str | None = None,
    ) -> httpx.Response:
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
                headers={"Authorization": f"Bearer {token}"} | ({"If-Match": etag} if etag else {}),
            )
        except httpx.HTTPError as exc:
            raise ApimError() from exc
        if response.status_code not in (200, 201, 202, 204):
            raise ApimError(response.status_code)
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            result = response.json()
        except ValueError as exc:
            raise ApimError(response.status_code) from exc
        if not isinstance(result, dict):
            raise ApimError(response.status_code)
        return result

    def _fragment_url(self, scope: str) -> str:
        if scope not in self.settings.gateway_settings_scopes:
            raise ApimError()
        # Reuse resource-ID validation, never accept an ARM URL from an API caller.
        self._url("00000000-0000-0000-0000-000000000000")
        return (
            f"https://management.azure.com{self.settings.apim_resource_id.rstrip('/')}"
            f"/policyFragments/aiflux-{scope}-settings?api-version={API_VERSION}"
        )

    def get_settings_fragment(self, scope: str) -> tuple[str, str]:
        response = self._send("GET", self._fragment_url(scope) + "&format=rawxml")
        properties = self._json(response).get("properties")
        value = properties.get("value") if isinstance(properties, dict) else None
        etag = response.headers.get("ETag")
        if not isinstance(value, str) or not value or len(value) > 65536 or not etag or len(etag) > 200:
            raise ApimError(response.status_code)
        return value, etag

    def put_settings_fragment(self, scope: str, value: str, etag: str) -> None:
        if not etag or etag == "*" or len(value.encode("utf-8")) > 65536:
            raise ApimError()
        response = self._send(
            "PUT", self._fragment_url(scope),
            {"properties": {
                "description": (
                    "Runtime-owned bounded settings; invariant inspection and routing remain Terraform-owned."
                ),
                "format": "rawxml", "value": value,
            }}, etag,
        )
        operation = response.headers.get("Azure-AsyncOperation")
        if operation is None:
            if response.status_code == 202:
                raise ApimError(202)
            return
        expected, actual = urlsplit(self._fragment_url(scope)), urlsplit(operation)
        if (actual.scheme, actual.netloc, actual.path) != (
            expected.scheme, expected.netloc, expected.path,
        ):
            raise ApimError()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = self._json(self._send("GET", operation))
            state = result.get("status")
            if state == "Succeeded":
                return
            if state not in ("InProgress", "Running", "Accepted"):
                raise ApimError(409)
            time.sleep(2)
        raise ApimError(504)

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
