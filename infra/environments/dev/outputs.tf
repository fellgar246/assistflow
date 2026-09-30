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
    enable_knowledge_bucket = var.enable_knowledge_bucket
    enable_schedules        = var.enable_schedules
  }
}

output "budget_enabled" {
  description = "Whether the monthly budget resource is created."
  value       = var.budget_enabled
}

output "agent_runtime_arn" {
  description = "Hosted runtime ARN. Null while enable_agentcore is false."
  value       = module.agentcore.agent_runtime_arn
}

output "agent_gateway_url" {
  description = "Hosted tool gateway URL. Null while enable_agentcore is false."
  value       = module.agentcore_gateway.gateway_url
}

output "knowledge_bucket_name" {
  description = "Document bucket name. Empty while the knowledge bucket is disabled."
  value       = module.knowledge_bucket.bucket_name
}

output "managed_knowledge_base_id" {
  description = "Managed knowledge base id. Null while enable_managed_rag is false."
  value       = module.managed_rag.knowledge_base_id
}
