output "memory_id" {
  description = "Hosted memory id. Null while the module is disabled."
  value       = var.enabled ? aws_bedrockagentcore_memory.session[0].id : null
}
