variable "enabled" {
  description = "Create the GitHub OIDC provider and the dev deploy role. Off until an operator applies them."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the role, as owner/name."
  type        = string
  default     = ""
}

variable "deploy_environment" {
  description = "GitHub environment the deploy role trusts."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "Region used in the state-lock ARN."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for resources this role may change."
  type        = string
  default     = "assistflow"
}

variable "state_bucket_name" {
  description = "Remote state bucket. Required only when the module is enabled."
  type        = string
  default     = ""
}

variable "lock_table_name" {
  description = "DynamoDB lock table for remote state."
  type        = string
  default     = "assistflow-dev-tf-lock"
}

variable "tags" {
  description = "Tags applied to the provider and the deploy role."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
