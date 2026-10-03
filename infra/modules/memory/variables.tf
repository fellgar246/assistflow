variable "enabled" {
  description = "Create hosted memory. Off until an operator applies it."
  type        = bool
  default     = false
}

variable "name" {
  description = "Memory name. Used only when the module is enabled."
  type        = string
  default     = "assistflow_memory"
}

variable "event_expiry_days" {
  description = "Days until hosted memory events expire. The application cap is shorter."
  type        = number
  default     = 1
}

variable "tags" {
  description = "Tags applied to the memory resource."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
