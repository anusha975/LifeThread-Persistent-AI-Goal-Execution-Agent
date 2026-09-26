# =============================================================================
# LifeThread Infrastructure: Redis Cache Module
# Production-ready AWS ElastiCache Redis 7 with TLS encryption in-transit,
# KMS encryption at rest, AUTH token enforcement, and automated failover
# =============================================================================

# 1. Subnet Group across isolated data subnets
resource "aws_elasticache_subnet_group" "redis" {
  name        = "${var.project_name}-${var.environment}-redis-subnet-group"
  description = "Isolated data subnet group for LifeThread ${var.environment} Redis"
  subnet_ids  = var.subnet_ids

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-redis-subnet-group"
    Environment = var.environment
  })
}

# 2. Redis Parameter Group
resource "aws_elasticache_parameter_group" "redis" {
  name        = "${var.project_name}-${var.environment}-redis7-params"
  family      = "redis7"
  description = "Redis 7 parameter group with maxmemory-policy eviction"

  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-redis-params"
    Environment = var.environment
  })
}

# 3. Redis Replication Group
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${var.project_name}-${var.environment}-cache"
  description                = "LifeThread ${var.environment} Redis replication group"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.node_type
  num_cache_clusters         = var.num_cache_clusters
  port                       = 6379

  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [var.security_group_id]
  parameter_group_name       = aws_elasticache_parameter_group.redis.name

  transit_encryption_enabled = true
  auth_token                 = var.auth_token
  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn

  automatic_failover_enabled = var.num_cache_clusters > 1
  multi_az_enabled           = var.num_cache_clusters > 1
  auto_minor_version_upgrade = true
  maintenance_window         = "sun:06:00-sun:07:00"
  snapshot_window            = "05:00-06:00"
  snapshot_retention_limit   = var.environment == "production" ? 7 : 0

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-redis"
    Environment = var.environment
  })
}
