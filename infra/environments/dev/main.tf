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

module "agentcore_gateway" {
  source = "../../modules/agentcore_gateway"

  enabled              = var.enable_agentcore
  runtime_role_name    = module.agentcore.runtime_role_name
  tool_package_path    = var.agentcore_tool_package_path
  tool_package_hash    = var.agentcore_tool_package_hash
  inbound_token        = var.agentcore_gateway_inbound_token
  actor_context_secret = var.agentcore_actor_context_secret
  database_url         = var.agentcore_tool_database_url
}

module "knowledge_bucket" {
  source = "../../modules/knowledge_bucket"

  enabled = var.enable_knowledge_bucket || var.enable_managed_rag
  tags    = local.required_tags
}

module "managed_rag" {
  source = "../../modules/managed_rag"

  enabled    = var.enable_managed_rag
  bucket_arn = module.knowledge_bucket.bucket_arn
  tags       = local.required_tags
}

module "cognito" {
  source = "../../modules/cognito"

  enabled = var.enable_cognito
  tags    = local.required_tags
}

module "async_workers" {
  source = "../../modules/async_workers"

  enabled             = var.enable_async_workers
  worker_package_path = var.async_worker_package_path
  worker_package_hash = var.async_worker_package_hash
  database_url        = var.async_worker_database_url
  tags                = local.required_tags
}
