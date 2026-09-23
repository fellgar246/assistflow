terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_budgets_budget" "application" {
  count = var.enabled ? 1 : 0

  name         = var.name
  budget_type  = "COST"
  limit_amount = var.monthly_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  time_period_start = var.time_period_start
}
