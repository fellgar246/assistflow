terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no queue, bus, or consumer.
# Revalidate current EventBridge, SQS, and Lambda prices before apply.

check "worker_config_when_enabled" {
  assert {
    condition     = !var.enabled || (var.worker_package_path != "" && var.database_url != "")
    error_message = "Set worker_package_path and database_url before enabling async workers."
  }
}

resource "aws_sqs_queue" "dlq" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-dlq"
  tags = var.tags
}

resource "aws_sqs_queue" "side_effects" {
  count = var.enabled ? 1 : 0

  name                       = var.name
  visibility_timeout_seconds = 30
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[0].arn
    maxReceiveCount     = 5
  })
  tags = var.tags
}

resource "aws_cloudwatch_event_bus" "side_effects" {
  count = var.enabled ? 1 : 0

  name = var.name
  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "side_effects" {
  count = var.enabled ? 1 : 0

  name           = "${var.name}-domain"
  event_bus_name = aws_cloudwatch_event_bus.side_effects[0].name
  event_pattern = jsonencode({
    source      = ["assistflow"]
    detail-type = ["ticket.created", "conversation.escalated", "approval.consumed", "conversation.resolved"]
  })
  tags = var.tags
}

resource "aws_sqs_queue_policy" "side_effects" {
  count = var.enabled ? 1 : 0

  queue_url = aws_sqs_queue.side_effects[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.side_effects[0].arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.side_effects[0].arn
          }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_event_target" "side_effects" {
  count = var.enabled ? 1 : 0

  rule           = aws_cloudwatch_event_rule.side_effects[0].name
  event_bus_name = aws_cloudwatch_event_bus.side_effects[0].name
  arn            = aws_sqs_queue.side_effects[0].arn
  target_id      = "side-effects"
}

resource "aws_iam_role" "consumer" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-consumer"
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

resource "aws_iam_role_policy" "consumer" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-consumer"
  role = aws_iam_role.consumer[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = aws_sqs_queue.side_effects[0].arn
      }
    ]
  })
}

resource "aws_lambda_function" "consumer" {
  count = var.enabled ? 1 : 0

  function_name    = "${var.name}-consumer"
  filename         = var.worker_package_path
  source_code_hash = var.worker_package_hash != "" ? var.worker_package_hash : null
  handler          = "assistflow_api.side_effect_worker.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.consumer[0].arn
  timeout          = 30
  memory_size      = 256
  tags             = var.tags

  environment {
    variables = {
      DATABASE_URL = var.database_url
    }
  }
}

resource "aws_lambda_event_source_mapping" "consumer" {
  count = var.enabled ? 1 : 0

  event_source_arn = aws_sqs_queue.side_effects[0].arn
  function_name    = aws_lambda_function.consumer[0].arn
  batch_size       = 10
}
