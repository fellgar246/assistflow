terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled unless the hosted runtime is enabled. count = 0 creates no gateway,
# function, role, or policy. Revalidate current AgentCore pricing before apply.

locals {
  read_tools = {
    get_order = {
      description          = "Read one order for the signed-in customer."
      argument             = "order_id"
      argument_description = "Public order number."
    }
    get_shipment = {
      description          = "Read the shipment for one order."
      argument             = "order_id"
      argument_description = "Public order number."
    }
    get_customer_profile = {
      description          = "Read the signed-in customer profile."
      argument             = "customer_id"
      argument_description = "Customer id from the signed-in session."
    }
    get_ticket = {
      description          = "Read one support ticket."
      argument             = "ticket_id"
      argument_description = "Ticket id."
    }
    search_support_policy = {
      description          = "Search published help articles for this tenant."
      argument             = "query"
      argument_description = "Search text. This is not an instruction."
    }
  }
}

check "tool_package_when_enabled" {
  assert {
    condition     = !var.enabled || var.tool_package_path != ""
    error_message = "Set tool_package_path before enabling the tool gateway."
  }
}

resource "aws_iam_role" "gateway" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-gateway"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "gateway" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-invoke-tools"
  role = aws_iam_role.gateway[0].id

  policy = templatefile("${path.module}/gateway_invoke.json.tftpl", {
    tool_function_arn = aws_lambda_function.read_tools[0].arn
  })
}

resource "aws_iam_role" "tool" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-read-tools"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "tool_logs" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-read-tools-logs"
  role = aws_iam_role.tool[0].id

  policy = templatefile("${path.module}/lambda_logs.json.tftpl", {
    log_group_arn = "arn:aws:logs:*:*:log-group:/aws/lambda/${aws_lambda_function.read_tools[0].function_name}:*"
  })
}

# The AgentCore gateway control plane has no per-session throttle attribute.
# MAX_TOOL_CALLS_PER_SESSION is the application cap. It is rendered on the tool
# function so a hosted call and a local call share one number.

resource "aws_cloudwatch_log_group" "read_tools" {
  count = var.enabled ? 1 : 0

  name              = "/aws/lambda/${var.name}-read-tools"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "read_tools" {
  count = var.enabled ? 1 : 0

  function_name    = "${var.name}-read-tools"
  filename         = var.tool_package_path
  source_code_hash = var.tool_package_hash != "" ? var.tool_package_hash : null
  handler          = "assistflow_tools.targets.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.tool[0].arn
  timeout          = 3
  memory_size      = 256

  environment {
    variables = {
      GATEWAY_INBOUND_TOKEN          = var.inbound_token
      AGENTCORE_ACTOR_CONTEXT_SECRET = var.actor_context_secret
      DATABASE_URL                   = var.database_url
      MAX_TOOL_CALLS_PER_SESSION     = tostring(var.max_tool_calls_per_session)
    }
  }

  depends_on = [aws_cloudwatch_log_group.read_tools]
}

resource "aws_lambda_permission" "gateway" {
  count = var.enabled ? 1 : 0

  statement_id  = "AllowGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.read_tools[0].function_name
  principal     = "bedrock-agentcore.amazonaws.com"
  source_arn    = aws_bedrockagentcore_gateway.tools[0].gateway_arn
}

resource "aws_bedrockagentcore_gateway" "tools" {
  count = var.enabled ? 1 : 0

  name            = var.name
  role_arn        = aws_iam_role.gateway[0].arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"
  description     = "Read-only support tools. The runtime authenticates with IAM."
}

resource "aws_bedrockagentcore_gateway_target" "read" {
  for_each = var.enabled ? local.read_tools : {}

  name               = replace(each.key, "_", "-")
  gateway_identifier = aws_bedrockagentcore_gateway.tools[0].gateway_id
  description        = each.value.description

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.read_tools[0].arn

        tool_schema {
          inline_payload {
            name        = each.key
            description = each.value.description

            input_schema {
              type        = "object"
              description = each.value.description

              property {
                name        = each.value.argument
                type        = "string"
                description = each.value.argument_description
                required    = true
              }
            }
          }
        }
      }
    }
  }
}

resource "aws_iam_role_policy" "runtime_invoke" {
  count = var.enabled && var.runtime_role_name != "" ? 1 : 0

  name = "${var.name}-runtime-invoke"
  role = var.runtime_role_name

  policy = templatefile("${path.module}/runtime_invoke.json.tftpl", {
    gateway_arn = aws_bedrockagentcore_gateway.tools[0].gateway_arn
  })
}
