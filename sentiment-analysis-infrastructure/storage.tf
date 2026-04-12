# S3 Buckets

# Frontend bucket
resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name_prefix}-frontend-${random_string.suffix.result}"
  force_destroy = true

  tags = merge(
    local.common_tags,
    {
      Name    = "${local.name_prefix}-frontend"
      Purpose = "Static website hosting"
    }
  )
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 bucket policy for CloudFront defined in cloudfront.tf or here?
# Usually kept with bucket or with distribution. Original had it under S3 section.
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOAI"
        Effect = "Allow"
        Principal = {
          AWS = aws_cloudfront_origin_access_identity.frontend.iam_arn
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.frontend.arn}/*"
      }
    ]
  })
}

# Data bucket (for batch processing)
resource "aws_s3_bucket" "data" {
  bucket        = "${local.name_prefix}-data-${random_string.suffix.result}"
  force_destroy = true

  tags = merge(
    local.common_tags,
    {
      Name    = "${local.name_prefix}-data"
      Purpose = "Batch file storage"
    }
  )
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "delete-old-files"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
  }
}

# DynamoDB Table
resource "aws_dynamodb_table" "sentiment_analytics" {
  name         = "${local.name_prefix}-analytics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${local.name_prefix}-analytics"
    }
  )
}

# SQS Queues for async batch processing
resource "aws_sqs_queue" "batch_jobs_dlq" {
  name                      = "${local.name_prefix}-batch-jobs-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = merge(
    local.common_tags,
    {
      Name    = "${local.name_prefix}-batch-jobs-dlq"
      Purpose = "Dead-letter queue for failed batch jobs"
    }
  )
}

resource "aws_sqs_queue" "batch_jobs" {
  name                       = "${local.name_prefix}-batch-jobs"
  visibility_timeout_seconds = var.batch_queue_visibility_timeout_seconds
  message_retention_seconds  = var.batch_queue_message_retention_seconds
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.batch_jobs_dlq.arn
    maxReceiveCount     = var.batch_queue_max_receive_count
  })

  tags = merge(
    local.common_tags,
    {
      Name    = "${local.name_prefix}-batch-jobs"
      Purpose = "Async batch job queue"
    }
  )
}
