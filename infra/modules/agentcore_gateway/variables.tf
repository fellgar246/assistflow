variable "enabled" {
  description = "Create the hosted tool gateway. Off unless the hosted runtime is enabled."
  type        = bool
  default     = false
}

variable "name" {
  description = "Gateway name. Used only when the module is enabled."
  type        = string
  default     = "assistflow_tools"
}

variable "runtime_role_name" {
  description = "Runtime role allowed to call this gateway. Empty skips that attachment."
  type        = string
  default     = ""
}

variable "tool_package_path" {
  description = "Zip for the read-tool function. Required when the module is enabled."
  type        = string
  default     = ""
}

variable "tool_package_hash" {
  description = "Base64 SHA-256 of the tool package. Empty leaves the hash unset."
  type        = string
  default     = ""
}

variable "inbound_token" {
  description = "Credential the runtime presents to the tool function. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "actor_context_secret" {
  description = "Secret that signs the tenant context. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "max_tool_calls_per_session" {
  description = "Application cap for tool calls in one session. The gateway control plane cannot set this throttle."
  type        = number
  default     = 15
}

variable "log_retention_days" {
  description = "Days to keep the tool function log group. Fourteen days is the longest default."
  type        = number
  default     = 14

  validation {
    condition     = var.log_retention_days >= 1 && var.log_retention_days <= 14
    error_message = "Log retention must be 14 days or shorter."
  }
}

variable "tags" {
  description = "Tags applied to the tool function log group."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}

variable "database_url" {
  description = "Database URL for the tool function. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}
