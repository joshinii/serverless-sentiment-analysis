# CloudWatch Alarms

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic           = "Sum"
  threshold           = "5"
  alarm_description   = "Alert when Lambda function errors exceed 5"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.sentiment_analyzer.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "inference_latency_p95" {
  alarm_name          = "${local.name_prefix}-inference-latency-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = var.inference_latency_p95_threshold_ms
  alarm_description   = "Alert when p95 inference latency is above threshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.sentiment_analyzer.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${local.name_prefix}-api-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "5XXError"
  namespace           = "AWS/ApiGateway"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "Alert when API Gateway 5xx errors exceed 10"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiName = aws_api_gateway_rest_api.main.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

# Structured log-based batch job metrics
resource "aws_cloudwatch_log_metric_filter" "batch_job_success" {
  name           = "${local.name_prefix}-batch-job-success"
  log_group_name = aws_cloudwatch_log_group.batch_worker_lambda.name
  pattern        = "{ $.function_name = \"batch_worker\" && $.event_type = \"invocation.completed\" && $.status = \"success\" }"

  metric_transformation {
    name      = "JobSuccess"
    namespace = "${local.name_prefix}/BatchJobs"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "batch_job_failure" {
  name           = "${local.name_prefix}-batch-job-failure"
  log_group_name = aws_cloudwatch_log_group.batch_worker_lambda.name
  pattern        = "{ $.function_name = \"batch_worker\" && $.event_type = \"record.failed\" && $.status = \"failed\" }"

  metric_transformation {
    name      = "JobFailure"
    namespace = "${local.name_prefix}/BatchJobs"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "batch_job_failure" {
  alarm_name          = "${local.name_prefix}-batch-job-failure"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "JobFailure"
  namespace           = "${local.name_prefix}/BatchJobs"
  period              = 300
  statistic           = "Sum"
  threshold           = var.batch_job_failure_alarm_threshold
  alarm_description   = "Alert when one or more batch jobs fail in a 5 minute window"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "batch_job_success_missing_when_failures" {
  alarm_name          = "${local.name_prefix}-batch-job-no-success-when-failing"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  alarm_description   = "Alert when failures are observed and no successful batch job completes in the same period"
  treat_missing_data  = "notBreaching"

  metric_query {
    id = "m_success"

    metric {
      metric_name = "JobSuccess"
      namespace   = "${local.name_prefix}/BatchJobs"
      period      = 300
      stat        = "Sum"
    }
  }

  metric_query {
    id = "m_failure"

    metric {
      metric_name = "JobFailure"
      namespace   = "${local.name_prefix}/BatchJobs"
      period      = 300
      stat        = "Sum"
    }
  }

  metric_query {
    id          = "e1"
    expression  = "IF((FILL(m_failure, 0) > 0) AND (FILL(m_success, 0) < 1), 1, 0)"
    label       = "BatchNoSuccessWhenFailing"
    return_data = true
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "batch_queue_depth" {
  alarm_name          = "${local.name_prefix}-batch-queue-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = var.batch_queue_depth_alarm_threshold
  alarm_description   = "Alert when batch queue depth stays high"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.batch_jobs.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "batch_dlq_messages" {
  alarm_name          = "${local.name_prefix}-batch-dlq-messages"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.batch_dlq_visible_messages_threshold
  alarm_description   = "Alert when DLQ has visible messages"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.batch_jobs_dlq.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "batch_worker_errors" {
  alarm_name          = "${local.name_prefix}-batch-worker-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Alert when batch worker Lambda errors exceed threshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.batch_worker.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "batch_worker_throttles" {
  alarm_name          = "${local.name_prefix}-batch-worker-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Alert when batch worker Lambda is throttled"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.batch_worker.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}

# SNS Topic for Alerts
resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
