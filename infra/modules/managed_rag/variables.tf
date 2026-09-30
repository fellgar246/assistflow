variable "enabled" {
  description = "Create a managed knowledge base. Off until an operator applies it."
  type        = bool
  default     = false
}

variable "name" {
  description = "Knowledge base name. Used only when the module is enabled."
  type        = string
  default     = "assistflow-support"
}

variable "bucket_arn" {
  description = "ARN of the document bucket. Required only when the module is enabled."
  type        = string
  default     = ""
}

variable "embedding_model_arn" {
  description = "Embedding model ARN. Required only when the module is enabled."
  type        = string
  default     = ""
}

variable "collection_arn" {
  description = "Vector collection ARN. Required only when the module is enabled."
  type        = string
  default     = ""
}

variable "vector_index_name" {
  description = "Vector index name. Used only when the module is enabled."
  type        = string
  default     = "assistflow-knowledge"
}

variable "tags" {
  description = "Tags applied to the knowledge base role."
  type        = map(string)
  default = {
    Project     = "assistflow"
    Environment = "dev"
    ManagedBy   = "terraform"
    CostCenter  = "learning"
    AutoCleanup = "true"
  }
}
