terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no log group and no dashboard.
# Revalidate current CloudWatch prices before apply.

locals {
  metric_names = [
    "conversation_count",
    "agent_turn_count",
    "agent_latency_ms",
    "model_input_tokens",
    "model_output_tokens",
    "tool_call_count",
    "tool_failure_count",
    "approval_requested_count",
    "approval_accepted_count",
    "approval_rejected_count",
    "human_escalation_rate",
    "rag_retrieval_count",
    "grounded_answer_failure_count",
  ]
}

resource "aws_cloudwatch_log_group" "api" {
  count = var.enabled ? 1 : 0

  name              = "/assistflow/api"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "tools" {
  count = var.enabled ? 1 : 0

  name              = "/assistflow/tools"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_dashboard" "assistflow" {
  count = var.enabled ? 1 : 0

  dashboard_name = "assistflow"
  dashboard_body = jsonencode({
    widgets = [
      for name in local.metric_names : {
        type = "metric"
        properties = {
          metrics = [["AssistFlow", name]]
          title   = name
          region  = var.aws_region
          stat    = contains(["agent_latency_ms", "human_escalation_rate"], name) ? "Average" : "Sum"
          period  = 300
        }
      }
    ]
  })
}
