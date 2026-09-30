terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no bucket.
resource "aws_s3_bucket" "knowledge" {
  count = var.enabled ? 1 : 0

  bucket_prefix = var.name_prefix
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_public_access_block" "knowledge" {
  count = var.enabled ? 1 : 0

  bucket                  = aws_s3_bucket.knowledge[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "knowledge" {
  count = var.enabled ? 1 : 0

  bucket = aws_s3_bucket.knowledge[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
