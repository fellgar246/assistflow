variable "enabled" {
  description = "Create the queue, the event bus, and the consumer. Off until an operator applies them."
  type        = bool
  default     = false
}

variable "name" {
  description = "Name prefix for the queue, bus, and consumer. Used only when the module is enabled."
  type        = string
  default     = "assistflow-side-effects"
}

variable "worker_package_path" {
  description = "Zip for the consumer function. Required only when the module is enabled."
  type        = string
  default     = ""
}

variable "worker_package_hash" {
  description = "Base64 SHA-256 of the consumer package. Empty leaves the hash unset."
  type        = string
  default     = ""
}

variable "database_url" {
  description = "Database URL for the consumer. Do not commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to the queue, the bus, and the consumer."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
