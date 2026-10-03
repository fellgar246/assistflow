terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Alerts are governance. They do not turn features off.

locals {
  monthly_alert_thresholds_usd = [1, 3, 5]
}

resource "aws_sns_topic" "budget" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-alerts"
  tags = var.tags
}

resource "aws_sns_topic_policy" "budget" {
  count = var.enabled ? 1 : 0

  arn = aws_sns_topic.budget[0].arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "budgets.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.budget[0].arn
      }
    ]
  })
}

resource "aws_budgets_budget" "application" {
  count = var.enabled ? 1 : 0

  name         = var.name
  budget_type  = "COST"
  limit_amount = var.monthly_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  time_period_start = var.time_period_start
  tags              = var.tags

  dynamic "notification" {
    for_each = toset(local.monthly_alert_thresholds_usd)
    content {
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value
      threshold_type            = "ABSOLUTE_VALUE"
      notification_type         = "ACTUAL"
      subscriber_sns_topic_arns = [aws_sns_topic.budget[0].arn]
    }
  }

  depends_on = [aws_sns_topic_policy.budget]
}
