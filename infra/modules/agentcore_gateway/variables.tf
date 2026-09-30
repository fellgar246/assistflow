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

variable "database_url" {
  description = "Database URL for the tool function. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}
