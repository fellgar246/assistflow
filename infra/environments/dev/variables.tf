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
