output "knowledge_base_id" {
  description = "Managed knowledge base id. Null while the module is disabled."
  value       = var.enabled ? aws_bedrockagent_knowledge_base.support[0].id : null
}

output "knowledge_base_arn" {
  description = "Managed knowledge base ARN. Null while the module is disabled."
  value       = var.enabled ? aws_bedrockagent_knowledge_base.support[0].arn : null
}
