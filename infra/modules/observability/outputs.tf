output "dashboard_name" {
  description = "Dashboard name. Empty while the module is disabled."
  value       = try(aws_cloudwatch_dashboard.assistflow[0].dashboard_name, "")
}

output "api_log_group" {
  description = "API log group name. Empty while the module is disabled."
  value       = try(aws_cloudwatch_log_group.api[0].name, "")
}
