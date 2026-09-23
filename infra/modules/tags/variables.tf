variable "project" {
  description = "Product tag applied to managed resources."
  type        = string
  default     = "assistflow"
}

variable "environment" {
  description = "Deployment environment tag."
  type        = string
  default     = "dev"
}

variable "cost_center" {
  description = "Cost attribution tag."
  type        = string
  default     = "learning"
}
