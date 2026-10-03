output "tags" {
  description = "Tags applied to resources in this environment."
  value       = module.required_tags.tags
}

output "feature_flags" {
  description = "Optional hosted features. All default to off."
  value = {
    enable_api               = var.enable_api
    enable_dynamodb_metadata = var.enable_dynamodb_metadata
    enable_github_oidc       = var.enable_github_oidc
    enable_agentcore         = var.enable_agentcore
    enable_long_term_memory  = var.enable_long_term_memory
    enable_managed_rag       = var.enable_managed_rag
    enable_knowledge_bucket  = var.enable_knowledge_bucket
    enable_schedules         = var.enable_schedules
    enable_async_workers     = var.enable_async_workers
    enable_cognito           = var.enable_cognito
    enable_observability     = var.enable_observability
  }
}

output "api_base_url" {
  description = "Dev API invoke URL. Empty while enable_api is false."
  value       = module.api.api_base_url
}

output "deploy_role_arn" {
  description = "GitHub deploy role ARN. Empty while enable_github_oidc is false."
  value       = module.github_oidc.deploy_role_arn
}

output "memory_id" {
  description = "Hosted memory id. Null while enable_long_term_memory is false."
  value       = module.memory.memory_id
}

output "operations_dashboard_name" {
  description = "Operations dashboard name. Empty while enable_observability is false."
  value       = module.observability.dashboard_name
}

output "cognito_user_pool_id" {
  description = "User pool id. Empty while enable_cognito is false."
  value       = module.cognito.user_pool_id
}

output "side_effect_queue_url" {
  description = "Side-effect queue URL. Empty while enable_async_workers is false."
  value       = module.async_workers.queue_url
}

output "side_effect_event_bus_name" {
  description = "Side-effect event bus name. Empty while enable_async_workers is false."
  value       = module.async_workers.event_bus_name
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
