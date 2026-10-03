terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. PostgreSQL remains the system of record.
# These tables are not written by the application.

resource "aws_dynamodb_table" "conversations" {
  count = var.enabled ? 1 : 0

  name         = "${var.name}-conversations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "conversation_id"
  tags         = var.tags

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "conversation_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "tool_executions" {
  count = var.enabled ? 1 : 0

  name         = "${var.name}-tool-executions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "execution_id"
  tags         = var.tags

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "execution_id"
    type = "S"
  }
}
