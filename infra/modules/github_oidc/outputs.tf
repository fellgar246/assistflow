output "deploy_role_arn" {
  description = "Role assumed by GitHub Actions. Empty while the module is disabled."
  value       = var.enabled ? aws_iam_role.deploy[0].arn : ""
}
