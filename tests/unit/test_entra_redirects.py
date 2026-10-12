import runpy
from pathlib import Path

import pytest

portal_redirect_uris = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra" / "scripts" / "bootstrap-entra.py")
)["portal_redirect_uris"]


@pytest.mark.parametrize(
    ("component", "path"),
    [("customer", "/redirect.html"), ("admin", "/admin/redirect.html")],
)
def test_portal_callbacks_include_both_hosts_and_preserve_existing(component, path):
    existing = "https://approved.example/redirect.html"
    app = {"spa": {"redirectUris": [existing]}}
    expected = {
        existing,
        "https://aiflux-gateway-dev.eastus.cloudapp.azure.com" + path,
        f"https://aiflux-fdpo-dev-{component}.azurewebsites.net{path}",
    }

    result = portal_redirect_uris(app, component, path)

    assert set(result) == expected
    assert portal_redirect_uris({"spa": {"redirectUris": result}}, component, path) == result
    assert app["spa"]["redirectUris"] == [existing]


def test_new_registration_without_spa_callbacks():
    assert len(portal_redirect_uris({"spa": None}, "customer", "/redirect.html")) == 2
