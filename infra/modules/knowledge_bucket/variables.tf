variable "enabled" {
  description = "Create the knowledge document bucket. Off until an operator applies it."
  type        = bool
  default     = false
}

variable "name_prefix" {
  description = "Prefix for the knowledge bucket name. Used only when the module is enabled."
  type        = string
  default     = "assistflow-knowledge-"
}

variable "tags" {
  description = "Tags applied to the bucket."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
