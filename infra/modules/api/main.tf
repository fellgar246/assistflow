terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no API, function, role, or log group.
# The function answers health and one seeded read. It does not open a database.

check "package_when_enabled" {
  assert {
    condition     = !var.enabled || var.package_path != ""
    error_message = "Set package_path before enabling the dev API."
  }
}

resource "aws_cloudwatch_log_group" "api" {
  count = var.enabled ? 1 : 0

  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "api" {
  count = var.enabled ? 1 : 0

  name = var.name
  tags = var.tags

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

resource "aws_iam_role_policy" "api_logs" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-logs"
  role = aws_iam_role.api[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.api[0].arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "api" {
  count = var.enabled ? 1 : 0

  function_name                  = var.name
  filename                       = var.package_path
  source_code_hash               = var.package_hash != "" ? var.package_hash : null
  handler                        = "health.handler"
  runtime                        = "python3.12"
  role                           = aws_iam_role.api[0].arn
  timeout                        = 3
  memory_size                    = 128
  reserved_concurrent_executions = 2
  tags                           = var.tags

  depends_on = [aws_iam_role_policy.api_logs]
}

resource "aws_apigatewayv2_api" "http" {
  count = var.enabled ? 1 : 0

  name          = var.name
  protocol_type = "HTTP"
  description   = "Dev API probe. Health and one seeded order read."
  tags          = var.tags
}

resource "aws_apigatewayv2_integration" "api" {
  count = var.enabled ? 1 : 0

  api_id                 = aws_apigatewayv2_api.http[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api[0].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "health" {
  count = var.enabled ? 1 : 0

  api_id    = aws_apigatewayv2_api.http[0].id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}

resource "aws_apigatewayv2_route" "seeded_order" {
  count = var.enabled ? 1 : 0

  api_id    = aws_apigatewayv2_api.http[0].id
  route_key = "GET /orders/ORD-10482"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}

resource "aws_apigatewayv2_stage" "default" {
  count = var.enabled ? 1 : 0

  api_id      = aws_apigatewayv2_api.http[0].id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}

resource "aws_lambda_permission" "http" {
  count = var.enabled ? 1 : 0

  statement_id  = "AllowHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http[0].execution_arn}/*/*"
}
