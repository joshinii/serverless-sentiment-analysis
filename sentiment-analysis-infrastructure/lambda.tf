# Lambda Functions (Placeholder deployment packages)
data "archive_file" "sentiment_lambda" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/sentiment_analyzer.zip"

  source {
    content  = <<-EOT
      def lambda_handler(event, context):
          return {
              'statusCode': 200,
              'body': '{"message": "Deploy actual code to replace this placeholder"}'
          }
    EOT
    filename = "lambda_function.py"
  }
}

data "archive_file" "batch_lambda" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/batch_processor.zip"

  source {
    content  = <<-EOT
      def lambda_handler(event, context):
          return {
              'statusCode': 200,
              'body': '{"message": "Deploy actual code to replace this placeholder"}'
          }
    EOT
    filename = "batch_submitter.py"
  }
}

data "archive_file" "batch_worker_lambda" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/batch_worker.zip"

  source {
    content  = <<-EOT
      def lambda_handler(event, context):
          return {
              'batchItemFailures': []
          }
    EOT
    filename = "batch_worker.py"
  }
}

data "archive_file" "history_lambda" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/history.zip"

  source {
    content  = <<-EOT
      def lambda_handler(event, context):
          return {
              'statusCode': 200,
              'body': '{"message": "Deploy actual code to replace this placeholder"}'
          }
    EOT
    filename = "history_handler.py"
  }
}

# Lambda: Sentiment Analyzer
resource "aws_lambda_function" "sentiment_analyzer" {
  filename         = data.archive_file.sentiment_lambda.output_path
  function_name    = "${local.name_prefix}-analyze-sentiment"
  role             = aws_iam_role.sentiment_lambda.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.sentiment_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 3008
  ephemeral_storage {
    size = 2048 # Increase /tmp size for model download
  }

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.sentiment_analytics.name
      MODEL_BUCKET   = aws_s3_bucket.data.id
      MODEL_PATH     = "/tmp/model_assets"
      LOG_LEVEL      = "INFO"
      SECRET_ARN     = aws_secretsmanager_secret.api_config.arn
    }
  }

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${local.name_prefix}-analyze-sentiment"
    }
  )
}

# Lambda: Batch Processor
resource "aws_lambda_function" "batch_processor" {
  filename         = data.archive_file.batch_lambda.output_path
  function_name    = "${local.name_prefix}-batch-processor"
  role             = aws_iam_role.batch_submitter_lambda.arn
  handler          = "batch_submitter.lambda_handler"
  source_code_hash = data.archive_file.batch_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      DYNAMODB_TABLE   = aws_dynamodb_table.sentiment_analytics.name
      JOB_QUEUE_URL    = aws_sqs_queue.batch_jobs.url
      JOB_INPUT_BUCKET = aws_s3_bucket.data.id
      LOG_LEVEL        = "INFO"
    }
  }

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${local.name_prefix}-batch-processor"
    }
  )
}

# Lambda: Batch Worker
resource "aws_lambda_function" "batch_worker" {
  filename         = data.archive_file.batch_worker_lambda.output_path
  function_name    = "${local.name_prefix}-batch-worker"
  role             = aws_iam_role.batch_lambda.arn
  handler          = "batch_worker.lambda_handler"
  source_code_hash = data.archive_file.batch_worker_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 3008
  ephemeral_storage {
    size = 2048
  }

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.sentiment_analytics.name
      MODEL_BUCKET   = aws_s3_bucket.data.id
      MODEL_PATH     = "/tmp/model_assets"
      LOG_LEVEL      = "INFO"
    }
  }

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${local.name_prefix}-batch-worker"
    }
  )
}

# Lambda: History Handler
resource "aws_lambda_function" "history_handler" {
  filename         = data.archive_file.history_lambda.output_path
  function_name    = "${local.name_prefix}-history"
  role             = aws_iam_role.history_lambda.arn
  handler          = "history_handler.lambda_handler"
  source_code_hash = data.archive_file.history_lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.sentiment_analytics.name
    }
  }

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${local.name_prefix}-history"
    }
  )
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "sentiment_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.sentiment_analyzer.function_name}"
  retention_in_days = 7
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "batch_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.batch_processor.function_name}"
  retention_in_days = 7
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "batch_worker_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.batch_worker.function_name}"
  retention_in_days = 7
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "history_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.history_handler.function_name}"
  retention_in_days = 7
  tags              = local.common_tags
}

# Lambda Permissions
resource "aws_lambda_permission" "sentiment_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sentiment_analyzer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*/*"
}

resource "aws_lambda_permission" "batch_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.batch_processor.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*/*"
}

resource "aws_lambda_permission" "history_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.history_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*/*"
}

resource "aws_lambda_event_source_mapping" "batch_worker_sqs" {
  event_source_arn                   = aws_sqs_queue.batch_jobs.arn
  function_name                      = aws_lambda_function.batch_worker.arn
  batch_size                         = 10
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
  enabled                            = true
}
