output "user_pool_id" {
  description = "User pool id. Empty while the module is disabled."
  value       = try(aws_cognito_user_pool.main[0].id, "")
}

output "user_pool_client_id" {
  description = "App client id. Empty while the module is disabled."
  value       = try(aws_cognito_user_pool_client.web[0].id, "")
}

output "issuer" {
  description = "Token issuer for the pool. Empty while the module is disabled."
  value       = var.enabled ? "https://${aws_cognito_user_pool.main[0].endpoint}" : ""
}
