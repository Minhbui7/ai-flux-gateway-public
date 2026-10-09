resource "azurerm_web_application_firewall_policy" "appgw" {
  name                = "${local.prefix}-appgw-waf"
  location            = var.location
  resource_group_name = local.rg
  tags                = local.tags
  policy_settings {
    enabled                          = true
    mode                             = "Prevention"
    request_body_check               = true
    max_request_body_size_in_kb      = var.edge.waf_body_limit_kb
    request_body_inspect_limit_in_kb = var.edge.waf_inspection_limit_kb
    file_upload_enforcement          = true
    request_body_enforcement         = true
  }
  managed_rules {
    managed_rule_set {
      type    = "OWASP"
      version = "3.2"
    }
  }
}

locals {
  appgw_backends = merge({
    apim = { fqdn = "${local.apim_name}.azure-api.net", health = "/status-0123456789abcdef" }
    }, { for k, app in azurerm_linux_web_app.main : k => {
      fqdn = app.default_hostname, health = var.apps[k].health_path
  } })
}

resource "azurerm_application_gateway" "main" {
  name                = "${local.prefix}-appgw"
  location            = var.location
  resource_group_name = local.rg
  zones               = var.edge.zones
  firewall_policy_id  = azurerm_web_application_firewall_policy.appgw.id
  tags                = local.tags
  sku {
    name = "WAF_v2"
    tier = "WAF_v2"
  }
  autoscale_configuration {
    min_capacity = 2
    max_capacity = 4
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.identity["edge"].id]
  }
  gateway_ip_configuration {
    name      = "gateway"
    subnet_id = azurerm_subnet.main["appgw"].id
  }
  frontend_ip_configuration {
    name                            = "private"
    subnet_id                       = azurerm_subnet.main["appgw"].id
    private_ip_address              = var.network.app_gateway_ip
    private_ip_address_allocation   = "Static"
    private_link_configuration_name = "frontdoor"
  }
  private_link_configuration {
    name = "frontdoor"
    ip_configuration {
      name                          = "primary"
      subnet_id                     = azurerm_subnet.main["link"].id
      private_ip_address_allocation = "Dynamic"
      primary                       = true
    }
  }
  frontend_port {
    name = "https"
    port = 443
  }
  ssl_certificate {
    name                = "origin"
    key_vault_secret_id = var.edge.certificate_secret_id
  }
  ssl_policy {
    policy_type = "Predefined"
    policy_name = "AppGwSslPolicy20220101S"
  }
  http_listener {
    name                           = "private-https"
    frontend_ip_configuration_name = "private"
    frontend_port_name             = "https"
    protocol                       = "Https"
    host_name                      = var.edge.origin_hostname
    require_sni                    = true
    ssl_certificate_name           = "origin"
  }
  global {
    request_buffering_enabled  = false
    response_buffering_enabled = false
  }
  dynamic "backend_address_pool" {
    for_each = local.appgw_backends
    content {
      name  = backend_address_pool.key
      fqdns = [backend_address_pool.value.fqdn]
    }
  }
  dynamic "backend_http_settings" {
    for_each = local.appgw_backends
    content {
      name                                = backend_http_settings.key
      cookie_based_affinity               = "Disabled"
      port                                = 443
      protocol                            = "Https"
      pick_host_name_from_backend_address = true
      probe_name                          = backend_http_settings.key
      request_timeout                     = var.edge.app_gateway_timeout_seconds
    }
  }
  dynamic "probe" {
    for_each = local.appgw_backends
    content {
      name                                      = probe.key
      protocol                                  = "Https"
      path                                      = probe.value.health
      pick_host_name_from_backend_http_settings = true
      interval                                  = 30
      timeout                                   = 30
      unhealthy_threshold                       = 3
      match {
        status_code = ["200"]
      }
    }
  }
  request_routing_rule {
    name               = "routes"
    priority           = 100
    rule_type          = "PathBasedRouting"
    http_listener_name = "private-https"
    url_path_map_name  = "routes"
  }
  url_path_map {
    name                               = "routes"
    default_backend_address_pool_name  = "customer"
    default_backend_http_settings_name = "customer"
    path_rule {
      name                       = "inference"
      paths                      = ["/v1", "/v1/*"]
      backend_address_pool_name  = "apim"
      backend_http_settings_name = "apim"
    }
    path_rule {
      name                       = "control-plane"
      paths                      = ["/api", "/api/*", "/health", "/ready"]
      backend_address_pool_name  = "api"
      backend_http_settings_name = "api"
    }
    path_rule {
      name                       = "admin"
      paths                      = ["/admin", "/admin/*"]
      backend_address_pool_name  = "admin"
      backend_http_settings_name = "admin"
    }
  }
  depends_on = [
    azurerm_role_assignment.edge_certificate,
    azurerm_private_dns_a_record.apim,
    azurerm_private_endpoint.main,
    azurerm_subnet_network_security_group_association.appgw,
  ]
}

resource "azurerm_cdn_frontdoor_profile" "main" {
  name                     = "${local.prefix}-frontdoor"
  resource_group_name      = local.rg
  sku_name                 = "Premium_AzureFrontDoor"
  response_timeout_seconds = var.edge.request_timeout_seconds
  tags                     = local.tags
  depends_on               = [terraform_data.approval]
}

resource "azurerm_cdn_frontdoor_endpoint" "main" {
  name                     = "${local.prefix}-edge"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  tags                     = local.tags
}

resource "azurerm_cdn_frontdoor_origin_group" "main" {
  name                     = "appgateway"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  session_affinity_enabled = false
  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }
  health_probe {
    path                = "/health"
    protocol            = "Https"
    request_type        = "GET"
    interval_in_seconds = 60
  }
}

resource "azapi_resource" "frontdoor_origin" {
  type      = "Microsoft.Cdn/profiles/originGroups/origins@2025-04-15"
  parent_id = azurerm_cdn_frontdoor_origin_group.main.id
  name      = "private-appgateway"
  body = {
    properties = {
      enabledState                = "Enabled"
      enforceCertificateNameCheck = true
      hostName                    = var.edge.origin_hostname
      originHostHeader            = var.edge.origin_hostname
      httpPort                    = 80
      httpsPort                   = 443
      priority                    = 1
      weight                      = 1000
      sharedPrivateLinkResource = {
        groupId             = "private"
        privateLink         = { id = azurerm_application_gateway.main.id }
        privateLinkLocation = var.edge.private_link_location
        requestMessage      = "AIFLUX Front Door to private Application Gateway; approve only this profile."
      }
    }
  }
}

resource "azurerm_cdn_frontdoor_route" "main" {
  name                          = "private-edge"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.main.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.main.id
  cdn_frontdoor_origin_ids      = [azapi_resource.frontdoor_origin.id]
  patterns_to_match             = ["/*"]
  supported_protocols           = ["Https"]
  forwarding_protocol           = "HttpsOnly"
  https_redirect_enabled        = true
  link_to_default_domain        = true
  enabled                       = false
}

resource "azurerm_cdn_frontdoor_firewall_policy" "main" {
  name                = "${local.compact}edgewaf"
  resource_group_name = local.rg
  sku_name            = "Premium_AzureFrontDoor"
  enabled             = true
  mode                = "Prevention"
  tags                = local.tags
  managed_rule {
    type    = "Microsoft_DefaultRuleSet"
    version = "2.1"
    action  = "Block"
  }
  managed_rule {
    type    = "Microsoft_BotManagerRuleSet"
    version = "1.0"
    action  = "Block"
  }
}

resource "azurerm_cdn_frontdoor_security_policy" "main" {
  name                     = "edge-waf"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.main.id
  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.main.id
      association {
        patterns_to_match = ["/*"]
        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_endpoint.main.id
        }
      }
    }
  }
}
