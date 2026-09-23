output "tags" {
  description = "Tags required on every managed resource."
  value = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = var.cost_center
    AutoCleanup = "true"
  }
}
