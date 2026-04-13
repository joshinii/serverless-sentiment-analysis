variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "sentiment-platform"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-west-2"
}

variable "alert_email" {
  description = "Email address for CloudWatch alerts"
  type        = string
}

variable "third_party_api_key" {
  description = "Third-party API key stored in Secrets Manager"
  type        = string
  sensitive   = true
}

variable "batch_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for the batch jobs queue; should exceed batch Lambda timeout"
  type        = number
  default     = 330
}

variable "batch_queue_message_retention_seconds" {
  description = "Message retention period for the batch jobs queue"
  type        = number
  default     = 1209600
}

variable "batch_queue_max_receive_count" {
  description = "How many receives before a message is moved to DLQ"
  type        = number
  default     = 5
}

variable "inference_latency_p95_threshold_ms" {
  description = "p95 latency threshold in milliseconds for sentiment inference Lambda"
  type        = number
  default     = 2500
}

variable "batch_job_failure_alarm_threshold" {
  description = "Number of failed batch jobs in 5 minutes before alerting"
  type        = number
  default     = 1
}

variable "batch_queue_depth_alarm_threshold" {
  description = "Average visible messages in batch queue before alerting"
  type        = number
  default     = 50
}

variable "batch_dlq_visible_messages_threshold" {
  description = "Visible DLQ messages threshold before alerting"
  type        = number
  default     = 1
}

variable "api_throttle_rate_limit" {
  description = "Steady-state request rate limit (RPS) for API Gateway stage"
  type        = number
  default     = 25
}

variable "api_throttle_burst_limit" {
  description = "Burst request limit for API Gateway stage"
  type        = number
  default     = 50
}

variable "enable_api_key" {
  description = "Enable API key requirement and usage plan for non-OPTIONS API methods"
  type        = bool
  default     = false
}

variable "api_key_throttle_rate_limit" {
  description = "Per-key steady-state request rate limit (RPS) when API key is enabled"
  type        = number
  default     = 10
}

variable "api_key_throttle_burst_limit" {
  description = "Per-key burst request limit when API key is enabled"
  type        = number
  default     = 20
}

variable "api_key_quota_limit" {
  description = "Per-key monthly request quota when API key is enabled"
  type        = number
  default     = 100000
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "SentimentAnalysis"
    ManagedBy   = "Terraform"
    Environment = "Development"
  }
}
