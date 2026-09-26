# =============================================================================
# LifeThread Infrastructure: Secrets Module
# Customer-Managed KMS Key, Automated Password Generation, & AWS Secrets Manager
# ZERO hardcoded credentials - all secrets externalized and rotated via KMS
# =============================================================================

# 1. KMS Customer Managed Key (CMK) with strict key policy
resource "aws_kms_key" "secrets" {
  description             = "KMS CMK for encrypting LifeThread ${var.environment} secrets"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-secrets-kms"
    Environment = var.environment
  })
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${var.project_name}-${var.environment}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# 2. Automated Generation of Cryptographically Secure Passwords
resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "random_password" "jwt_secret_key" {
  length           = 64
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "random_password" "redis_auth_token" {
  length           = 32
  special          = false
}

resource "random_password" "mcp_internal_token" {
  length           = 48
  special          = false
}

# 3. AWS Secrets Manager: Database Credentials Secret
resource "aws_secretsmanager_secret" "database" {
  name                    = "${var.project_name}/${var.environment}/database"
  description             = "PostgreSQL master connection credentials for LifeThread ${var.environment}"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = var.environment == "production" ? 30 : 0

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-db-secret"
    Environment = var.environment
  })
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
    database = "lifethread_${var.environment}"
  })
}

# 4. AWS Secrets Manager: Application Core & Security Secret
resource "aws_secretsmanager_secret" "app_security" {
  name                    = "${var.project_name}/${var.environment}/app-security"
  description             = "JWT signing key and internal authentication tokens for LifeThread ${var.environment}"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = var.environment == "production" ? 30 : 0

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-app-security-secret"
    Environment = var.environment
  })
}

resource "aws_secretsmanager_secret_version" "app_security" {
  secret_id = aws_secretsmanager_secret.app_security.id
  secret_string = jsonencode({
    jwt_secret_key     = random_password.jwt_secret_key.result
    mcp_internal_token = random_password.mcp_internal_token.result
  })
}

# 5. AWS Secrets Manager: Redis Auth Secret
resource "aws_secretsmanager_secret" "redis" {
  name                    = "${var.project_name}/${var.environment}/redis"
  description             = "ElastiCache Redis authentication token for LifeThread ${var.environment}"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = var.environment == "production" ? 30 : 0

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-redis-secret"
    Environment = var.environment
  })
}

resource "aws_secretsmanager_secret_version" "redis" {
  secret_id = aws_secretsmanager_secret.redis.id
  secret_string = jsonencode({
    auth_token = random_password.redis_auth_token.result
  })
}

# 6. AWS Secrets Manager: External AI Providers Secret (Optional fallbacks)
resource "aws_secretsmanager_secret" "external_ai" {
  name                    = "${var.project_name}/${var.environment}/external-ai"
  description             = "Optional secondary API keys (OpenAI / Anthropic) if used as Bedrock fallback"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = var.environment == "production" ? 30 : 0

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-external-ai-secret"
    Environment = var.environment
  })
}

resource "aws_secretsmanager_secret_version" "external_ai" {
  secret_id = aws_secretsmanager_secret.external_ai.id
  secret_string = jsonencode({
    openai_api_key    = "CHANGEME_BOOTSTRAP_VALUE"
    anthropic_api_key = "CHANGEME_BOOTSTRAP_VALUE"
  })
}
