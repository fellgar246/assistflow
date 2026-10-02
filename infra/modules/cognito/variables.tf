variable "enabled" {
  description = "Create the user pool, app client, and groups. Off until an operator applies them."
  type        = bool
  default     = false
}

variable "name" {
  description = "User pool name. Used only when the module is enabled."
  type        = string
  default     = "assistflow"
}

variable "tags" {
  description = "Tags applied to the user pool."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
