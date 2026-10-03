variable "enabled" {
  description = "Create the hosted agent runtime. Off until an operator applies it."
  type        = bool
  default     = false
}

variable "name" {
  description = "Runtime name. Used only when the module is enabled."
  type        = string
  default     = "assistflow_support"
}

variable "container_image_uri" {
  description = "Image URI for the hosted runtime. Ignored while the module is disabled."
  type        = string
  default     = ""
}

variable "aws_region" {
  description = "Region used in the model and guardrail ARNs."
  type        = string
  default     = "us-east-1"
}

variable "bedrock_model_id" {
  description = "Foundation model id the runtime may invoke. Not a wildcard."
  type        = string
  default     = "anthropic.claude-3-5-haiku-20241022-v1:0"
}

variable "bedrock_guardrail_id" {
  description = "Guardrail id the runtime may apply. Empty omits that permission."
  type        = string
  default     = ""
}
