output "schedule_name" {
  description = "Schedule rule name. Empty while the module is disabled."
  value       = var.enabled ? aws_cloudwatch_event_rule.maintenance[0].name : ""
}
