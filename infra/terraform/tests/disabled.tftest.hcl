mock_provider "azurerm" {
  override_during = plan
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev"
      location = "eastus"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "4d75ed7f-75ab-4db6-b1f3-263f240d1450"
      tenant_id       = "00000000-0000-0000-0000-000000000001"
    }
  }
  mock_data "azurerm_network_security_group" {
    defaults = {
      id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.Network/networkSecurityGroups/policy-attached-nsg"
    }
  }
  mock_resource "azurerm_api_management" {
    defaults = {
      id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.ApiManagement/service/aiflux-test-apim"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test"
      client_id    = "00000000-0000-0000-0000-000000000002"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }
  mock_resource "azurerm_application_insights" {
    defaults = {
      id                = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.Insights/components/test"
      connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000004"
    }
  }
  mock_resource "azurerm_public_ip" {
    defaults = {
      id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.Network/publicIPAddresses/test"
    }
  }
  mock_resource "azurerm_linux_web_app" {
    defaults = {
      possible_outbound_ip_address_list = ["203.0.113.20", "203.0.113.21"]
    }
  }
  mock_resource "azurerm_linux_function_app" {
    defaults = {
      possible_outbound_ip_address_list = ["203.0.113.22"]
    }
  }
  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.Network/virtualNetworks/test/subnets/appgw"
    }
  }
}

mock_provider "azapi" {}

variables {
  subscription_id                 = "4d75ed7f-75ab-4db6-b1f3-263f240d1450"
  resource_group_name             = "rg-aiflux-fdpo-dev"
  location                        = "eastus"
  name_prefix                     = "aiflux-test"
  deployment_approved             = true
  deployment_stage                = "public-edge"
  public_edge_live_gates_approved = true
  publisher_email                 = "test@example.invalid"
  gateway_origin_hostname         = "aiflux-gateway-dev.eastus.cloudapp.azure.com"
  apim_capacity                   = 1
  app_service_sku                 = "P1v3"
  sql_sku                         = "S0"
  operator_ip                     = "203.0.113.10"
  sql_firewall_ipv4s = {
    web-1    = "203.0.113.20"
    web-2    = "203.0.113.21"
    function = "203.0.113.22"
  }
  log_retention_days   = 30
  registry_resource_id = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.ContainerRegistry/registries/test"
  entra = {
    audience            = "api://test"
    client_id           = "00000000-0000-0000-0000-000000000005"
    home_tenant_id      = "00000000-0000-0000-0000-000000000001"
    bootstrap_object_id = "00000000-0000-0000-0000-000000000006"
  }
  sql_admin = {
    login     = "test-admin"
    object_id = "00000000-0000-0000-0000-000000000007"
    tenant_id = "00000000-0000-0000-0000-000000000001"
  }
  network = {
    address_space      = "10.50.0.0/16"
    app_gateway_subnet = "10.50.0.0/24"
  }
  edge = {
    origin_hostname             = "aiflux-gateway-dev.eastus.cloudapp.azure.com"
    dns_label                   = "aiflux-gateway-dev"
    certificate_secret_id       = "https://test.vault.azure.net/secrets/appgw/"
    certificate_vault_id        = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.KeyVault/vaults/test"
    app_gateway_timeout_seconds = 120
    waf_body_limit_kb           = 128
    waf_inspection_limit_kb     = 128
    zones                       = ["1", "2", "3"]
  }
  apps = {
    api      = { image = "test/api@sha256:0000000000000000000000000000000000000000000000000000000000000000", registry_url = "https://test.azurecr.io", port = 8000, health_path = "/health" }
    customer = { image = "test/customer@sha256:0000000000000000000000000000000000000000000000000000000000000000", registry_url = "https://test.azurecr.io", port = 8080, health_path = "/" }
    admin    = { image = "test/admin@sha256:0000000000000000000000000000000000000000000000000000000000000000", registry_url = "https://test.azurecr.io", port = 8080, health_path = "/admin/" }
  }
}

run "edge_bootstrap_needs_no_certificate_or_live_attestation" {
  command = plan
  variables {
    deployment_stage                = "edge-bootstrap"
    public_edge_live_gates_approved = false
    edge = {
      origin_hostname             = "aiflux-gateway-dev.eastus.cloudapp.azure.com"
      dns_label                   = "aiflux-gateway-dev"
      app_gateway_timeout_seconds = 120
      waf_body_limit_kb           = 128
      waf_inspection_limit_kb     = 128
      zones                       = ["1", "2", "3"]
    }
  }
  assert {
    condition     = length(azurerm_application_gateway.main["public"].ssl_certificate) == 0 && alltrue([for listener in azurerm_application_gateway.main["public"].http_listener : listener.protocol == "Http"])
    error_message = "Bootstrap must not require or invent a TLS certificate."
  }
  assert {
    condition     = alltrue([for path in azurerm_application_gateway.main["public"].url_path_map : path.default_backend_address_pool_name == "deny"]) && toset(keys(local.appgw_backends)) == toset(["api", "deny"]) && length(azurerm_role_assignment.edge_certificate) == 0
    error_message = "Bootstrap permits only HTTP-01, has no portal/APIM backend, and grants no certificate read role."
  }
  assert {
    condition     = azurerm_web_application_firewall_policy.appgw["public"].policy_settings[0].log_scrubbing[0].enabled && length(azurerm_web_application_firewall_policy.appgw["public"].custom_rules) == 2 && !var.public_edge_live_gates_approved
    error_message = "Bootstrap must scrub logs and block non-challenge/inference requests without falsely attesting live acceptance."
  }
}

run "edge_candidate_is_operator_restricted_without_live_attestation" {
  command = plan
  variables {
    deployment_stage                = "edge-candidate"
    public_edge_live_gates_approved = false
  }
  assert {
    condition     = length(azurerm_application_gateway.main["public"].ssl_certificate) == 1 && length(azurerm_web_application_firewall_policy.appgw["public"].custom_rules) == 2 && output.gateway_url == null
    error_message = "Candidate TLS can be tested before release, but its WAF operator gate must remain and gateway URL must not be released."
  }
  assert {
    condition = azurerm_role_assignment.edge_certificate["edge"].scope == (
      var.edge.certificate_vault_id
      ) && azurerm_role_assignment.edge_certificate["edge"].role_definition_name == "Key Vault Secrets User" && (
      azurerm_role_assignment.edge_certificate["edge"].principal_id ==
      azurerm_user_assigned_identity.identity["edge"].principal_id
    )
    error_message = "Application Gateway needs read-only secret access scoped to its Key Vault; the API writer remains limited to the exact TLS secret."
  }
}

run "preserve_governance_attached_nsg" {
  command = plan
  variables {
    deployment_stage                = "edge-bootstrap"
    public_edge_live_gates_approved = false
    app_gateway_existing_nsg_name   = "policy-attached-nsg"
  }
  assert {
    condition     = azurerm_subnet_network_security_group_association.appgw["public"].network_security_group_id == data.azurerm_network_security_group.appgw_platform[0].id && length(azurerm_network_security_rule.appgw_platform) == 4
    error_message = "Keep the governance NSG association and add only four individually managed named ingress rules."
  }
}

run "reject_timeout_above_appgw_v2_limit" {
  command = plan
  variables {
    edge = {
      origin_hostname             = "aiflux-gateway-dev.eastus.cloudapp.azure.com"
      dns_label                   = "aiflux-gateway-dev"
      certificate_secret_id       = "https://test.vault.azure.net/secrets/appgw"
      certificate_vault_id        = "/subscriptions/4d75ed7f-75ab-4db6-b1f3-263f240d1450/resourceGroups/rg-aiflux-fdpo-dev/providers/Microsoft.KeyVault/vaults/test"
      app_gateway_timeout_seconds = 241
      waf_body_limit_kb           = 128
      waf_inspection_limit_kb     = 128
      zones                       = ["1", "2", "3"]
    }
  }
  expect_failures = [var.edge]
}

run "apim_first_stage" {
  command = plan
  variables {
    deployment_stage = "apim"
    entra            = null
    sql_admin        = null
    edge             = null
    operator_ip      = null
    apps             = {}
  }
  assert {
    condition     = azurerm_api_management.main.sku_name == "BasicV2_1" && azurerm_api_management.main.virtual_network_type == "None" && length(azurerm_api_management.main.virtual_network_configuration) == 0 && azurerm_api_management.main.public_network_access_enabled
    error_message = "Basic v2 must be public with no VNet integration or injection."
  }
  assert {
    condition     = length(azurerm_subnet.main) == 0 && length(azurerm_virtual_network.main) == 0
    error_message = "APIM/protection must not require operator bootstrap, VM, NAT, or networking."
  }
  assert {
    condition     = azapi_resource.ai["language"].body.kind == "AIServices" && azapi_resource.ai["language"].name == "${var.name_prefix}-foundry" && azurerm_role_assignment.ai_user["language"].role_definition_name == "Cognitive Services User"
    error_message = "Language PII must use the Foundry umbrella resource with a resource-scoped gateway identity role."
  }
  assert {
    condition     = length(azurerm_linux_web_app.main) == 0 && length(azurerm_mssql_server.main) == 0 && length(azurerm_linux_function_app.ingestion) == 0 && length(azurerm_application_gateway.main) == 0
    error_message = "The APIM-first stage must not create apps, SQL, ingestion, or public edge resources."
  }
  assert {
    condition     = output.gateway_url == null && !output.inference_enabled && azurerm_key_vault.main.public_network_access_enabled && alltrue([for ai in azapi_resource.ai : ai.body.properties.publicNetworkAccess == "Enabled" && ai.body.properties.disableLocalAuth])
    error_message = "Protection dependencies must use public authenticated endpoints without releasing inference."
  }
}

run "public_platform_stage" {
  command = plan
  variables {
    deployment_stage   = "platform"
    edge               = null
    sql_firewall_ipv4s = {}
  }
  assert {
    condition     = length(azurerm_linux_web_app.main) == 3 && length(azurerm_mssql_server.main) == 1 && length(azurerm_mssql_database.main) == 1
    error_message = "The platform stage must add the authenticated public app and SQL resources."
  }
  assert {
    condition     = length(azurerm_application_gateway.main) == 0 && !contains(keys(azurerm_user_assigned_identity.identity), "edge") && output.gateway_url == null
    error_message = "The platform stage must not provision the public edge or its identity."
  }
  assert {
    condition     = toset(keys(azurerm_subnet.main)) == toset(["appgw"]) && azurerm_subnet.main["appgw"].service_endpoint[0].service == "Microsoft.Web" && length(azurerm_subnet.main["appgw"].delegation) == 0
    error_message = "Only the AppGW subnet with Microsoft.Web service endpoint is needed; no app/APIM integration."
  }
  assert {
    condition     = length(azurerm_mssql_firewall_rule.apps) == 0 && azurerm_mssql_firewall_rule.operator[0].start_ip_address == var.operator_ip
    error_message = "Initial platform creation must allow the operator only until actual app outbound IPs are reviewed."
  }
}

run "deferred_language_registry_prerequisites" {
  command = plan
  variables {
    deployment_stage                        = "apim"
    protection_language_enabled             = false
    key_vault_public_network_access_enabled = false
    create_container_registry               = true
  }
  assert {
    condition     = toset(keys(azapi_resource.ai)) == toset(["safety"]) && output.deferred_protection_dependencies == tolist(["language-pii"]) && !output.inference_enabled
    error_message = "Explicit Language deferral must retain Content Safety and report missing PII without enabling inference."
  }
  assert {
    condition     = !azurerm_key_vault.main.public_network_access_enabled && azurerm_container_registry.main[0].sku == "Basic" && !azurerm_container_registry.main[0].admin_enabled && !azurerm_container_registry.main[0].anonymous_pull_enabled
    error_message = "Respect governance-disabled vault access and create authenticated Basic ACR only."
  }
}

run "independent_platform_prerequisites" {
  command = plan
  variables {
    deployment_stage                        = "prerequisites"
    entra                                   = null
    apps                                    = {}
    protection_language_enabled             = false
    key_vault_public_network_access_enabled = false
    create_container_registry               = true
    edge                                    = null
  }
  assert {
    condition     = length(azurerm_service_plan.apps) == 1 && length(azurerm_mssql_server.main) == 1 && length(azurerm_mssql_database.main) == 1 && length(azapi_resource.function_storage) == 1 && length(azurerm_user_assigned_identity.identity) == 5
    error_message = "Independent prerequisites must create approved plan/SQL/storage/identities without requiring blocked app registrations or fake images."
  }
  assert {
    condition     = length(azurerm_linux_web_app.main) == 0 && length(azurerm_linux_function_app.ingestion) == 0 && length(azurerm_application_gateway.main) == 0 && output.gateway_url == null && output.control_plane_settings == null && !output.inference_enabled
    error_message = "Blocked identity/artifact prerequisites must not create falsely configured runtime apps or release routes."
  }
  assert {
    condition     = length(azurerm_role_assignment.acr_pull) == 3 && length(azurerm_role_assignment.function_storage) == 3 && length(azurerm_role_assignment.monitor_reader) == 2 && length(azurerm_role_assignment.subscription_manager) == 1
    error_message = "Prerequisites must prepare resource-scoped managed identity roles without directory-wide permission or an enabled runtime."
  }
  assert {
    condition     = azurerm_mssql_server.main[0].location == coalesce(var.sql_location, var.location)
    error_message = "SQL defaults to the gateway location unless an explicit SQL location is configured."
  }
}

run "sql_can_use_a_separate_approved_region" {
  command = plan
  variables {
    deployment_stage = "prerequisites"
    sql_location     = "australiaeast"
    entra            = null
    apps             = {}
    edge             = null
  }
  assert {
    condition     = azurerm_mssql_server.main[0].location == "australiaeast" && length(azurerm_mssql_database.main) == 1
    error_message = "The SQL server/database must use the explicit Australia East region without relocating the apps."
  }
}

run "platform_apps_with_governance_disabled_sql_network" {
  command = plan
  variables {
    deployment_stage                  = "platform"
    sql_public_network_access_enabled = false
    sql_firewall_ipv4s                = {}
    edge                              = null
  }
  assert {
    condition     = length(azurerm_linux_web_app.main) == 3 && !azurerm_mssql_server.main[0].public_network_access_enabled && length(azurerm_mssql_firewall_rule.operator) == 0 && length(azurerm_mssql_firewall_rule.apps) == 0 && output.deferred_platform_dependencies == tolist(["sql-public-endpoint"])
    error_message = "Apps may be provisioned for diagnostics while preserving a governance-disabled SQL network without attempting firewall mutations."
  }
}

run "deferred_sql_public_endpoint" {
  command = plan
  variables {
    deployment_stage                  = "prerequisites"
    sql_public_network_access_enabled = false
    entra                             = null
    apps                              = {}
    edge                              = null
  }
  assert {
    condition     = !azurerm_mssql_server.main[0].public_network_access_enabled && length(azurerm_mssql_firewall_rule.operator) == 0 && output.deferred_platform_dependencies == tolist(["sql-public-endpoint"])
    error_message = "A governance-disabled SQL endpoint must remain disabled without repeated firewall mutations and must be exposed as a platform blocker."
  }
}

run "reject_deferred_language_public_edge" {
  command = plan
  variables {
    protection_language_enabled = false
  }
  expect_failures = [terraform_data.approval]
}

run "deferred_sql_prerequisites" {
  command = plan
  variables {
    deployment_stage                               = "prerequisites"
    sql_enabled                                    = false
    entra                                          = null
    apps                                           = {}
    edge                                           = null
    function_storage_public_network_access_enabled = false
  }
  assert {
    condition     = length(azurerm_mssql_server.main) == 0 && length(azurerm_mssql_database.main) == 0 && length(azurerm_mssql_firewall_rule.operator) == 0 && output.deferred_platform_dependencies == tolist(["azure-sql"]) && length(azurerm_service_plan.apps) == 1
    error_message = "SQL entitlement deferral must explicitly report missing SQL, preserve independent hosting prerequisites, and avoid repeatedly creating the rejected server."
  }
  assert {
    condition     = azapi_resource.function_storage[0].body.properties.publicNetworkAccess == "Disabled" && !azapi_resource.function_storage[0].body.properties.allowSharedKeyAccess && !azapi_resource.function_storage[0].body.properties.allowBlobPublicAccess
    error_message = "Storage deferral must respect governance while retaining keyless/nonanonymous posture."
  }
}

run "reject_deferred_sql_runtime" {
  command = plan
  variables {
    sql_enabled = false
  }
  expect_failures = [var.sql_enabled]
}

run "disabled_posture" {
  command = plan
  assert {
    condition     = !azurerm_api_management_product.main.published && azurerm_api_management_api.blocked.subscription_required
    error_message = "The product must remain unpublished and native subscriptions required."
  }
  assert {
    condition     = !azurerm_linux_function_app.ingestion[0].enabled && azurerm_api_management_api_policy.closed.xml_content == file("${path.module}/../../gateway/policies/disabled.xml")
    error_message = "The inference/Function release gates must remain disabled."
  }
  assert {
    condition     = !output.inference_enabled && local.control_settings.AIFLUX_CATALOG_CONFIGURED == "false"
    error_message = "No success-shaped inference/catalog defaults."
  }
  assert {
    condition     = alltrue([for app in azurerm_linux_web_app.main : app.public_network_access_enabled && app.https_only && app.virtual_network_subnet_id == null && app.site_config[0].ip_restriction_default_action == "Deny" && app.site_config[0].scm_use_main_ip_restriction]) && azurerm_mssql_server.main[0].public_network_access_enabled
    error_message = "Public TLS apps require deny-default origin/SCM restrictions without VNet integration; SQL must be public."
  }
  assert {
    condition     = alltrue([for app in azurerm_linux_web_app.main : anytrue([for rule in app.site_config[0].ip_restriction : rule.virtual_network_subnet_id == azurerm_subnet.main["appgw"].id && rule.action == "Allow"]) && anytrue([for rule in app.site_config[0].ip_restriction : rule.ip_address == "${var.operator_ip}/32" && rule.action == "Allow"])])
    error_message = "Each web origin must allow only the AppGW service endpoint and explicit operator /32."
  }
  assert {
    condition     = azurerm_mssql_server.main[0].azuread_administrator[0].azuread_authentication_only && azurerm_mssql_server.main[0].minimum_tls_version == "1.2" && azurerm_mssql_firewall_rule.operator[0].start_ip_address == var.operator_ip && azurerm_mssql_firewall_rule.operator[0].end_ip_address == var.operator_ip && alltrue([for rule in azurerm_mssql_firewall_rule.apps : rule.start_ip_address != "0.0.0.0" && rule.start_ip_address == rule.end_ip_address])
    error_message = "SQL must be Entra-only/TLS with exact operator and app outbound rules, never AllowAzureServices."
  }
  assert {
    condition     = azapi_resource.function_storage[0].body.properties.publicNetworkAccess == "Enabled" && !azapi_resource.function_storage[0].body.properties.allowSharedKeyAccess && !azapi_resource.function_storage[0].body.properties.allowBlobPublicAccess && azapi_resource.function_storage[0].body.properties.supportsHttpsTrafficOnly && azurerm_key_vault.main.rbac_authorization_enabled && azurerm_key_vault.main.network_acls[0].default_action == "Allow"
    error_message = "Public data endpoints must retain TLS, no anonymous blob/shared keys, and vault RBAC."
  }
  assert {
    condition     = azurerm_public_ip.appgw["public"].sku == "Standard" && azurerm_application_gateway.main["public"].frontend_ip_configuration[0].name == "public" && anytrue([for listener in azurerm_application_gateway.main["public"].http_listener : listener.protocol == "Https"])
    error_message = "The released edge must use a public Standard IP and HTTPS listener."
  }
  assert {
    condition     = azurerm_application_gateway.main["public"].global[0].request_buffering_enabled && !azurerm_application_gateway.main["public"].global[0].response_buffering_enabled
    error_message = "Keep WAF request buffering enabled and response buffering disabled for SSE."
  }
  assert {
    condition     = anytrue([for listener in azurerm_application_gateway.main["public"].http_listener : listener.host_name == var.edge.origin_hostname]) && azurerm_public_ip.appgw["public"].domain_name_label == var.edge.dns_label
    error_message = "The HTTPS listener, certificate hostname, and candidate public DNS label must agree."
  }
  assert {
    condition     = !contains(keys(azapi_resource.monitor_diagnostic.body.properties), "largeLanguageModel")
    error_message = "LLM request/response logging must be omitted."
  }
}

run "hybrid_private_data_platform" {
  command = plan
  variables {
    deployment_stage                               = "platform"
    hybrid_private_data_enabled                    = true
    sql_public_network_access_enabled              = false
    key_vault_public_network_access_enabled        = false
    function_storage_public_network_access_enabled = false
    sql_firewall_ipv4s                             = {}
    network = {
      address_space                  = "10.240.0.0/16"
      app_gateway_subnet             = "10.240.1.0/24"
      private_endpoint_subnet        = "10.240.3.0/24"
      app_service_integration_subnet = "10.240.4.0/24"
    }
  }
  assert {
    condition     = toset(keys(azurerm_private_endpoint.data)) == toset(["sql", "vault", "blob", "queue", "table"]) && length(azurerm_private_dns_zone.data) == 5 && length(azurerm_private_dns_zone_virtual_network_link.data) == 5
    error_message = "Hybrid creates only five private endpoints and matching DNS zones/links for the three approved data services; no APIM/Foundry/File PE."
  }
  assert {
    condition     = azurerm_private_dns_zone.data["sql"].name == "privatelink.database.windows.net" && azurerm_private_dns_zone.data["vault"].name == "privatelink.vaultcore.azure.net" && alltrue([for service in ["blob", "queue", "table"] : azurerm_private_dns_zone.data[service].name == "privatelink.${service}.core.windows.net"]) && alltrue([for link in azurerm_private_dns_zone_virtual_network_link.data : !link.registration_enabled])
    error_message = "Correct service DNS zones must be linked without autoregistration."
  }
  assert {
    condition     = !azurerm_mssql_server.main[0].public_network_access_enabled && azurerm_mssql_server.main[0].connection_policy == "Proxy" && !azurerm_key_vault.main.public_network_access_enabled && azapi_resource.function_storage[0].body.properties.publicNetworkAccess == "Disabled" && length(azurerm_mssql_firewall_rule.apps) == 0 && length(azurerm_mssql_firewall_rule.operator) == 0 && length(output.sql_required_outbound_ipv4s) == 0
    error_message = "Preserve disabled public data access and SQL Proxy on 1433 without public firewall/IP dependencies."
  }
  assert {
    condition     = azurerm_linux_web_app.main["api"].virtual_network_subnet_id == azurerm_subnet.app_service_integration[0].id && azurerm_linux_function_app.ingestion[0].virtual_network_subnet_id == azurerm_subnet.app_service_integration[0].id && azurerm_linux_web_app.main["customer"].virtual_network_subnet_id == null && azurerm_linux_web_app.main["admin"].virtual_network_subnet_id == null && azurerm_subnet.app_service_integration[0].delegation[0].service_delegation[0].name == "Microsoft.Web/serverFarms"
    error_message = "Only API and ingestion need outbound integration on the delegated subnet."
  }
  assert {
    condition     = azurerm_linux_function_app.ingestion[0].content_share_force_disabled && azurerm_linux_function_app.ingestion[0].storage_uses_managed_identity && !azurerm_linux_function_app.ingestion[0].enabled && azurerm_api_management.main.public_network_access_enabled && azurerm_api_management.main.virtual_network_type == "None" && azapi_resource.ai["language"].body.properties.publicNetworkAccess == "Enabled" && length(azurerm_application_gateway.main) == 0 && !output.inference_enabled && output.deferred_platform_dependencies == tolist(["private-sql-runtime-acceptance"])
    error_message = "Dedicated keyless Function needs no Files share; public APIM/Foundry posture and disabled release gates must remain."
  }
  assert {
    condition     = anytrue([for rule in azurerm_network_security_group.app_service_integration[0].security_rule : rule.access == "Allow" && rule.direction == "Outbound" && rule.destination_address_prefix == var.network.private_endpoint_subnet && toset(rule.destination_port_ranges) == toset(["1433", "443"])]) && anytrue([for rule in azurerm_network_security_group.app_service_integration[0].security_rule : rule.access == "Deny" && rule.priority == 110 && rule.destination_port_range == "*"])
    error_message = "SQL Proxy/HTTPS only to the data subnet; no broad redirect-port range."
  }
}

run "hybrid_edge_requires_private_sql_acceptance" {
  command = plan
  variables {
    hybrid_private_data_enabled                    = true
    sql_public_network_access_enabled              = false
    key_vault_public_network_access_enabled        = false
    function_storage_public_network_access_enabled = false
    sql_firewall_ipv4s                             = {}
    network = {
      address_space                  = "10.240.0.0/16"
      app_gateway_subnet             = "10.240.1.0/24"
      private_endpoint_subnet        = "10.240.3.0/24"
      app_service_integration_subnet = "10.240.4.0/24"
    }
  }
  expect_failures = [terraform_data.approval]
}

run "reject_unapproved_cost" {
  command = plan
  variables {
    deployment_approved = false
  }
  expect_failures = [terraform_data.approval]
}

run "reject_public_edge_before_live_gates" {
  command = plan
  variables {
    public_edge_live_gates_approved = false
  }
  expect_failures = [terraform_data.approval]
}

run "reject_missing_operator_ip" {
  command = plan
  variables {
    operator_ip = null
  }
  expect_failures = [var.operator_ip]
}

run "reject_azure_wide_operator_ip" {
  command = plan
  variables {
    operator_ip = "0.0.0.0"
  }
  expect_failures = [var.operator_ip]
}

run "reject_broad_sql_rule" {
  command = plan
  variables {
    sql_firewall_ipv4s = { azure = "0.0.0.0" }
  }
  expect_failures = [var.sql_firewall_ipv4s]
}

run "reject_private_operator_ip" {
  command = plan
  variables {
    operator_ip = "10.240.1.4"
  }
  expect_failures = [var.operator_ip]
}

run "reject_operator_cidr" {
  command = plan
  variables {
    operator_ip = "203.0.113.10/24"
  }
  expect_failures = [var.operator_ip]
}

run "reject_sql_cidr" {
  command = plan
  variables {
    sql_firewall_ipv4s = { broad = "203.0.113.0/24" }
  }
  expect_failures = [var.sql_firewall_ipv4s]
}

run "reject_public_edge_without_app_sql_rules" {
  command = plan
  variables {
    sql_firewall_ipv4s = {}
  }
  expect_failures = [terraform_data.sql_firewall_gate]
}

run "reject_development_inference_without_approved_threshold" {
  command = plan
  variables {
    dev_openai_inference_enabled = true
  }
  expect_failures = [terraform_data.dev_openai_gate[0]]
}

run "development_inference_requires_explicit_safety_configuration" {
  command = plan

  assert {
    condition     = !var.dev_openai_inference_enabled && var.dev_openai_content_safety_threshold == null && !output.inference_enabled
    error_message = "Development inference must remain off until explicitly enabled with an approved content-safety threshold."
  }
  assert {
    condition     = azurerm_api_management_api.dev_openai.subscription_required && azurerm_api_management_api_policy.dev_openai.xml_content == file("${path.module}/../../gateway/policies/disabled.xml")
    error_message = "The staged development API must remain subscription-required and fail closed by default."
  }
  assert {
    condition     = length(azurerm_api_management_product.dev_openai) == 0 && length(azapi_resource.dev_model_backend) == 0 && length(azapi_resource.dev_model_pool) == 0 && length(azapi_resource.dev_content_safety_backend) == 0
    error_message = "No development product or inference backend may be created while the safety approval gate is unset."
  }
}
