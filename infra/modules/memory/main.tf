terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no memory resource.
# Application limits still bound a session. This expiry is only a backstop.

resource "aws_bedrockagentcore_memory" "session" {
  count = var.enabled ? 1 : 0

  name                  = var.name
  description           = "Hosted session memory. Preferences stay in PostgreSQL."
  event_expiry_duration = var.event_expiry_days
  tags                  = var.tags
}
