terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no schedule.
# The rule has no target, so enabling it does not invoke a job.

resource "aws_cloudwatch_event_rule" "maintenance" {
  count = var.enabled ? 1 : 0

  name                = "${var.name}-maintenance"
  description         = "Dev schedule with no target."
  schedule_expression = "rate(1 day)"
  tags                = var.tags
}
