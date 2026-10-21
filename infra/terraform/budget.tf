locals {
  monthly_budgets = {
    for budget in(var.monthly_budget == null ? [] : [var.monthly_budget]) :
    "main" => budget if local.prerequisites_stage
  }
}

resource "azurerm_consumption_budget_resource_group" "main" {
  for_each          = local.monthly_budgets
  name              = each.value.name
  resource_group_id = local.rg_id
  amount            = each.value.amount
  time_grain        = "Monthly"
  time_period {
    start_date = each.value.start_date
    end_date   = each.value.end_date
  }
  dynamic "notification" {
    for_each = toset([50, 80, 100])
    content {
      enabled        = true
      operator       = "GreaterThanOrEqualTo"
      threshold      = notification.value
      threshold_type = "Actual"
      contact_emails = each.value.contact_emails
    }
  }
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [terraform_data.approval]
}

import {
  for_each = { for key, budget in local.monthly_budgets : key => budget if budget.import_existing }
  to       = azurerm_consumption_budget_resource_group.main[each.key]
  id       = "${local.rg_id}/providers/Microsoft.Consumption/budgets/${each.value.name}"
}
