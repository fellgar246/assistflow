output "bucket_name" {
  description = "Knowledge bucket name. Empty while the module is disabled."
  value       = var.enabled ? aws_s3_bucket.knowledge[0].bucket : ""
}

output "bucket_arn" {
  description = "Knowledge bucket ARN. Empty while the module is disabled."
  value       = var.enabled ? aws_s3_bucket.knowledge[0].arn : ""
}
