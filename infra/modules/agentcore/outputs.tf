output "agent_runtime_arn" {
  description = "ARN of the hosted runtime. Null while the module is disabled."
  value       = var.enabled ? aws_bedrockagentcore_agent_runtime.support[0].agent_runtime_arn : null
}

output "runtime_role_name" {
  description = "Execution role for the hosted runtime. Empty while the module is disabled."
  value       = var.enabled ? aws_iam_role.runtime[0].name : ""
}
