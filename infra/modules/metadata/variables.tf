variable "enabled" {
  description = "Create optional metadata tables. Off until an operator applies them."
  type        = bool
  default     = false
}

variable "name" {
  description = "Prefix for the metadata tables. Used only when the module is enabled."
  type        = string
  default     = "assistflow-dev"
}

variable "tags" {
  description = "Tags applied to the metadata tables."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
