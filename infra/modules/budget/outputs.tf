output "budget_name" {
  description = "Name of the monthly budget when the module is enabled."
  value       = var.enabled ? var.name : null
}
