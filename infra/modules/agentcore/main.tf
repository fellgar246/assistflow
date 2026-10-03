terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no runtime, role, or policy.
# Invoke permission names one model and, when set, one guardrail.

check "named_bedrock_model" {
  assert {
    condition     = !var.enabled || (var.bedrock_model_id != "" && !endswith(var.bedrock_model_id, "*"))
    error_message = "Set bedrock_model_id to one model before enabling the hosted runtime."
  }
}

data "aws_caller_identity" "current" {
  count = var.enabled && var.bedrock_guardrail_id != "" ? 1 : 0
}

locals {
  account_id = one(data.aws_caller_identity.current[*].account_id)
  model_arn  = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
  bedrock_statements = concat(
    [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ]
        Resource = local.model_arn
      }
    ],
    local.account_id == null ? [] : [
      {
        Effect = "Allow"
        Action = [
          "bedrock:ApplyGuardrail",
          "bedrock:GetGuardrail",
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}:${local.account_id}:guardrail/${var.bedrock_guardrail_id}"
      }
    ]
  )
}

resource "aws_iam_role" "runtime" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-runtime"

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

resource "aws_iam_role_policy" "runtime" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-runtime"
  role = aws_iam_role.runtime[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect = "Allow"
          Action = [
            "logs:CreateLogGroup",
            "logs:CreateLogStream",
            "logs:PutLogEvents",
          ]
          Resource = "arn:aws:logs:*:*:log-group:/aws/bedrock-agentcore/*"
        }
      ],
      local.bedrock_statements,
      [
        {
          Effect = "Allow"
          Action = [
            "ecr:GetAuthorizationToken",
          ]
          Resource = "*"
        },
        {
          Effect = "Allow"
          Action = [
            "ecr:BatchGetImage",
            "ecr:GetDownloadUrlForLayer",
          ]
          Resource = "arn:aws:ecr:*:*:repository/*"
        }
      ]
    )
  })
}

resource "aws_bedrockagentcore_agent_runtime" "support" {
  count = var.enabled ? 1 : 0

  agent_runtime_name = var.name
  role_arn           = aws_iam_role.runtime[0].arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = var.container_image_uri
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }
}
