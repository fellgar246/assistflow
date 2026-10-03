variable "enabled" {
  description = "Create the dev API. Off until an operator applies it."
  type        = bool
  default     = false
}

variable "name" {
  description = "API and function name. Used only when the module is enabled."
  type        = string
  default     = "assistflow-dev-api"
}

variable "package_path" {
  description = "Zip that contains health.py. Required only when the module is enabled."
  type        = string
  default     = ""
}

variable "package_hash" {
  description = "Base64 SHA-256 of the API package. Empty leaves the hash unset."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "Days to keep the function log group. Fourteen days is the longest default."
  type        = number
  default     = 14

  validation {
    condition     = var.log_retention_days >= 1 && var.log_retention_days <= 14
    error_message = "Log retention must be 14 days or shorter."
  }
}

variable "tags" {
  description = "Tags applied to the API, the function, and its log group."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
