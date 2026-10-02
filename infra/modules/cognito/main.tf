terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no user pool, client, or group.
# Revalidate current Cognito prices before apply.

resource "aws_cognito_user_pool" "main" {
  count = var.enabled ? 1 : 0

  name = var.name

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  schema {
    name                = "tenant_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 36
      max_length = 36
    }
  }

  schema {
    name                = "role"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 1
      max_length = 32
    }
  }

  schema {
    name                = "customer_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 36
      max_length = 36
    }
  }

  schema {
    name                = "agent_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 36
      max_length = 36
    }
  }

  tags = var.tags
}

resource "aws_cognito_user_pool_client" "web" {
  count = var.enabled ? 1 : 0

  name         = "${var.name}-web"
  user_pool_id = aws_cognito_user_pool.main[0].id

  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  explicit_auth_flows                  = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = false
}

resource "aws_cognito_user_group" "customer" {
  count = var.enabled ? 1 : 0

  name         = "customer"
  user_pool_id = aws_cognito_user_pool.main[0].id
  description  = "Customers. Tenant and customer id are token claims."
}

resource "aws_cognito_user_group" "support_agent" {
  count = var.enabled ? 1 : 0

  name         = "support_agent"
  user_pool_id = aws_cognito_user_pool.main[0].id
  description  = "Support agents. Tenant and agent id are token claims."
}
