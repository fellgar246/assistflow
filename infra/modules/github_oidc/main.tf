terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. The role trusts one repository environment.
# It can deploy this project. It is not an administrator role.

check "repository_when_enabled" {
  assert {
    condition = !var.enabled || (
      length(regexall("^[^/]+/[^/]+$", var.github_repository)) == 1 && var.state_bucket_name != ""
    )
    error_message = "Set github_repository to owner/name and set state_bucket_name before enabling GitHub OIDC."
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.enabled ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
  tags            = var.tags
}

resource "aws_iam_role" "deploy" {
  count = var.enabled ? 1 : 0

  name = "${var.project}-dev-deploy"
  tags = var.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRoleWithWebIdentity"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github[0].arn
        }
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.deploy_environment}"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "deploy" {
  count = var.enabled ? 1 : 0

  name = "${var.project}-dev-deploy"
  role = aws_iam_role.deploy[0].id
  policy = templatefile("${path.module}/deploy_policy.json.tftpl", {
    state_bucket = var.state_bucket_name
    lock_table   = var.lock_table_name
    region       = var.aws_region
    project      = var.project
  })
}
