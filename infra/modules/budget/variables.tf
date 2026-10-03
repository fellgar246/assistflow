variable "enabled" {
  description = "Create the monthly cost budget. Off until an operator applies a live stack."
  type        = bool
  default     = false
}

variable "monthly_limit_usd" {
  description = "Engineering ceiling for the monthly budget, in USD. This is not a provider invoice guarantee."
  type        = string
  default     = "5"
}

variable "name" {
  description = "Budget display name."
  type        = string
  default     = "assistflow-monthly"
}

variable "time_period_start" {
  description = "UTC start of the budget window."
  type        = string
  default     = "2026-01-01_00:00"
}

variable "tags" {
  description = "Tags applied to the budget and its alert topic."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
