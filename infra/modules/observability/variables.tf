variable "enabled" {
  description = "Create log groups and the dashboard. Off until an operator applies them."
  type        = bool
  default     = false
}

variable "aws_region" {
  description = "Region shown on the dashboard widgets."
  type        = string
  default     = "us-east-1"
}

variable "log_retention_days" {
  description = "Days to keep API and tool logs."
  type        = number
  default     = 14
}

variable "tags" {
  description = "Tags applied to the log groups."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
