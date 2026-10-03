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
  description = "Days to keep the function log group."
  type        = number
  default     = 14
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
