output "conversations_table_name" {
  description = "Conversation metadata table. Empty while the module is disabled."
  value       = var.enabled ? aws_dynamodb_table.conversations[0].name : ""
}

output "tool_executions_table_name" {
  description = "Tool-execution metadata table. Empty while the module is disabled."
  value       = var.enabled ? aws_dynamodb_table.tool_executions[0].name : ""
}
