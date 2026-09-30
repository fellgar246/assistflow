terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

locals {
  required_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = var.cost_center
    AutoCleanup = "true"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.required_tags
  }
}

check "required_tags_match_module" {
  assert {
    condition     = module.required_tags.tags == local.required_tags
    error_message = "Provider default tags must match the shared tags module."
  }
}

module "required_tags" {
  source = "../../modules/tags"

  project     = var.project
  environment = var.environment
  cost_center = var.cost_center
}

module "budget" {
  source = "../../modules/budget"

  enabled           = var.budget_enabled
  monthly_limit_usd = var.monthly_budget_usd
}

module "agentcore" {
  source = "../../modules/agentcore"

  enabled             = var.enable_agentcore
  container_image_uri = var.agentcore_container_image_uri
}
