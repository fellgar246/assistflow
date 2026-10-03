output "api_base_url" {
  description = "Invoke URL for the dev API. Empty while the module is disabled."
  value       = var.enabled ? aws_apigatewayv2_api.http[0].api_endpoint : ""
}

output "function_name" {
  description = "Probe function name. Empty while the module is disabled."
  value       = var.enabled ? aws_lambda_function.api[0].function_name : ""
}
