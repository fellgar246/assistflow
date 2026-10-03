variable "aws_region" {
  description = "Region used when this stack is applied. The foundation does not apply it."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Product tag."
  type        = string
  default     = "assistflow"
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"
}

variable "cost_center" {
  description = "Cost attribution tag."
  type        = string
  default     = "learning"
}

variable "enable_api" {
  description = "Dev API Gateway and probe function. Disabled by default."
  type        = bool
  default     = false
}

variable "api_package_path" {
  description = "Zip for the dev API probe. Required only when enable_api is true."
  type        = string
  default     = ""
}

variable "api_package_hash" {
  description = "Base64 SHA-256 of the dev API probe. Empty leaves the hash unset."
  type        = string
  default     = ""
}

variable "enable_dynamodb_metadata" {
  description = "Optional DynamoDB metadata tables. PostgreSQL stays the system of record. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_github_oidc" {
  description = "GitHub OIDC provider and dev deploy role. Disabled by default."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "Repository allowed to assume the deploy role, as owner/name."
  type        = string
  default     = ""
}

variable "github_deploy_environment" {
  description = "GitHub environment the deploy role trusts."
  type        = string
  default     = "dev"
}

variable "state_bucket_name" {
  description = "Remote state bucket name. Required only when enable_github_oidc is true."
  type        = string
  default     = ""
}

variable "lock_table_name" {
  description = "DynamoDB table that locks remote state."
  type        = string
  default     = "assistflow-dev-tf-lock"
}

variable "bedrock_model_id" {
  description = "Foundation model id the hosted runtime may invoke."
  type        = string
  default     = "anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "bedrock_guardrail_id" {
  description = "Guardrail id the hosted runtime may apply. Empty omits that permission."
  type        = string
  default     = ""
}

variable "budget_enabled" {
  description = "Create the monthly AWS budget. Left off until a live stack is applied."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  description = "Engineering ceiling recorded on the budget resource, in USD."
  type        = string
  default     = "5"
}

variable "enable_agentcore" {
  description = "Hosted agent runtime. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_long_term_memory" {
  description = "Long-term agent memory. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_managed_rag" {
  description = "Managed retrieval. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_knowledge_bucket" {
  description = "Document bucket for application-owned retrieval. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_schedules" {
  description = "Scheduled jobs. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_cognito" {
  description = "User pool for sign-in. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_observability" {
  description = "Log groups and the operations dashboard. Disabled by default."
  type        = bool
  default     = false
}

variable "enable_async_workers" {
  description = "Queue, event bus, and side-effect consumer. Disabled by default."
  type        = bool
  default     = false
}

variable "async_worker_package_path" {
  description = "Zip for the side-effect consumer. Required only when enable_async_workers is true."
  type        = string
  default     = ""
}

variable "async_worker_package_hash" {
  description = "Base64 SHA-256 of the side-effect consumer package. Empty leaves the hash unset."
  type        = string
  default     = ""
}

variable "async_worker_database_url" {
  description = "Database URL for the side-effect consumer. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "agentcore_container_image_uri" {
  description = "Image for the hosted runtime. Used only when enable_agentcore is true."
  type        = string
  default     = ""
}

variable "agentcore_tool_package_path" {
  description = "Zip for the read-tool function. Required only when enable_agentcore is true."
  type        = string
  default     = ""
}

variable "agentcore_tool_package_hash" {
  description = "Base64 SHA-256 of the tool package. Empty leaves the hash unset."
  type        = string
  default     = ""
}

variable "agentcore_gateway_inbound_token" {
  description = "Credential the runtime presents to the tool function. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "agentcore_actor_context_secret" {
  description = "Secret that signs the tenant context. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "agentcore_tool_database_url" {
  description = "Database URL for the tool function. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}
