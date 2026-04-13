# Secrets Management

resource "aws_secretsmanager_secret" "api_config" {
  name        = "${local.name_prefix}-api-config-${random_string.suffix.result}"
  description = "Application secrets (e.g. Third Party API Keys)"

  # Force delete for easy cleanup in this project
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "api_config_val" {
  secret_id = aws_secretsmanager_secret.api_config.id
  secret_string = jsonencode({
    THIRD_PARTY_API_KEY = var.third_party_api_key
  })
}
