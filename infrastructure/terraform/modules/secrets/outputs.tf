output "kms_key_arn" {
  value       = aws_kms_key.secrets.arn
  description = "ARN of the KMS Customer Managed Key used for secrets encryption"
}

output "db_secret_arn" {
  value       = aws_secretsmanager_secret.database.arn
  description = "ARN of the database credentials secret"
}

output "db_password" {
  value       = random_password.db_password.result
  sensitive   = true
  description = "Generated database password (sensitive)"
}

output "db_username" {
  value       = var.db_username
  description = "Database master username"
}

output "app_security_secret_arn" {
  value       = aws_secretsmanager_secret.app_security.arn
  description = "ARN of the application security secret (JWT & internal tokens)"
}

output "redis_secret_arn" {
  value       = aws_secretsmanager_secret.redis.arn
  description = "ARN of the Redis authentication secret"
}

output "redis_auth_token" {
  value       = random_password.redis_auth_token.result
  sensitive   = true
  description = "Generated Redis auth token (sensitive)"
}

output "external_ai_secret_arn" {
  value       = aws_secretsmanager_secret.external_ai.arn
  description = "ARN of external AI fallback secret"
}
