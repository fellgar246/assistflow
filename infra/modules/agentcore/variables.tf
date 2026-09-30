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
