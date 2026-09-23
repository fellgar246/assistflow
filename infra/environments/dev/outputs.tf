output "tags" {
  description = "Tags applied to resources in this environment."
  value       = module.required_tags.tags
}

output "feature_flags" {
  description = "Optional hosted features. All default to off."
  value = {
    enable_agentcore        = var.enable_agentcore
    enable_long_term_memory = var.enable_long_term_memory
    enable_managed_rag      = var.enable_managed_rag
    enable_schedules        = var.enable_schedules
  }
}

output "budget_enabled" {
  description = "Whether the monthly budget resource is created."
  value       = var.budget_enabled
}
