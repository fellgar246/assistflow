output "gateway_arn" {
  description = "ARN of the hosted tool gateway. Null while the module is disabled."
  value       = var.enabled ? aws_bedrockagentcore_gateway.tools[0].gateway_arn : null
}

output "gateway_url" {
  description = "MCP endpoint for the hosted tool gateway. Null while the module is disabled."
  value       = var.enabled ? aws_bedrockagentcore_gateway.tools[0].gateway_url : null
}
