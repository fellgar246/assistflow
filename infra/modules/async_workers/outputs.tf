output "queue_url" {
  description = "Side-effect queue URL. Empty while async workers are disabled."
  value       = var.enabled ? aws_sqs_queue.side_effects[0].url : ""
}

output "event_bus_name" {
  description = "Event bus name. Empty while async workers are disabled."
  value       = var.enabled ? aws_cloudwatch_event_bus.side_effects[0].name : ""
}
