variable "enabled" {
  description = "Create the dev schedule. Off until an operator applies it."
  type        = bool
  default     = false
}

variable "name" {
  description = "Schedule name prefix. Used only when the module is enabled."
  type        = string
  default     = "assistflow"
}

variable "tags" {
  description = "Tags applied to the schedule."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
