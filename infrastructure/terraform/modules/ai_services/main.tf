# =============================================================================
# LifeThread Infrastructure: AI Services Module
# IAM Roles & Policies for Amazon Bedrock, AgentCore, and Strands Knowledge Bases
# S3 Bucket with KMS Encryption and Versioning for Context Strands
# =============================================================================

# 1. S3 Storage for Bedrock Strands & Context Documents
resource "aws_s3_bucket" "strands" {
  bucket        = "${var.project_name}-${var.environment}-strands-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "production"

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-strands-bucket"
    Environment = var.environment
  })
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_versioning" "strands" {
  bucket = aws_s3_bucket.strands.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "strands" {
  bucket = aws_s3_bucket.strands.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "strands" {
  bucket                  = aws_s3_bucket.strands.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 2. IAM Policy for Application ECS Task to access Amazon Bedrock
resource "aws_iam_policy" "bedrock_access" {
  name        = "${var.project_name}-${var.environment}-bedrock-access"
  description = "Allows LifeThread application containers to invoke Bedrock foundation models, AgentCore, and Knowledge Bases"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream",
          "bedrock:GetFoundationModel",
          "bedrock:ListFoundationModels"
        ]
        Resource = "*"
      },
      {
        Sid    = "BedrockAgentCoreInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeAgent"
        ]
        Resource = "*"
      },
      {
        Sid    = "BedrockKnowledgeBaseRetrieval"
        Effect = "Allow"
        Action = [
          "bedrock:Retrieve",
          "bedrock:RetrieveAndGenerate"
        ]
        Resource = "*"
      },
      {
        Sid    = "StrandsS3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.strands.arn,
          "${aws_s3_bucket.strands.arn}/*"
        ]
      }
    ]
  })

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-bedrock-policy"
    Environment = var.environment
  })
}
