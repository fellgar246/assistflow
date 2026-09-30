terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# Disabled by default. count = 0 creates no knowledge base, role, or data source.
resource "aws_iam_role" "knowledge" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-knowledge"
  tags = var.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "bedrock.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "knowledge" {
  count = var.enabled ? 1 : 0

  name = "${var.name}-knowledge"
  role = aws_iam_role.knowledge[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [var.bucket_arn, "${var.bucket_arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = var.embedding_model_arn
      }
    ]
  })
}

resource "aws_bedrockagent_knowledge_base" "support" {
  count = var.enabled ? 1 : 0

  name     = var.name
  role_arn = aws_iam_role.knowledge[0].arn
  tags     = var.tags

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = var.embedding_model_arn
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = var.collection_arn
      vector_index_name = var.vector_index_name
      field_mapping {
        vector_field   = "embedding"
        text_field     = "text"
        metadata_field = "metadata"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.bucket_arn != "" && var.embedding_model_arn != "" && var.collection_arn != ""
      error_message = "Managed retrieval needs a document bucket, an embedding model, and a vector collection."
    }
  }
}

resource "aws_bedrockagent_data_source" "policies" {
  count = var.enabled ? 1 : 0

  knowledge_base_id = aws_bedrockagent_knowledge_base.support[0].id
  name              = "policies"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = var.bucket_arn
    }
  }
}
