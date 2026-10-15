"""Idempotent dedicated dev registrations. Uses the signed-in CLI identity, never secrets."""

import argparse
import json
import subprocess
import uuid
from pathlib import Path

PREFIX = "aiflux-fdpo-dev"
HOST = "https://aiflux-gateway-dev.eastus.cloudapp.azure.com"
TENANT = "16b3c013-d300-468d-ac64-7eda0820b6d3"
BOOTSTRAP = "958ce003-57f5-434f-b107-ca31266a7b08"
SUBSCRIPTION = None


def az(*args):
    context = ["--subscription", SUBSCRIPTION] if SUBSCRIPTION else []
    result = subprocess.run(
        ["az.cmd", *args, *context, "--only-show-errors", "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def patch(object_id, body):
    az(
        "rest",
        "--method",
        "PATCH",
        "--url",
        f"https://graph.microsoft.com/v1.0/applications/{object_id}",
        "--body",
        json.dumps(body),
    )


def registration(component, prefix=PREFIX, bootstrap=BOOTSTRAP, customer=False):
    name = f"{prefix}-{component}"
    marker = f"AIFLUX customer deployment: {prefix}"
    found = az("ad", "app", "list", "--filter", f"displayName eq '{name}'")
    if len(found) > 1:
        raise RuntimeError(f"Ambiguous exact-name registration: {name}")
    if found:
        app = found[0]
        owners = az("ad", "app", "owner", "list", "--id", app["id"])
        if not any(owner["id"] == bootstrap for owner in owners):
            raise RuntimeError(f"Existing registration is not owned by bootstrap user: {name}")
        if customer and app.get("notes") != marker:
            raise RuntimeError(f"Existing registration lacks customer deployment ownership marker: {name}")
        return app
    app = az(
        "ad",
        "app",
        "create",
        "--display-name",
        name,
        "--sign-in-audience",
        "AzureADMyOrg",
    )
    # Ownership is established before configuration so interrupted creation is recoverable.
    owners = az("ad", "app", "owner", "list", "--id", app["id"])
    if not any(owner["id"] == bootstrap for owner in owners):
        az("ad", "app", "owner", "add", "--id", app["id"], "--owner-object-id", bootstrap)
    if customer:
        patch(app["id"], {"notes": marker})
    return app


def service_principal(app):
    found = az("ad", "sp", "list", "--filter", f"appId eq '{app['appId']}'")
    if len(found) > 1:
        raise RuntimeError("Ambiguous service principal")
    return found[0] if found else az("ad", "sp", "create", "--id", app["appId"])


def portal_redirect_uris(app, component, path, host=HOST, prefix=PREFIX):
    existing = (app.get("spa") or {}).get("redirectUris", [])
    return sorted(
        set(existing)
        | {
            host + path,
            f"https://{prefix}-{component}.azurewebsites.net{path}",
        }
    )


def main():
    global SUBSCRIPTION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription")
    parser.add_argument("--tenant", default=TENANT)
    parser.add_argument("--bootstrap-object-id", default=BOOTSTRAP)
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--hostname", default=HOST.removeprefix("https://"))
    parser.add_argument("--output", type=Path, default=Path("infra/terraform/live-identity.json"))
    parser.add_argument("--customer", action="store_true")
    args = parser.parse_args()
    SUBSCRIPTION = args.subscription
    account = az("account", "show")
    if account["tenantId"] != args.tenant:
        raise RuntimeError("Wrong Entra tenant")
    if az("ad", "signed-in-user", "show")["id"] != args.bootstrap_object_id:
        raise RuntimeError("Wrong bootstrap operator")
    apps = {
        key: registration(key, args.prefix, args.bootstrap_object_id, args.customer)
        for key in ("api", "customer", "admin")
    }
    scope_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{args.prefix}/access_as_user"))
    admin_role = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{args.prefix}/ids_admin"))
    patch(
        apps["api"]["id"],
        {
            "signInAudience": "AzureADMyOrg",
            "identifierUris": [f"api://{apps['api']['appId']}"],
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [
                    {
                        "id": scope_id,
                        "value": "access_as_user",
                        "type": "User",
                        "isEnabled": True,
                        "adminConsentDisplayName": "Access AIFLUX as an approved user",
                        "adminConsentDescription": (
                            "Access AIFLUX subject to tenant and explicit member approval."
                        ),
                        "userConsentDisplayName": "Access AIFLUX",
                        "userConsentDescription": "Access AIFLUX as yourself, subject to explicit approval.",
                    }
                ],
            },
            "appRoles": [
                {
                    "id": admin_role,
                    "value": "ids_admin",
                    "displayName": "IDS administrator",
                    "description": "Home-tenant IDS administrator; database approval is still required.",
                    "allowedMemberTypes": ["User"],
                    "isEnabled": True,
                }
            ],
        },
    )
    patch(
        apps["api"]["id"],
        {
            "api": {
                "preAuthorizedApplications": [
                    {"appId": apps[key]["appId"], "delegatedPermissionIds": [scope_id]}
                    for key in ("customer", "admin")
                ],
            },
        },
    )
    for key, path in (("customer", "/redirect.html"), ("admin", "/admin/redirect.html")):
        patch(
            apps[key]["id"],
            {
                "signInAudience": "AzureADMyOrg",
                "spa": {
                    "redirectUris": portal_redirect_uris(
                        apps[key], key, path, "https://" + args.hostname, args.prefix
                    )
                },
                "requiredResourceAccess": [
                    {
                        "resourceAppId": apps["api"]["appId"],
                        "resourceAccess": [{"id": scope_id, "type": "Scope"}],
                    }
                ],
            },
        )
    principals = {key: service_principal(app) for key, app in apps.items()}
    existing = az(
        "rest",
        "--method",
        "GET",
        "--url",
        f"https://graph.microsoft.com/v1.0/servicePrincipals/{principals['api']['id']}/appRoleAssignedTo",
    )["value"]
    if not any(
        row["principalId"] == args.bootstrap_object_id and row["appRoleId"] == admin_role for row in existing
    ):
        az(
            "rest",
            "--method",
            "POST",
            "--url",
            f"https://graph.microsoft.com/v1.0/servicePrincipals/{principals['api']['id']}/appRoleAssignedTo",
            "--body",
            json.dumps(
                {
                    "principalId": args.bootstrap_object_id,
                    "resourceId": principals["api"]["id"],
                    "appRoleId": admin_role,
                }
            ),
        )
    evidence = {
        "tenant_id": args.tenant,
        "bootstrap_object_id": args.bootstrap_object_id,
        "audience": apps["api"]["appId"],
        "scope": f"api://{apps['api']['appId']}/access_as_user",
        "applications": {
            key: {
                "client_id": app["appId"],
                "object_id": app["id"],
                "service_principal_id": principals[key]["id"],
            }
            for key, app in apps.items()
        },
    }
    if args.customer:
        evidence["deployment_prefix"] = args.prefix
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
